import secrets
import uuid
import json
import io
import numpy as np
import shutil
import threading
from pathlib import Path
from fastapi.responses import RedirectResponse, FileResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import models
from database import get_db, SessionLocal
from security import get_current_admin, pwd_context, sanitize_email_name_part
from datetime import datetime, timedelta, date
import os
from fastapi import Request, Response, Form, UploadFile, File
from fastapi.templating import Jinja2Templates
from clip_test import find_matches_in_dataset, describe_item, get_clip_components, get_text_embedding, get_multi_image_embedding
import torch
from PIL import Image
import json
from sqlalchemy.exc import IntegrityError
from models import SettingsUpdate
from security import get_current_user
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from utils import save_file, resolve_category_name
from sqlalchemy import or_



class AdminCreate(BaseModel):
    full_name: str
    email: EmailStr
    permissions: List[str]
    department: Optional[str] = None
    section: Optional[str] = None

# For Bulk Student Registration (Matching your new User columns)
class StudentCreate(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    course: Optional[str] = None
    section: Optional[str] = None

class StudentBulkImport(BaseModel):
    student_id: str
    last_name: str
    first_name: str
    middle_name: Optional[str] = ""
    program: str
    level: str

class BulkRegisterRequest(BaseModel):
    students: List[StudentBulkImport]

templates = Jinja2Templates(directory="templates")
# Change your directory definition
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Unified path: everything goes into static/uploads
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")

router = APIRouter(prefix="/admin", tags=["Admin"])

BULK_REGISTRATION_JOBS: dict[str, dict] = {}
BULK_JOB_LOCK = threading.Lock()
STUDENT_ACCESS_PERMISSION = "Student-Portal-Access"
DELETE_QUEUE_PERMISSION = "__PENDING_DELETE__"

class PermissionUpdate(BaseModel):
    permissions: list[str]


class StudentActivationRequest(BaseModel):
    user_ids: list[int]


def user_is_faculty_account(user: models.User) -> bool:
    if not user or user.is_admin:
        return False
    department = str(user.department or "").strip()
    course = str(user.course or "").strip()
    section = str(user.section or "").strip()
    return bool(department and department != "N/A" and not course and not section)


def parse_permissions(raw_permissions) -> list[str]:
    try:
        if isinstance(raw_permissions, str):
            return json.loads(raw_permissions)
        return raw_permissions or []
    except Exception:
        return []


def ensure_pending_claim_for_pair(
    db: Session,
    *,
    lost_item: models.Item,
    found_item: models.Item,
    claimant_id: int | None,
    similarity_score: str = ""
) -> models.Claim:
    existing_claim = db.query(models.Claim).filter(
        models.Claim.lost_item_id == lost_item.id,
        models.Claim.found_item_id == found_item.id,
        models.Claim.status.in_(["pending", "approved"])
    ).first()
    if existing_claim:
        return existing_claim

    new_claim = models.Claim(
        lost_item_id=lost_item.id,
        found_item_id=found_item.id,
        claimant_id=claimant_id,
        similarity_score=similarity_score,
        status="pending"
    )
    db.add(new_claim)
    return new_claim


def student_has_portal_access(user: models.User) -> bool:
    return STUDENT_ACCESS_PERMISSION in parse_permissions(user.permissions)


def user_is_pending_delete(user: models.User) -> bool:
    return DELETE_QUEUE_PERMISSION in parse_permissions(user.permissions)


def get_assignable_permissions(admin: models.User) -> set[str]:
    permissions = set(parse_permissions(admin.permissions))
    permissions.discard(STUDENT_ACCESS_PERMISSION)
    permissions.discard(DELETE_QUEUE_PERMISSION)
    return permissions


def notify_admin(
    db: Session,
    message: str,
    notif_type: str = "new_report",
    related_id: int = None,
    target_url: str | None = None
):
    new_notif = models.Notification(
        message=message,
        type=notif_type,
        related_id=related_id,
        target_url=target_url,
        is_read=False,  # Default to unread
        created_at=datetime.utcnow() # Good for sorting the notification list
    )
    db.add(new_notif)
    db.commit()

def check_permission(required_permission: str):
    def permission_dependency(
        admin: models.User = Depends(get_current_admin)
    ):
        # Convert string JSON to list if necessary
        permissions = parse_permissions(admin.permissions)

        if required_permission not in permissions:
            raise HTTPException(
                status_code=403,
                detail=f"Access Denied: Requires {required_permission}"
            )

        return admin
    return permission_dependency
def create_admin_notification(
    db: Session,
    message: str,
    notif_type: str,
    related_id: int,
    target_url: str | None = None
):
    if target_url is None:
        if notif_type == "user_management_students":
            target_url = "/admin/User-Management?tab=student"
        elif notif_type == "user_management_admin":
            target_url = "/admin/User-Management?tab=admin"
        elif notif_type == "match":
            target_url = "/admin/Claim-Management"
        elif notif_type == "chat":
            target_url = "/admin/Messages"
        else:
            target_url = "/admin/Found_Items_Report"

    notif = models.Notification(
        message=message,
        type=notif_type,
        related_id=related_id,
        target_url=target_url,
        is_read=False,         # Ensure it starts as unread
        created_at=datetime.utcnow() # Add the time it happened
    )
    db.add(notif)
    db.commit()
    db.refresh(notif) # This allows you to access the new notif.id immediately
    return notif


def update_bulk_job(job_id: str, **changes):
    with BULK_JOB_LOCK:
        job = BULK_REGISTRATION_JOBS.get(job_id)
        if not job:
            return None
        job.update(changes)
        return job


def infer_employee_account_label(identifier: str) -> str:
    suffix = str(identifier or "").strip().upper()[-1:]
    if suffix in {"F", "P"}:
        return "Faculty / Teacher"
    if suffix == "A":
        return "Administrative Personnel"
    return "Employee"


def build_faculty_email(first_name: str, last_name: str) -> str:
    first_part = sanitize_email_name_part(first_name)
    last_part = sanitize_email_name_part(last_name)
    if not first_part or not last_part:
        return ""
    return f"{first_part}.{last_part}@novaliches.sti.edu.ph"


def build_item_match_text(item: models.Item) -> str:
    parts = [
        item.category or "",
        item.brand or "",
        item.color or "",
        item.location or "",
        item.description or "",
    ]
    return " ".join(part.strip() for part in parts if part and str(part).strip())


def normalize_match_value(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def store_item_as_reference(
    db: Session,
    item: models.Item,
    reason: str = "disposed"
) -> models.ReferenceItem:
    existing_reference = None
    if item.id is not None:
        existing_reference = db.query(models.ReferenceItem).filter(
            models.ReferenceItem.source_item_id == item.id
        ).first()

    if existing_reference:
        return existing_reference

    reference_item = models.ReferenceItem(
        source_item_id=item.id,
        category_id=item.category_id,
        status=item.status,
        category=item.category,
        department=item.department,
        description=item.description,
        image_path=item.image_path,
        image_embedding=item.image_embedding,
        brand=item.brand,
        color=item.color,
        location=item.location,
        date=item.date,
        time_found=item.time_found,
        user_id=item.user_id,
        archived=item.archived,
        is_surrendered=item.is_surrendered,
        deleted_reason=reason,
        created_at=item.created_at,
        deleted_at=datetime.utcnow(),
    )
    db.add(reference_item)
    db.flush()
    return reference_item


def compute_item_match_score(lost_item: models.Item, found_item: models.Item) -> float | None:
    if not lost_item.image_embedding or not found_item.image_embedding:
        return None

    try:
        lost_vec = np.array(json.loads(lost_item.image_embedding)).flatten()
        found_vec = np.array(json.loads(found_item.image_embedding)).flatten()
    except Exception:
        return None

    image_score = float(np.dot(lost_vec, found_vec))

    text_score = 0.0
    lost_text = build_item_match_text(lost_item)
    found_text = build_item_match_text(found_item)
    if lost_text and found_text:
        try:
            lost_text_vec = get_text_embedding(lost_text)
            found_text_vec = get_text_embedding(found_text)
            text_score = float(np.dot(lost_text_vec, found_text_vec))
        except Exception:
            text_score = 0.0

    score = (image_score * 0.7) + (text_score * 0.3)

    lost_brand = normalize_match_value(lost_item.brand)
    found_brand = normalize_match_value(found_item.brand)
    if lost_brand and found_brand and lost_brand == found_brand:
        score += 0.08
    elif lost_brand and found_brand and lost_brand != found_brand:
        score -= 0.12

    lost_color = normalize_match_value(lost_item.color)
    found_color = normalize_match_value(found_item.color)
    if lost_color and found_color and lost_color == found_color:
        score += 0.05
    elif lost_color and found_color and lost_color != found_color:
        score -= 0.20

    lost_location = normalize_match_value(lost_item.location)
    found_location = normalize_match_value(found_item.location)
    if lost_location and found_location and (
        lost_location in found_location or found_location in lost_location
    ):
        score += 0.03

    return round(score, 4)


def process_bulk_registration_job(job_id: str, users_list: list[dict], duplicate_action: str):
    db = SessionLocal()
    started_at = datetime.utcnow()

    results = []
    seen_student_nos = set()
    seen_emails = set()
    created_count = 0
    replaced_count = 0
    ignored_count = 0

    total_students = len(users_list)
    update_bulk_job(
        job_id,
        status="running",
        started_at=started_at.isoformat(),
        progress=0,
        processed=0,
        total=total_students,
        message="Bulk registration is running in the background."
    )

    try:
        for index, s in enumerate(users_list, start=1):
            source_type = str(s.get("source_type", "student")).strip().lower()
            is_employee_import = source_type == "employee"
            s_id = str(s.get("student_no", "")).strip()
            last_n = str(s.get("last_name", "")).strip()
            first_n = str(s.get("first_name", "")).strip()
            middle_n = str(s.get("middle_name", "")).strip()
            course = str(s.get("course", "")).strip()
            level = str(s.get("level", "")).strip()
            batch_val = str(s.get("batch_id", "")).strip()
            department = str(s.get("department", "")).strip()
            display_name = str(s.get("display_name", "")).strip()
            initial_permissions = [STUDENT_ACCESS_PERMISSION] if is_employee_import else []

            last_6 = s_id[-6:]
            email_addr = (
                build_faculty_email(first_n, last_n)
                if is_employee_import and s_id
                else (f"{last_n.lower().replace(' ', '')}.{last_6}@novaliches.sti.edu.ph" if s_id and last_n else "")
            )
            default_pass = f"STI{s_id}" if s_id else ""
            new_full_name = (
                display_name
                or f"{first_n} {middle_n} {last_n}".replace("  ", " ").strip()
            )

            if is_employee_import and not department:
                department = infer_employee_account_label(s_id)
            existing_user = None

            try:
                if not s_id or not first_n or not last_n:
                    ignored_count += 1
                    results.append({
                        "email": email_addr,
                        "student_no": s_id or "N/A",
                        "full_name": new_full_name or "Invalid Row",
                        "course": course,
                        "department": department,
                        "level": level,
                        "batch_id": batch_val,
                        "temp_password": "",
                        "status": "Ignored - Missing required fields"
                    })
                elif s_id in seen_student_nos or email_addr in seen_emails:
                    ignored_count += 1
                    results.append({
                        "email": email_addr,
                        "student_no": s_id,
                        "full_name": new_full_name,
                        "course": course,
                        "department": department,
                        "level": level,
                        "batch_id": batch_val,
                        "temp_password": "",
                        "status": "Ignored - Duplicate in upload"
                    })
                else:
                    seen_student_nos.add(s_id)
                    seen_emails.add(email_addr)

                    existing_user = db.query(models.User).filter(
                        (models.User.student_no == s_id) | (models.User.email == email_addr)
                    ).first()

                    if existing_user:
                        if existing_user.is_admin:
                            ignored_count += 1
                            results.append({
                                "email": email_addr,
                                "student_no": s_id,
                                "full_name": new_full_name,
                                "course": course,
                                "department": department,
                                "level": level,
                                "batch_id": batch_val,
                                "temp_password": "",
                                "status": "Ignored - Conflicts with existing admin"
                            })
                        elif duplicate_action == "ignore":
                            ignored_count += 1
                            results.append({
                                "email": existing_user.email,
                                "student_no": existing_user.student_no,
                                "full_name": existing_user.full_name or new_full_name,
                                "course": existing_user.course or course,
                                "department": existing_user.department or department,
                                "level": existing_user.level or level,
                                "batch_id": existing_user.batch_id or batch_val,
                                "temp_password": "",
                                "status": "Ignored - Already registered"
                            })
                        else:
                            existing_user.first_name = first_n
                            existing_user.middle_name = middle_n
                            existing_user.last_name = last_n
                            existing_user.full_name = new_full_name
                            existing_user.student_no = s_id
                            existing_user.email = email_addr
                            existing_user.course = course
                            existing_user.department = department
                            existing_user.level = level
                            existing_user.batch_id = batch_val
                            existing_user.hashed_password = pwd_context.hash(default_pass)
                            existing_user.must_change_password = True
                            existing_user.is_archived = False
                            existing_user.is_admin = False
                            existing_user.permissions = json.dumps(initial_permissions)

                            replaced_count += 1
                            results.append({
                                "email": email_addr,
                                "student_no": s_id,
                                "full_name": new_full_name,
                                "course": course,
                                "department": department,
                                "level": level,
                                "batch_id": batch_val,
                                "temp_password": default_pass,
                                "status": "Replaced existing user"
                            })
                    else:
                        user_obj = models.User(
                            first_name=first_n,
                            middle_name=middle_n,
                            last_name=last_n,
                            full_name=new_full_name,
                            student_no=s_id,
                            email=email_addr,
                            course=course,
                            department=department,
                            level=level,
                            batch_id=batch_val,
                            hashed_password=pwd_context.hash(default_pass),
                            is_admin=False,
                            must_change_password=True,
                            permissions=json.dumps(initial_permissions)
                        )
                        db.add(user_obj)
                        created_count += 1

                        results.append({
                            "email": email_addr,
                            "student_no": s_id,
                            "full_name": new_full_name,
                                "course": course,
                                "department": department,
                                "level": level,
                                "batch_id": batch_val,
                                "temp_password": default_pass,
                            "status": "Created"
                        })

                    if results and results[-1].get("status") in {"Created", "Replaced existing user"}:
                        db.commit()
            except IntegrityError:
                db.rollback()

                last_result = results[-1] if results else None
                if last_result and last_result.get("student_no") == s_id:
                    last_result["temp_password"] = ""
                    last_result["status"] = "Ignored - Duplicate email or student number conflict"

                    if duplicate_action == "replace" and existing_user and not existing_user.is_admin:
                        replaced_count = max(replaced_count - 1, 0)
                    else:
                        created_count = max(created_count - 1, 0)
                ignored_count += 1
            except Exception as row_error:
                db.rollback()
                ignored_count += 1
                results.append({
                    "email": email_addr,
                    "student_no": s_id or "N/A",
                    "full_name": new_full_name or "Invalid Row",
                    "course": course,
                    "department": department,
                    "level": level,
                    "batch_id": batch_val,
                    "temp_password": "",
                    "status": f"Failed - {str(row_error)[:120]}"
                })

            update_bulk_job(
                job_id,
                processed=index,
                progress=int((index / total_students) * 100) if total_students else 100,
                summary={
                    "total": total_students,
                    "created": created_count,
                    "replaced": replaced_count,
                    "ignored": ignored_count,
                    "duplicate_action": duplicate_action
                }
            )

        finished_at = datetime.utcnow()
        update_bulk_job(
            job_id,
            status="completed",
            finished_at=finished_at.isoformat(),
            progress=100,
            processed=total_students,
            message="Bulk registration completed.",
            results=results,
            summary={
                "total": total_students,
                "created": created_count,
                "replaced": replaced_count,
                "ignored": ignored_count,
                "duplicate_action": duplicate_action
            }
        )

        create_admin_notification(
            db,
            f"User batch registration completed. Created {created_count}, replaced {replaced_count}, ignored {ignored_count}.",
            "user_management_students",
            None
        )
    except Exception as e:
        db.rollback()
        print(f"CRITICAL REGISTRATION ERROR: {e}")
        update_bulk_job(
            job_id,
            status="failed",
            finished_at=datetime.utcnow().isoformat(),
            message=str(e),
            error=str(e)
        )
    finally:
        db.close()
    

from datetime import datetime

# ROUTE 1: Toggle Archive (Soft Delete/Restore)
@router.post("/toggle-archive/{user_id}")
async def toggle_archive(
    user_id: int, 
    archive: bool, 
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    permissions = parse_permissions(user.permissions)
    user.is_archived = archive

    # 🔥 ADD THIS BLOCK
    if archive:
        user.permissions = json.dumps([])  # remove all permissions
    else:
        permissions = [permission for permission in permissions if permission != DELETE_QUEUE_PERMISSION]
        user.permissions = json.dumps(permissions)

    # Optional: track when it happened
    user.archived_at = datetime.now() if archive else None
    
    db.commit()
    db.refresh(user)  # optional but good practice

    status = "archived" if archive else "restored"
    return {"message": f"User {user.full_name} has been {status}."}

@router.post("/move-to-delete/{user_id}")
async def move_user_to_delete(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Delete"))
):
    user = db.query(models.User).filter(models.User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_archived:
        raise HTTPException(status_code=400, detail="Only archived users can be moved to delete.")

    permissions = parse_permissions(user.permissions)
    if DELETE_QUEUE_PERMISSION not in permissions:
        permissions.append(DELETE_QUEUE_PERMISSION)
        user.permissions = json.dumps(permissions)
        db.commit()

    return {"message": f"User {user.full_name} moved to Delete tab."}

# ROUTE 2: Permanent Delete (Hard Delete)
@router.delete("/permanent-delete/{user_id}")
async def permanent_delete(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        delete_user_and_related_records(db, user)
        db.commit()
        
        return {"message": "User and all related records (messages, claims, items) deleted."}

    except Exception as e:
        db.rollback()
        print(f"Delete Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Database Integrity Error: User has active records.")

def delete_user_and_related_records(db: Session, user: models.User):
    user_id = user.id
    db.query(models.ClaimDecisionReport).filter(
        models.ClaimDecisionReport.created_by_admin_id == user_id
    ).update(
        {models.ClaimDecisionReport.created_by_admin_id: None},
        synchronize_session=False
    )
    db.query(models.ClaimProof).filter(
        models.ClaimProof.claimant_user_id == user_id
    ).update(
        {models.ClaimProof.claimant_user_id: None},
        synchronize_session=False
    )
    db.query(models.Message).filter(
        (models.Message.sender_id == user_id) |
        (models.Message.recipient_id == user_id)
    ).delete(synchronize_session=False)
    db.query(models.Claim).filter(models.Claim.claimant_id == user_id).delete(synchronize_session=False)
    user_items = db.query(models.Item).filter(models.Item.user_id == user_id).all()
    for item in user_items:
        linked_claims = db.query(models.Claim).filter(
            or_(
                models.Claim.lost_item_id == item.id,
                models.Claim.found_item_id == item.id,
            )
        ).all()
        if linked_claims:
            claim_ids = [claim.id for claim in linked_claims]
            db.query(models.ClaimDecisionReport).filter(
                models.ClaimDecisionReport.claim_id.in_(claim_ids)
            ).delete(synchronize_session=False)
            db.query(models.ClaimProof).filter(
                models.ClaimProof.claim_id.in_(claim_ids)
            ).delete(synchronize_session=False)
            db.query(models.Claim).filter(
                models.Claim.id.in_(claim_ids)
            ).delete(synchronize_session=False)
        store_item_as_reference(db, item, reason="user_deleted")
        db.delete(item)
    db.query(models.PendingItem).filter(models.PendingItem.user_id == user_id).delete(synchronize_session=False)
    db.delete(user)

# --- FIX 1: The Embedding Generator ---
def generate_embedding(image_path: str):
    from clip_test import get_clip_components 
    model, processor = get_clip_components()
    # Ensure we point to the STATIC folder where the file actually lives
    # If image_path is "uploads/file.jpg", this makes it "static/uploads/file.jpg"
    if not image_path.startswith("static/"):
        image_path = os.path.join("static", image_path)
    
    full_path = os.path.join(BASE_DIR, image_path) 

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"Image file not found at {full_path}")

    img = Image.open(full_path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt")

    with torch.no_grad():
        feat = model.get_image_features(**inputs)
        if hasattr(feat, "pooler_output"):
            feat = feat.pooler_output
        feat = feat / feat.norm(p=2, dim=-1, keepdim=True)

    # This returns a JSON STRING which matches your new models.py Column(String)
    return json.dumps(feat.cpu().numpy().flatten().tolist())


async def build_combined_upload_embedding(*uploads: UploadFile) -> str:
    images = []

    for upload in uploads:
        if not upload or not upload.filename:
            continue

        image_bytes = await upload.read()
        await upload.seek(0)
        if not image_bytes:
            continue

        try:
            images.append(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid uploaded image: {upload.filename}") from exc

    if not images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    return json.dumps(get_multi_image_embedding(images).tolist())
# Auto Archive
def auto_archive_pending(db: Session):
    cutoff = datetime.utcnow() - timedelta(days=3)
    db.query(models.PendingItem).filter(
        models.PendingItem.created_at < cutoff,
        models.PendingItem.archived == False
    ).update({"archived": True})
    db.commit()


@router.get("/my-permissions")
async def get_my_permissions(admin: models.User = Depends(get_current_admin)):
    # If permissions are stored as a JSON string in DB, decode them
    if isinstance(admin.permissions, str):
        return json.loads(admin.permissions)
    return admin.permissions # Return list directly if already a list

@router.post("/items/confirm-match/{lost_id}/{found_id}")
async def confirm_match(lost_id: int, found_id: int, db: Session = Depends(get_db)):
    lost_item = db.query(models.Item).filter(models.Item.id == lost_id).first()
    found_item = db.query(models.Item).filter(models.Item.id == found_id).first()

    if not lost_item or not found_item:
        raise HTTPException(status_code=404, detail="Items not found")

    # This is where the magic happens
    lost_item.is_matched = True
    found_item.is_matched = True

    db.commit()
    return {"message": "Items successfully matched!"}


@router.post("/items/analyze-matches")
async def analyze_item_matches(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    lost_items = db.query(models.Item).filter(
        models.Item.status == "lost",
        models.Item.archived == False,
        models.Item.is_matched == False,
        models.Item.image_embedding.isnot(None),
    ).all()

    found_items = db.query(models.Item).filter(
        models.Item.status == "found",
        models.Item.archived == False,
        models.Item.is_matched == False,
        models.Item.image_embedding.isnot(None),
    ).all()

    if not lost_items or not found_items:
        return {
            "message": "No available items to analyze.",
            "scanned_lost": len(lost_items),
            "scanned_found": len(found_items),
            "matched_count": 0,
            "matches": [],
        }

    match_threshold = 0.70
    matched_found_ids: set[int] = set()
    created_matches: list[dict] = []

    existing_pairs = {
        (claim.lost_item_id, claim.found_item_id)
        for claim in db.query(models.Claim).all()
        if claim.lost_item_id and claim.found_item_id
    }

    for lost_item in lost_items:
        best_found = None
        best_score = 0.0
        lost_category = (lost_item.category or "").strip().lower()

        for found_item in found_items:
            if found_item.id in matched_found_ids:
                continue

            found_category = (found_item.category or "").strip().lower()
            if lost_category and found_category and lost_category != found_category:
                continue

            score = compute_item_match_score(lost_item, found_item)
            if score is None:
                continue

            if score > best_score:
                best_score = score
                best_found = found_item

        if not best_found or best_score < match_threshold:
            continue

        lost_item.is_matched = True
        best_found.is_matched = True
        matched_found_ids.add(best_found.id)

        if (lost_item.id, best_found.id) not in existing_pairs:
            db.add(models.Claim(
                lost_item_id=lost_item.id,
                found_item_id=best_found.id,
                claimant_id=lost_item.user_id or current_admin.id,
                similarity_score=f"{best_score * 100:.1f}%",
                status="pending",
            ))
            existing_pairs.add((lost_item.id, best_found.id))

        created_matches.append({
            "lost_id": lost_item.id,
            "found_id": best_found.id,
            "score": best_score,
            "category": lost_item.category or best_found.category or "Unknown",
        })

    db.commit()

    if created_matches:
        create_admin_notification(
            db,
            f"Match analysis completed. {len(created_matches)} lost and found pairs were flagged for review.",
            "match",
            created_matches[0]["lost_id"],
            "/admin/Claim-Management"
        )

    return {
        "message": "Analysis completed.",
        "scanned_lost": len(lost_items),
        "scanned_found": len(found_items),
        "matched_count": len(created_matches),
        "matches": created_matches,
    }

@router.get("/items/found")
def get_found_items(db: Session = Depends(get_db)):
    items = db.query(models.Item).filter(
        models.Item.status == "found",
        models.Item.archived == False
    ).all()
    return items

@router.get("/items/found/archived")
def get_archived_found_items(db: Session = Depends(get_db)):
    items = db.query(models.Item).filter(
        models.Item.status == "found",
        models.Item.archived == True
    ).all()
    return items

@router.get("/items/lost")
def get_lost_items(db: Session = Depends(get_db)):
    items = db.query(models.Item).filter(
        models.Item.status == "lost",
        models.Item.archived == False
    ).all()
    return items

@router.get("/items/lost/archived")
def get_archived_lost_items(db: Session = Depends(get_db)):
    items = db.query(models.Item).filter(
        models.Item.status == "lost",
        models.Item.archived == True
    ).all()
    return items
@router.get("/dashboard")
def admin_dashboard(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    # REMOVED "admin": current_admin from the dictionary below
    return templates.TemplateResponse(
        "admin.20.html",
        {"request": request} 
    )

@router.get("/User-Management")
async def admin_user_management(
    request: Request,
    # This automatically handles the token/cookie and checks permissions
    admin = Depends(check_permission("User-Management"))
):
    return templates.TemplateResponse(
        "Admin Pages/User_Management.html",
        {"request": request, "admin": admin}
    )
@router.get("/Messages")
def admin_Messages( # Renamed this function
    request: Request,
    admin = Depends(check_permission("Messages"))
):
   
    return templates.TemplateResponse(
        "Admin Pages/Admin_Message.html",
        {"request": request, "admin": admin} 
    )

@router.get("/Lost_Items_Report")
def admin_lost_items_report( # Renamed this function
    request: Request,
    admin = Depends(check_permission("Lost-Reports"))
):

    
    return templates.TemplateResponse(
        "Admin Pages/Lost_item_Report.html",
        {"request": request, "admin": admin} 
    )

@router.get("/Found_Items_Report")
def admin_found_items_report( # Renamed this function
    request: Request,
    admin = Depends(check_permission("Found-Reports"))
):
    
    return templates.TemplateResponse(
        "Admin Pages/Found_item_Report.html",
         {"request": request, "admin": admin} 
    )

@router.get("/Claim-Management" )
def admin_claim_management( # Renamed this function
    request: Request,
    admin = Depends(check_permission("Claim-Management"))
):  
    
    return templates.TemplateResponse(
        "Admin Pages/Claim_Management.html",
        {"request": request, "admin": admin} 
    )
@router.get("/Reports")
def admin_reports(
    request: Request,
    admin = Depends(check_permission("Reports"))
):
    reports_page = os.path.join(BASE_DIR, "templates", "Admin Pages", "Reports.html")
    return FileResponse(reports_page)
@router.get("/Profile")
def admin_profile(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return templates.TemplateResponse(
        "Admin Pages/Admin_Profile.html",
        {"request": request}
    )

@router.post("/update-profile")
async def update_profile(
    full_name: str = Form(None),
    student_no: str = Form(None), # The missing number
    course: str = Form(None),
    section: str = Form(None),
    profile_img: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    user = current_user
    
    if not user:
        return {"error": "User not found"}

    # Handle Image Upload
    if profile_img and profile_img.filename:
        os.makedirs("static/profile_pics", exist_ok=True)
        file_extension = os.path.splitext(profile_img.filename)[1]
        file_path = f"static/profile_pics/user_{user.id}{file_extension}"
        
        with open(file_path, "wb") as buffer:
            buffer.write(await profile_img.read())
        
        user.profile_pic = file_path

    # Update Text Fields (Email remains read-only for security)
    if full_name: user.full_name = full_name
    if student_no: user.student_no = student_no
    if course: user.course = course
    if section: user.section = section

    db.commit()
    return {"message": "Profile updated successfully"}

@router.get("/Settings")
def admin_settings(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return templates.TemplateResponse(
        "Admin Pages/Setting.html",
        {"request": request}
    )
@router.get("/Confiscated-items")
def admin_confiscated_items(
    request: Request,
    admin = Depends(check_permission("Confiscated-items"))
):
   
    return templates.TemplateResponse(
        "Admin Pages/Confiscated_Item.html",
        {"request": request, "admin": admin} 
    )   

@router.get("/Content-management")
def admin_content_management(
    request: Request,
    admin = Depends(check_permission("Content-management"))
):
    
    return templates.TemplateResponse(
        "Admin Pages/Content_Management.html",
        {"request": request, "admin": admin} 
    )
@router.get("/Content-management/features")
def admin_content_management(
    request: Request,
    admin = Depends(check_permission("Content-management"))
):
    
    return templates.TemplateResponse(
        "Admin Pages/admin_cms_features.html",
        {"request": request, "admin": admin} 
    )
@router.get("/Content-management/about")
def admin_content_management(
    request: Request,
    admin = Depends(check_permission("Content-management"))
):
    
    return templates.TemplateResponse(
        "Admin Pages/admin_cms_about.html",
        {"request": request, "admin": admin} 
    )


@router.get("/Content-Editor")
async def content_editor_page(
    request: Request,
    admin = Depends(check_permission("Content-management"))
):
    # You can add logic here to fetch existing content from the DB 
    # to pre-fill the inputs if you want!
    return templates.TemplateResponse(
        "/Admin Pages/admin_cms.html",
        {"request": request, "admin": admin}
        )

@router.get("/pending-items")
def get_pending_items(
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    auto_archive_pending(db)

    items = db.query(models.PendingItem).filter(
        models.PendingItem.archived == False
    ).order_by(models.PendingItem.created_at.desc()).all()

    return items


@router.get("/pending-items/archived")
def get_archived_pending_items(
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    items = db.query(models.PendingItem).filter(
        models.PendingItem.archived == True
    ).order_by(models.PendingItem.created_at.desc()).all()

    return items

@router.get("/departments")
async def get_departments(db: Session = Depends(get_db)):
    # Fetches the list we inserted (Registrar, IT Dept, etc.)
    return db.query(models.Department).all()

@router.get("/category")
async def get_caregory(db: Session = Depends(get_db)):
    # Fetches the list we inserted (Registrar, IT Dept, etc.)
    return db.query(models.Category).all()


@router.post("/departments")
async def create_department(
    data: dict,
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("Content-management"))
):
    name = str(data.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Department name is required.")

    existing = db.query(models.Department).filter(models.Department.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Department already exists.")

    new_department = models.Department(name=name)
    db.add(new_department)
    db.commit()
    db.refresh(new_department)
    return {"status": "success", "department": new_department}


@router.delete("/departments/{department_id}")
async def delete_department(
    department_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("Content-management"))
):
    department = db.query(models.Department).filter(models.Department.id == department_id).first()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found.")

    db.delete(department)
    db.commit()
    return {"status": "success"}


@router.post("/categories")
async def create_category(
    data: dict,
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("Content-management"))
):
    name = str(data.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required.")

    existing = db.query(models.Category).filter(models.Category.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists.")

    new_category = models.Category(name=name)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return {"status": "success", "category": new_category}


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("Content-management"))
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")

    db.delete(category)
    db.commit()
    return {"status": "success"}


@router.post("/create-new-admin")
async def create_new_admin(
    admin_in: AdminCreate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Create"))
):
    requested_permissions = list(dict.fromkeys(admin_in.permissions))
    assignable_permissions = get_assignable_permissions(current_admin)
    invalid_permissions = [
        permission for permission in requested_permissions
        if permission not in assignable_permissions
    ]

    if invalid_permissions:
        raise HTTPException(
            status_code=403,
            detail=f"You cannot grant permissions you do not have: {', '.join(invalid_permissions)}"
        )

    if any(permission.startswith("User-Management-") for permission in requested_permissions):
        requested_permissions = list(dict.fromkeys(["User-Management", *requested_permissions]))

    existing = db.query(models.User).filter(
        models.User.email == admin_in.email
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Admin email already registered"
        )

    # Generate secure temporary password
    temp_password = secrets.token_urlsafe(8)

    new_admin = models.User(
        full_name=admin_in.full_name,
        email=admin_in.email,
        hashed_password=pwd_context.hash(temp_password),
        is_admin=True,
        permissions=json.dumps(requested_permissions),
        department=admin_in.department, # Saves to the new column
        section=admin_in.section,
        must_change_password=True
    )

    db.add(new_admin)
    db.commit()

    create_admin_notification(
        db,
        f"New admin account created for {admin_in.full_name}.",
        "user_management_admin",
        new_admin.id
    )

    return {
        "message": "Admin created successfully",
        "temp_password": temp_password
    }

@router.post("/update-permissions/{user_id}")
async def update_user_permissions(
    user_id: int, 
    data: PermissionUpdate, 
    db: Session = Depends(get_db),
    admin = Depends(check_permission("User-Management-Edit"))
):
    # 1. Find the user in the database
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    requested_permissions = list(dict.fromkeys(data.permissions))
    assignable_permissions = get_assignable_permissions(admin)
    invalid_permissions = [permission for permission in requested_permissions if permission not in assignable_permissions]

    if invalid_permissions:
        raise HTTPException(
            status_code=403,
            detail=f"You cannot grant permissions you do not have: {', '.join(invalid_permissions)}"
        )

    permissions = requested_permissions
    if any(permission.startswith("User-Management-") for permission in permissions):
        permissions = list(dict.fromkeys(["User-Management", *permissions]))

    if not user.is_admin and student_has_portal_access(user) and STUDENT_ACCESS_PERMISSION not in permissions:
        permissions.append(STUDENT_ACCESS_PERMISSION)

    # 2. Convert the list to a JSON string for SSMS storage
    # This matches the logic in your get-all-users route
    user.permissions = json.dumps(permissions)
    
    try:
        db.commit()
        db.refresh(user)
        is_active = bool(permissions) if user.is_admin else student_has_portal_access(user)
        return {"message": "Permissions updated successfully", "status": "Active" if is_active else "Deactivated"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/get-all-users")
async def get_all_users(
    db: Session = Depends(get_db),
    # Ensure the person calling this is actually an admin with the right perms
    admin = Depends(check_permission("User-Management")) 
):
    users = db.query(models.User).all()
    user_list = []
    
    for u in users:
        # 1. Handle permissions safely
        perms = parse_permissions(u.permissions)
        is_student_active = True if u.is_admin else student_has_portal_access(u)

        # 2. Append the formatted dictionary
        user_list.append({
            "id": u.id,
            "full_name": u.full_name or "N/A",
            "student_no": u.student_no or "N/A",
            "email": u.email,
            "batch_id": u.batch_id or "",
            "department": u.department or "N/A",
            "course": u.course or "",
            "section": u.section or "",
            "course_section": f"{u.course or ''} {u.section or ''}".strip() or "N/A",
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "is_admin": u.is_admin,
            "is_archived": u.is_archived,
            "is_student_active": is_student_active,
            "is_pending_delete": user_is_pending_delete(u),
            "permissions": perms
        })
        
    return user_list


@router.post("/activate-students")
async def activate_students(
    data: StudentActivationRequest,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Edit"))
):
    user_ids = list(dict.fromkeys(data.user_ids))
    if not user_ids:
        raise HTTPException(status_code=400, detail="No users selected for activation.")

    students: list[models.User] = []
    chunk_size = 1000
    for start in range(0, len(user_ids), chunk_size):
        user_id_chunk = user_ids[start:start + chunk_size]
        students.extend(
            db.query(models.User).filter(
                models.User.id.in_(user_id_chunk),
                models.User.is_admin == False,
                models.User.is_archived == False
            ).all()
        )

    if not students:
        raise HTTPException(status_code=404, detail="No eligible users found for activation.")

    activated_count = 0
    for student in students:
        permissions = parse_permissions(student.permissions)
        if STUDENT_ACCESS_PERMISSION not in permissions:
            permissions.append(STUDENT_ACCESS_PERMISSION)
            student.permissions = json.dumps(permissions)
            activated_count += 1

    db.commit()

    return {
        "message": f"{activated_count} user account(s) activated successfully.",
        "count": activated_count,
        "requested_count": len(user_ids)
    }


@router.post("/deactivate-students")
async def deactivate_students(
    data: StudentActivationRequest,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Edit"))
):
    user_ids = list(dict.fromkeys(data.user_ids))
    if not user_ids:
        raise HTTPException(status_code=400, detail="No users selected for deactivation.")

    students: list[models.User] = []
    chunk_size = 1000
    for start in range(0, len(user_ids), chunk_size):
        user_id_chunk = user_ids[start:start + chunk_size]
        students.extend(
            db.query(models.User).filter(
                models.User.id.in_(user_id_chunk),
                models.User.is_admin == False,
                models.User.is_archived == False
            ).all()
        )

    if not students:
        raise HTTPException(status_code=404, detail="No eligible users found for deactivation.")

    deactivated_count = 0
    for student in students:
        permissions = parse_permissions(student.permissions)
        if STUDENT_ACCESS_PERMISSION in permissions:
            permissions = [permission for permission in permissions if permission != STUDENT_ACCESS_PERMISSION]
            student.permissions = json.dumps(permissions)
            deactivated_count += 1

    db.commit()

    return {
        "message": f"{deactivated_count} user account(s) deactivated successfully.",
        "count": deactivated_count,
        "requested_count": len(user_ids)
    }


@router.post("/grant-admin-access/{user_id}")
async def grant_admin_access(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Edit"))
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_archived:
        raise HTTPException(status_code=400, detail="Archived accounts cannot be granted admin access.")

    if user.is_admin:
        raise HTTPException(status_code=400, detail="This account already has admin access.")

    if not user_is_faculty_account(user):
        raise HTTPException(status_code=400, detail="Only faculty accounts can be granted admin access.")

    current_permissions = [perm for perm in parse_permissions(user.permissions) if perm != STUDENT_ACCESS_PERMISSION]
    user.is_admin = True
    user.permissions = json.dumps(current_permissions)

    db.commit()
    db.refresh(user)

    create_admin_notification(
        db,
        f"{user.full_name or user.email} was granted admin access.",
        "user_management_admin",
        user.id
    )

    return {
        "message": f"{user.full_name or user.email} now has admin access.",
        "user_id": user.id
    }

@router.post("/archive-students-by-batch")
async def archive_students_by_batch(
    data: dict,
    db: Session = Depends(get_db),
    admin = Depends(check_permission("User-Management"))
):
    batch_id = str(data.get("batch_id", "")).strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="Batch ID is required")

    students = db.query(models.User).filter(
        models.User.is_admin == False,
        models.User.is_archived == False,
        models.User.batch_id == batch_id
    ).all()

    if not students:
        raise HTTPException(status_code=404, detail="No active students found for this batch")

    for student in students:
        student.is_archived = True

    db.commit()

    return {
        "message": f"{len(students)} student account(s) from batch {batch_id} archived successfully.",
        "count": len(students),
        "batch_id": batch_id
    }

@router.post("/restore-students-by-batch")
async def restore_students_by_batch(
    data: dict,
    db: Session = Depends(get_db),
    admin = Depends(check_permission("User-Management"))
):
    batch_id = str(data.get("batch_id", "")).strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="Batch ID is required")

    students = db.query(models.User).filter(
        models.User.is_admin == False,
        models.User.is_archived == True,
        models.User.batch_id == batch_id
    ).all()

    if not students:
        raise HTTPException(status_code=404, detail="No archived students found for this batch")

    for student in students:
        student.is_archived = False

    db.commit()

    return {
        "message": f"{len(students)} student account(s) from batch {batch_id} restored successfully.",
        "count": len(students),
        "batch_id": batch_id
    }

@router.delete("/delete-students-by-batch")
async def delete_students_by_batch(
    data: dict,
    db: Session = Depends(get_db),
    admin = Depends(check_permission("User-Management"))
):
    batch_id = str(data.get("batch_id", "")).strip()
    if not batch_id:
        raise HTTPException(status_code=400, detail="Batch ID is required")

    students = db.query(models.User).filter(
        models.User.is_admin == False,
        models.User.is_archived == True,
        models.User.batch_id == batch_id
    ).all()

    if not students:
        raise HTTPException(status_code=404, detail="No archived students found for this batch")

    try:
        count = len(students)
        for student in students:
            delete_user_and_related_records(db, student)
        db.commit()
        return {
            "message": f"{count} archived student account(s) from batch {batch_id} deleted successfully.",
            "count": count,
            "batch_id": batch_id
        }
    except Exception as e:
        db.rollback()
        print(f"Batch Delete Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete archived students for this batch")

@router.post("/bulk-register-students")
async def bulk_register(
    data: dict,
    current_admin: models.User = Depends(check_permission("User-Management-Create"))
):
    students_list = data.get("students", []) or data.get("users", [])
    duplicate_action = str(data.get("duplicate_action", "ignore")).strip().lower()
    if duplicate_action not in {"ignore", "replace"}:
        duplicate_action = "ignore"

    if not isinstance(students_list, list) or len(students_list) == 0:
        raise HTTPException(status_code=400, detail="No users were provided for registration.")

    job_id = uuid.uuid4().hex
    with BULK_JOB_LOCK:
        BULK_REGISTRATION_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "finished_at": None,
            "progress": 0,
            "processed": 0,
            "total": len(students_list),
            "summary": {
                "total": len(students_list),
                "created": 0,
                "replaced": 0,
                "ignored": 0,
                "duplicate_action": duplicate_action
            },
            "results": [],
            "message": "Bulk registration request accepted.",
            "requested_by": current_admin.id
        }

    worker = threading.Thread(
        target=process_bulk_registration_job,
        args=(job_id, students_list, duplicate_action),
        daemon=True
    )
    worker.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Bulk registration started in the background."
    }


@router.get("/bulk-register-students/status/{job_id}")
async def get_bulk_register_status(
    job_id: str,
    current_admin: models.User = Depends(check_permission("User-Management-Create"))
):
    with BULK_JOB_LOCK:
        job = BULK_REGISTRATION_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Bulk registration job not found.")

        try:
            current_permissions = json.loads(current_admin.permissions) if isinstance(current_admin.permissions, str) else (current_admin.permissions or [])
        except Exception:
            current_permissions = []

        if job.get("requested_by") != current_admin.id and "User-Management" not in current_permissions:
            raise HTTPException(status_code=403, detail="You do not have access to this bulk registration job.")

        return job
# Approve Item
# --- FIX 2: The Approval Logic ---
@router.post("/approve-item/{item_id}")
async def approve_item(item_id: int, db: Session = Depends(get_db)):
    # 1. Find the pending item
    pending = db.query(models.PendingItem).filter(models.PendingItem.id == item_id).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Item not found")

    # 2. Move to main Items table
    # We carry over the 'matched_item_id' logic here
    new_item = models.Item(
        status="found",
        category=pending.category,
        description=pending.description,
        location=pending.location,
        date=pending.date,
        image_path=pending.image_path,
        image_embedding=pending.image_embedding,
        brand=pending.brand,
        color=pending.color,
        time_found=pending.time_found,
        user_id=pending.user_id,
        is_matched=False,
        is_surrendered=True,
        archived=False,
        approved_at=datetime.utcnow()
    )

    db.add(new_item)

    # 3. Remove from pending
    db.delete(pending)
    db.commit()

    return {"status": "success", "message": "Item approved and moved to inventory"}



@router.post("/archive-pending/{pending_id}")
def archive_pending(
    pending_id: int,
    db: Session = Depends(get_db),
    admin: str = Depends(get_current_admin)
):
    pending = db.query(models.PendingItem).filter(models.PendingItem.id == pending_id).first()
    if not pending:
        raise HTTPException(404, "Pending item not found")

    pending.archived = True # Just hide it
    db.commit()
    return {"message": "Item archived"}


@router.delete("/pending-items/{pending_id}/dispose")
def dispose_pending_item(
    pending_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    pending = db.query(models.PendingItem).filter(models.PendingItem.id == pending_id).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending item not found")

    try:
        reference_item = models.ReferenceItem(
            source_item_id=None,
            category_id=None,
            status="found",
            category=pending.category,
            department=None,
            description=pending.description,
            image_path=pending.image_path,
            image_embedding=pending.image_embedding,
            brand=pending.brand,
            color=pending.color,
            location=pending.location,
            date=pending.date,
            time_found=pending.time_found,
            user_id=pending.user_id,
            archived=True,
            is_surrendered=True,
            deleted_reason="disposed_pending",
            created_at=pending.created_at,
            deleted_at=datetime.utcnow(),
        )
        db.add(reference_item)
        db.delete(pending)
        db.commit()
        return {"status": "success", "message": "Pending item disposed"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not dispose pending item")

@router.post("/archive-found/{item_id}")
def archive_found_item(
    item_id: int, 
    db: Session = Depends(get_db), 
    admin: str = Depends(get_current_admin)
):
    # 1. Search in the Items table
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # 2. FIX: Change 'is_archived' to 'archived' to match your models.py
    item.archived = True 
    db.commit()

    return {"status": "success", "message": "Item moved to archives"}


@router.post("/recover-pending/{pending_id}")
def recover_pending(
    pending_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    pending = db.query(models.PendingItem).filter(models.PendingItem.id == pending_id).first()
    if pending:
        pending.archived = False
        db.commit()
        return {"status": "success", "message": "Pending item restored to approval queue", "record_type": "pending"}

    # Fallback: if the UI thought this was pending but the archived record already lives
    # in the main found-items table, recover that item instead of hard-failing.
    item = db.query(models.Item).filter(models.Item.id == pending_id).first()
    if item:
        item.archived = False
        db.commit()
        return {"status": "success", "message": "Archived found item restored to active inventory", "record_type": "found"}

    raise HTTPException(status_code=404, detail="Pending item not found")


@router.post("/recover-found/{item_id}")
def recover_found_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.archived = False
    db.commit()
    return {"status": "success", "message": "Item restored to active inventory"}

@router.post("/reset-student-password")
async def reset_student_password(
    data: dict, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(check_permission("User-Management-Reset"))
):
    email = data.get("email")
    student = db.query(models.User).filter(models.User.email == email).first()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # 1. Generate a new temporary password
    new_temp = "STI-" + str(uuid.uuid4())[:8] 
    
    # 2. Hash the new password using bcrypt for security
    student.hashed_password = pwd_context.hash(new_temp)
    
    # 3. FORCE PASSWORD CHANGE: Set flag back to True (1)
    student.must_change_password = True 
    
    db.commit()
    
    return {
        "status": "success",
        "new_temp_password": new_temp
    }
import os
import shutil
from datetime import datetime
from fastapi import FastAPI, APIRouter, UploadFile, File, Form, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

app = FastAPI()

# --- CRITICAL: This allows the browser to access the 'static' folder ---
# If your images are in static/uploads, the URL will be /static/uploads/filename.jpg
app.mount("/static", StaticFiles(directory="static"), name="static")

UPLOAD_DIR = "static/uploads"

@router.post("/items/lost")
async def finalize_lost_upload(
    file: UploadFile = File(...),
    extra_image_1: UploadFile = File(None),
    extra_image_2: UploadFile = File(None),
    item_name: str = Form(...),
    category_id: int = Form(...), # Match!
    category: str = Form(...),    # Match!
    department: str = Form(...),  #
    brand: str = Form(None),
    color: str = Form(None),
    description: str = Form(None),
    location: str = Form(...),
    date: str = Form(None),
    time_found: str = Form(None),
    image_embedding: str = Form(None), 
    ai_score: float = Form(0.0),       
    matched_item_id: int = Form(None), 
    db: Session = Depends(get_db),
    # 1. Add this dependency to get the logged-in user's info
    current_user: models.User = Depends(get_current_user) 
):
    # 2. Save the file
    try:
        resolved_category = resolve_category_name(db, category_id=category_id, category_name=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    normalized_image_embedding = await build_combined_upload_embedding(file, extra_image_1, extra_image_2)
    saved_path = save_file(file, resolved_category)

    # 3. Date Parsing
    parsed_date = None
    if date and date.strip():
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            parsed_date = None

    # 4. Determine Automatic Match Status
    is_auto_match = ai_score >= 0.55 and matched_item_id is not None

    # 5. Create the Database Record 
    new_item = models.Item(
        status="lost",
        category_id=category_id,
        category=category,
        department=department,
        user_id=current_user.id,  # <--- SETS THE UPLOADER RECORD
        description=f"[{item_name}] {description}" if description else item_name,
        brand=brand,
        color=color,
        location=location,
        image_path=saved_path, 
        image_embedding=normalized_image_embedding, 
        date=parsed_date,
        time_found=time_found,
        is_matched=is_auto_match, 
        archived=False,
        is_surrendered=True,      
        created_at=datetime.utcnow()
    )

    try:
        db.add(new_item)
        db.flush()
        
        # 6. Handle the "Other Side" of the match
        if is_auto_match:
            found_item = db.query(models.Item).filter(models.Item.id == matched_item_id).first()
            if found_item and found_item.status == "found" and not found_item.archived:
                new_item.is_matched = True
                found_item.is_matched = True
                ensure_pending_claim_for_pair(
                    db,
                    lost_item=new_item,
                    found_item=found_item,
                    claimant_id=new_item.user_id or found_item.user_id or current_user.id,
                    similarity_score=f"{ai_score * 100:.1f}%"
                )

        db.commit()
        db.refresh(new_item)

        # 7. Notification
        notify_admin(
            db,
            f"Admin {current_user.full_name} reported: {item_name}",
            related_id=new_item.id,
            target_url="/admin/Lost_Items_Report"
        )

        return {
            "status": "success", 
            "item_id": new_item.id,
            "uploader": current_user.full_name,
            "auto_matched": is_auto_match
        }
        
    except Exception as e:
        db.rollback()
        print(f"Database Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.post("/items/founds")
async def finalize_found_upload(
    file: UploadFile = File(...),
    extra_image_1: UploadFile = File(None),
    extra_image_2: UploadFile = File(None),
    item_name: str = Form(...),
    category_id: int = Form(...), # Match!
    category: str = Form(...),    # Match!
    department: str = Form(...),  #
    brand: str = Form(None),
    color: str = Form(None),
    description: str = Form(None),
    location: str = Form(...),
    date: str = Form(None),
    time_found: str = Form(None),
    image_embedding: str = Form(None), 
    ai_score: float = Form(0.0),       
    matched_item_id: int = Form(None), 
    db: Session = Depends(get_db),
    # 1. Add this dependency to get the logged-in user's info
    current_user: models.User = Depends(get_current_user) 
):
    # 2. Save the file
    try:
        resolved_category = resolve_category_name(db, category_id=category_id, category_name=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    normalized_image_embedding = await build_combined_upload_embedding(file, extra_image_1, extra_image_2)
    saved_path = save_file(file, resolved_category)

    # 2. Handle Date Parsing safely (prevents crash if date is empty)
    parsed_date = None
    if date and date.strip():
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            parsed_date = None

    # 4. Determine Automatic Match Status
    is_auto_match = ai_score >= 0.55 and matched_item_id is not None

    # 5. Create the Database Record 
    new_item = models.Item(
        status="found",
        category_id=category_id,
        category=category,
        department=department,
        user_id=current_user.id,  # <--- SETS THE UPLOADER RECORD
        description=f"[{item_name}] {description}" if description else item_name,
        brand=brand,
        color=color,
        location=location,
        image_path=saved_path, 
        image_embedding=normalized_image_embedding, 
        date=parsed_date,
        time_found=time_found,
        is_matched=is_auto_match, 
        archived=False,
        is_surrendered=False,      
        created_at=datetime.utcnow()
    )

    try:
        db.add(new_item)
        db.flush()
        
        # 6. Handle the "Other Side" of the match
        if is_auto_match:
            lost_item = db.query(models.Item).filter(models.Item.id == matched_item_id).first()
            if lost_item and lost_item.status == "lost" and not lost_item.archived:
                new_item.is_matched = True
                lost_item.is_matched = True
                ensure_pending_claim_for_pair(
                    db,
                    lost_item=lost_item,
                    found_item=new_item,
                    claimant_id=lost_item.user_id or new_item.user_id or current_user.id,
                    similarity_score=f"{ai_score * 100:.1f}%"
                )

        db.commit()
        db.refresh(new_item)

        # 7. Notification
        notify_admin(
            db,
            f"Admin {current_user.full_name} reported: {item_name}",
            related_id=new_item.id,
            target_url="/admin/Found_Items_Report"
        )

        return {
            "status": "success", 
            "item_id": new_item.id,
            "uploader": current_user.full_name,
            "auto_matched": is_auto_match
        }
        
    except Exception as e:
        db.rollback()
        print(f"Database Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/items/{item_id}/archive")
async def archive_item(
    item_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1. Find the item
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # 2. Update the status
    item.archived = True
    
    try:
        db.commit()
        # Optional: Log who archived it
        print(f"Admin {current_user.full_name} archived item {item_id}")
        return {"status": "success", "message": "Item moved to archive"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not archive item")

@router.delete("/items/{item_id}/dispose")
async def dispose_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        linked_claims = db.query(models.Claim).filter(
            or_(
                models.Claim.lost_item_id == item_id,
                models.Claim.found_item_id == item_id,
            )
        ).all()

        if linked_claims:
            claim_ids = [claim.id for claim in linked_claims]
            db.query(models.ClaimDecisionReport).filter(
                models.ClaimDecisionReport.claim_id.in_(claim_ids)
            ).delete(synchronize_session=False)
            db.query(models.ClaimProof).filter(
                models.ClaimProof.claim_id.in_(claim_ids)
            ).delete(synchronize_session=False)
            db.query(models.Claim).filter(
                models.Claim.id.in_(claim_ids)
            ).delete(synchronize_session=False)

        store_item_as_reference(db, item, reason="disposed")
        db.delete(item)
        db.commit()

        print(f"Admin {current_user.full_name} disposed item {item_id}")
        return {"status": "success", "message": "Item moved to hidden reference dataset and removed from live inventory"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not dispose item")

@router.get("/dashboard-stats")
async def get_stats(admin_email: str = Depends(get_current_admin)):
    return {"welcome": f"Hello {admin_email}", "total_items": 150}

# --- 8. AI & UPLOAD ROUTES ---
def calculate_similarity(vec1_json, vec2_json):
    if not vec1_json or not vec2_json:
        return 0.0
    v1 = np.array(json.loads(vec1_json))
    v2 = np.array(json.loads(vec2_json))
    return np.dot(v1, v2)

@router.get("/notifications")
def get_notifications(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    # Fetch latest 10 unread notifications, newest first
    notifications = db.query(models.Notification)\
        .order_by(models.Notification.created_at.desc())\
        .limit(10)\
        .all()
    
    return notifications

@router.post("/notifications/{notif_id}/read")
def mark_read(
    notif_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    notif = db.query(models.Notification).filter(models.Notification.id == notif_id).first()
    if notif:
        notif.is_read = True
        db.commit()
    return {"status": "success"}

@router.post("/update-settings")
async def update_settings(
    data: SettingsUpdate,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    user = db.query(models.User).filter(models.User.id == current_admin.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Admin not found")

    user.two_factor_enabled = bool(data.two_factor)
    user.push_notifications = bool(data.notifications)
    user.theme_mode = (data.theme or "light")[:20]
    user.font_size = max(12, min(24, int(data.font_size)))

    db.commit()
    return {"status": "success", "message": "Settings applied across system"}


@router.post("/create-announcement")
async def create_announcement(
    title: str = Form(...),
    content: str = Form(...),
    file: UploadFile = File(...), # Changed from 'image' to 'file'
    db: Session = Depends(get_db)
):
    # Keep a single active announcement by replacing the current record.
    upload_dir = Path("static/images")
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{Path(file.filename).name}"
    file_location = upload_dir / safe_name

    with file_location.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    db_path = f"static/images/{safe_name}"
    existing_posts = db.query(models.Announcement).order_by(models.Announcement.created_at.desc()).all()
    current_post = existing_posts[0] if existing_posts else None

    if current_post:
        old_path = current_post.image_url or ""
        current_post.title = title
        current_post.content = content
        current_post.image_url = db_path
        current_post.created_at = datetime.utcnow()

        if old_path.startswith("static/images/") and old_path != db_path:
            old_file = Path(old_path)
            if old_file.exists():
                old_file.unlink(missing_ok=True)

        for stale_post in existing_posts[1:]:
            stale_path = stale_post.image_url or ""
            if stale_path.startswith("static/images/"):
                stale_file = Path(stale_path)
                if stale_file.exists():
                    stale_file.unlink(missing_ok=True)
            db.delete(stale_post)
        message = "Announcement replaced"
    else:
        new_post = models.Announcement(
            title=title,
            content=content,
            image_url=db_path,
            created_at=datetime.utcnow()
        )
        db.add(new_post)
        message = "Announcement published"

    db.commit()
    
    return {"message": message, "path": db_path}
@router.post("/report-confiscated")
async def report_confiscated(
    category: str = Form(...),
    brand: str = Form(None),
    description: str = Form(...),
    color: str = Form(None),
    date_confiscated: str = Form(None),
    estimated_time: str = Form(None),
    location: str = Form(...),
    reason: str = Form(...),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    parsed_date_confiscated = None
    if date_confiscated:
        try:
            parsed_date_confiscated = datetime.strptime(date_confiscated, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Please choose a valid confiscated date.")

    # 1. Handle Image Upload
    file_path = None
    if image:
        upload_dir = "static/uploads/confiscated"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, image.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        file_path = file_path.replace("\\", "/")

    # 2. Save to Database
    new_item = models.ConfiscatedItem(
        category=category,
        brand=brand,
        description=description,
        color=color,
        date_confiscated=parsed_date_confiscated,
        location=location,
        estimated_time=estimated_time,
        reason=reason,
        image_path=file_path
    )
    
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    
    return {"message": "Success", "id": new_item.id}

@router.get("/get-confiscated-items")
async def get_confiscated_items(db: Session = Depends(get_db)):
    items = db.query(models.ConfiscatedItem).order_by(models.ConfiscatedItem.created_at.desc()).all()
    return items


@router.get("/get-confiscated-item/{item_id}")
async def get_confiscated_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(models.ConfiscatedItem).filter(models.ConfiscatedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Confiscated item not found")
    return item


@router.put("/update-confiscated/{item_id}")
async def update_confiscated_item(
    item_id: int,
    category: str = Form(...),
    brand: str = Form(None),
    description: str = Form(...),
    color: str = Form(None),
    date_confiscated: str = Form(None),
    estimated_time: str = Form(None),
    location: str = Form(...),
    reason: str = Form(...),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    item = db.query(models.ConfiscatedItem).filter(models.ConfiscatedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Confiscated item not found")

    parsed_date_confiscated = None
    if date_confiscated:
        try:
            parsed_date_confiscated = datetime.strptime(date_confiscated, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Please choose a valid confiscated date.")

    if image and image.filename:
        upload_dir = "static/uploads/confiscated"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, image.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        item.image_path = file_path.replace("\\", "/")

    item.category = category
    item.brand = brand
    item.description = description
    item.color = color
    item.date_confiscated = parsed_date_confiscated
    item.estimated_time = estimated_time
    item.location = location
    item.reason = reason

    db.commit()
    db.refresh(item)
    return {"message": "Confiscated item updated", "item": item}


@router.delete("/delete-confiscated/{item_id}")
async def delete_confiscated_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(models.ConfiscatedItem).filter(models.ConfiscatedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Confiscated item not found")

    db.delete(item)
    db.commit()
    return {"message": "Confiscated item deleted"}
