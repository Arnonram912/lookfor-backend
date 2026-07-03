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
from PIL import Image
import json
from sqlalchemy.exc import IntegrityError
from models import SettingsUpdate
from security import get_current_user
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from utils import (
    public_file_url,
    save_file,
    resolve_category_name,
    validate_upload_file_size,
    format_user_display_name,
    format_item_code,
    item_display_id,
    item_display_code,
)
from sqlalchemy import or_
from concurrent.futures import ThreadPoolExecutor


class AdminCreate(BaseModel):
    student_no: str
    full_name: Optional[str] = None
    last_name: str
    first_name: str
    middle_name: Optional[str] = ""
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


class AcademicTermScheduleUpdate(BaseModel):
    current_academic_year: str
    current_semester: str
    current_start_date: date
    current_end_date: date
    next_academic_year: str
    next_semester: str
    next_start_date: date
    next_end_date: date


class AcademicTermReactivateRequest(BaseModel):
    new_end_date: date
templates = Jinja2Templates(directory="templates")
# Change your directory definition
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_PROFILE_PICS_DIR = os.path.join(STATIC_DIR, "profile_pics")
DEFAULT_PROFILE_PIC = "static/photos/default-student-avatar.jpg"
# Unified path: everything goes into static/uploads
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")

router = APIRouter(prefix="/admin", tags=["Admin"])

BULK_REGISTRATION_JOBS: dict[str, dict] = {}
BULK_JOB_LOCK = threading.Lock()
ROOT_ADMIN_EMAIL = "admin@novaliches.sti.edu.ph"
ADMIN_PERMISSION_KEYS = [
    "Messages",
    "User-Management",
    "User-Management-Create",
    "User-Management-Edit",
    "User-Management-Reset",
    "User-Management-Archive",
    "User-Management-Delete",
    "Lost-Reports",
    "Found-Reports",
    "Claim-Management",
    "Reports",
    "Confiscated-items",
    "Content-management",
]
STUDENT_ACCESS_PERMISSION = "Student-Portal-Access"
DELETE_QUEUE_PERMISSION = "__PENDING_DELETE__"

class PermissionUpdate(BaseModel):
    permissions: list[str]


class StudentActivationRequest(BaseModel):
    user_ids: list[int]


class UserBatchActionResult(BaseModel):
    message: str
    count: int
    requested_count: int


def user_is_faculty_account(user: models.User) -> bool:
    if not user or user.is_admin:
        return False
    department = str(user.department or "").strip()
    course = str(user.course or "").strip()
    section = str(user.section or "").strip()
    return bool(department and department != "N/A" and not course and not section)


def deployed_static_path(path: str | None, fallback: str = DEFAULT_PROFILE_PIC) -> str:
    raw_path = str(path or "").strip().split("?", 1)[0]
    if not raw_path:
        return fallback

    if raw_path.startswith(("http://", "https://", "//")):
        return raw_path

    normalized_path = raw_path.lstrip("/").replace("\\", "/")
    if not normalized_path.startswith("static/"):
        return raw_path

    physical_path = os.path.abspath(os.path.join(BASE_DIR, *normalized_path.split("/")))
    static_root = os.path.abspath(STATIC_DIR)
    if os.path.commonpath([static_root, physical_path]) != static_root:
        return fallback

    if os.path.isfile(physical_path) and os.path.getsize(physical_path) > 0:
        return public_file_url(normalized_path)

    return public_file_url(fallback)


def parse_permissions(raw_permissions) -> list[str]:
    try:
        if isinstance(raw_permissions, str):
            return json.loads(raw_permissions)
        return raw_permissions or []
    except Exception:
        return []


def is_root_admin(user: models.User | None) -> bool:
    return bool(
        user
        and user.is_admin
        and str(user.email or "").strip().lower() == ROOT_ADMIN_EMAIL
    )


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


def normalize_saved_possible_matches(raw_possible_matches: str | None) -> str | None:
    if not raw_possible_matches:
        return None

    try:
        parsed_matches = json.loads(raw_possible_matches)
    except Exception:
        return None

    if not isinstance(parsed_matches, list):
        return None

    cleaned_matches = []
    for match in parsed_matches[:3]:
        if not isinstance(match, dict):
            continue
        cleaned_matches.append({
            "id": match.get("id"),
            "score": match.get("score"),
            "category": match.get("category"),
            "location": match.get("location"),
            "image_path": public_file_url(match.get("image_path")),
            "brand": match.get("brand"),
            "color": match.get("color"),
            "description": match.get("description"),
            "source": match.get("source", "found"),
            "cross_category": bool(match.get("cross_category")),
            "warning": match.get("warning"),
        })

    return json.dumps(cleaned_matches) if cleaned_matches else None


def serialize_found_item_match(
    found_item: models.Item,
    score: float | None = None,
    previous_pending_id: int | None = None
) -> dict:
    return {
        "id": found_item.id,
        "score": round(float(score or 0), 4),
        "category": found_item.category,
        "location": found_item.location,
        "image_path": public_file_url(found_item.image_path),
        "brand": found_item.brand,
        "color": found_item.color,
        "description": found_item.description,
        "source": "found",
        "previous_pending_id": previous_pending_id,
    }


def item_has_approved_claim(db: Session, item: models.Item) -> bool:
    if not item:
        return False

    filters = [models.Claim.status == "approved"]
    if item.status == "lost":
        filters.append(models.Claim.lost_item_id == item.id)
    elif item.status == "found":
        filters.append(models.Claim.found_item_id == item.id)
    else:
        return False

    return bool(db.query(models.Claim.id).filter(*filters).first())


def serialize_inventory_item(db: Session, item: models.Item) -> dict:
    report_item_id = item_display_id(item)
    report_item_code = item_display_code(item)
    entered_by_name = format_user_display_name(item.owner, "Unknown User")
    reported_person_name = str(getattr(item, "report_owner_name", "") or "").strip()
    reported_person_group = str(getattr(item, "report_owner_group", "") or "").strip()
    uploader_name = reported_person_name or entered_by_name

    return {
        "id": item.id,
        "item_id": report_item_id,
        "item_code": report_item_code,
        "lost_id": report_item_code if item.status == "lost" else None,
        "found_id": report_item_code if item.status == "found" else None,
        "status": item.status,
        "category_id": item.category_id,
        "category": item.category,
        "department": item.department,
        "description": item.description,
        "image_path": public_file_url(item.image_path),
        "possible_matches": normalize_saved_possible_matches(item.possible_matches),
        "is_matched": item.is_matched,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "is_surrendered": item.is_surrendered,
        "brand": item.brand,
        "color": item.color,
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
        "archived": item.archived,
        "deleted": bool(getattr(item, "deleted", False)),
        "location": item.location,
        "date": item.date.isoformat() if item.date else None,
        "time_found": item.time_found,
        "user_id": item.user_id,
        "uploader_name": uploader_name,
        "entered_by_name": entered_by_name,
        "report_owner_user_id": getattr(item, "report_owner_user_id", None),
        "report_owner_name": reported_person_name,
        "report_owner_group": reported_person_group,
        "is_claimed": item_has_approved_claim(db, item),
    }


def serialize_pending_item(db: Session, item: models.PendingItem) -> dict:
    submitter = item.submitter
    pending_code = format_item_code("pending_found", item.id)
    return {
        "id": item.id,
        "item_id": item.id,
        "item_code": pending_code,
        "found_id": pending_code,
        "status": "pending_found",
        "category": item.category,
        "item_name": item.item_name,
        "description": item.description,
        "location": item.location,
        "date": item.date.isoformat() if item.date else None,
        "time_found": item.time_found,
        "image_path": public_file_url(item.image_path),
        "image_embedding": item.image_embedding,
        "brand": item.brand,
        "color": item.color,
        "matched_item_id": item.matched_item_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "archived": item.archived,
        "deleted": bool(getattr(item, "deleted", False)),
        "user_id": item.user_id,
        "uploader_name": format_user_display_name(
            submitter,
            "Unknown User"
        ),
    }


def prepend_lost_possible_match(lost_item: models.Item, match_payload: dict) -> None:
    existing_matches = []
    if lost_item.possible_matches:
        try:
            parsed = json.loads(lost_item.possible_matches)
            existing_matches = parsed if isinstance(parsed, list) else []
        except Exception:
            existing_matches = []

    match_id = match_payload.get("id")
    match_source = match_payload.get("source")
    previous_pending_id = match_payload.get("previous_pending_id")
    deduped_matches = [
        match for match in existing_matches
        if not (
            isinstance(match, dict)
            and (
                (
                    match.get("id") == match_id
                    and match.get("source", "found") == match_source
                )
                or (
                    previous_pending_id
                    and match.get("id") == previous_pending_id
                    and match.get("source") == "pending_found"
                )
            )
        )
    ]
    lost_item.possible_matches = json.dumps([match_payload, *deduped_matches][:3])


def create_student_notification(
    db: Session,
    user_id: int,
    message: str,
    notif_type: str = "student_match",
    target_url: str | None = None
):
    if target_url is None:
        target_url = "/student/Lost-report"

    notif = models.Notification(
        message=message,
        type=notif_type,
        related_id=user_id,
        target_url=target_url,
        is_read=False,
        created_at=datetime.utcnow()
    )
    db.add(notif)
    return notif


def student_has_portal_access(user: models.User) -> bool:
    return STUDENT_ACCESS_PERMISSION in parse_permissions(user.permissions)


def user_is_pending_delete(user: models.User) -> bool:
    return DELETE_QUEUE_PERMISSION in parse_permissions(user.permissions)


def get_assignable_permissions(admin: models.User) -> set[str]:
    if is_root_admin(admin):
        return set(ADMIN_PERMISSION_KEYS)

    permissions = set(parse_permissions(admin.permissions))
    permissions.discard(STUDENT_ACCESS_PERMISSION)
    permissions.discard(DELETE_QUEUE_PERMISSION)
    return permissions


def notify_admin(
    db: Session,
    message: str,
    notif_type: str = "new_report",
    related_id: int = None,
    target_url: str | None = None,
    created_by_admin_id: int | None = None
):
    new_notif = models.Notification(
        message=message,
        type=notif_type,
        related_id=related_id,
        created_by_admin_id=created_by_admin_id,
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
        if is_root_admin(admin):
            return admin

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
    target_url: str | None = None,
    created_by_admin_id: int | None = None
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
        created_by_admin_id=created_by_admin_id,
        target_url=target_url,
        is_read=False,         # Ensure it starts as unread
        created_at=datetime.utcnow() # Add the time it happened
    )
    db.add(notif)
    db.commit()
    db.refresh(notif) # This allows you to access the new notif.id immediately
    return notif


def get_default_semester_dates(academic_year: str, semester: str) -> tuple[date, date]:
    try:
        start_year_text, end_year_text = academic_year.split("-", 1)
        start_year = int(start_year_text)
        end_year = int(end_year_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Academic year must use the format YYYY-YYYY.") from exc

    if end_year != start_year + 1:
        raise ValueError("Academic year must contain two consecutive years.")
    if semester == "1st Semester":
        return date(start_year, 7, 28), date(start_year, 12, 5)
    if semester == "2nd Semester":
        return date(end_year, 1, 5), date(end_year, 6, 5)
    raise ValueError("Invalid semester.")


def get_following_semester(academic_year: str, semester: str) -> tuple[str, str, date, date]:
    if semester == "1st Semester":
        next_year = academic_year
        next_semester = "2nd Semester"
    else:
        start_year = int(academic_year.split("-", 1)[0]) + 1
        next_year = f"{start_year}-{start_year + 1}"
        next_semester = "1st Semester"
    start_date, end_date = get_default_semester_dates(next_year, next_semester)
    return next_year, next_semester, start_date, end_date


def get_or_create_academic_term_setting(db: Session) -> models.AcademicTermSetting:
    setting = db.query(models.AcademicTermSetting).filter(models.AcademicTermSetting.id == 1).first()
    if setting:
        return setting

    setting = models.AcademicTermSetting(
        id=1,
        current_academic_year="2025-2026",
        current_semester="2nd Semester",
        current_start_date=date(2026, 1, 5),
        current_end_date=date(2026, 6, 5),
        current_status="active",
        next_academic_year="2026-2027",
        next_semester="1st Semester",
        next_start_date=date(2026, 7, 28),
        next_end_date=date(2026, 12, 5),
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def serialize_academic_term_setting(setting: models.AcademicTermSetting) -> dict:
    return {
        "current_academic_year": setting.current_academic_year,
        "current_semester": setting.current_semester,
        "current_start_date": setting.current_start_date.isoformat() if setting.current_start_date else None,
        "current_end_date": setting.current_end_date.isoformat() if setting.current_end_date else None,
        "current_status": setting.current_status,
        "next_academic_year": setting.next_academic_year,
        "next_semester": setting.next_semester,
        "next_start_date": setting.next_start_date.isoformat() if setting.next_start_date else None,
        "next_end_date": setting.next_end_date.isoformat() if setting.next_end_date else None,
        "can_reactivate": setting.current_status == "ended",
    }


def end_current_academic_term(
    db: Session,
    setting: models.AcademicTermSetting,
    ended_by_admin_id: int | None = None,
) -> int:
    if setting.current_status == "ended":
        return 0

    candidates = db.query(models.User).filter(
        models.User.is_admin == False,
        models.User.is_archived == False,
        models.User.batch_id.like(f"BATCH-{setting.current_academic_year} %"),
    ).all()
    students = [user for user in candidates if not user_is_faculty_account(user)]
    transition = models.AcademicTermTransition(
        academic_year=setting.current_academic_year,
        semester=setting.current_semester,
        archived_user_ids=json.dumps([user.id for user in students]),
        ended_by_admin_id=ended_by_admin_id,
    )
    db.add(transition)
    for student in students:
        student.is_archived = True
    setting.current_status = "ended"
    db.commit()

    create_admin_notification(
        db,
        f"{setting.current_academic_year} {setting.current_semester} ended. "
        f"{len(students)} student account(s) were archived.",
        "academic_term",
        setting.id,
        "/admin/User-Management?tab=archive",
    )
    return len(students)


def start_next_academic_term(db: Session, setting: models.AcademicTermSetting) -> None:
    if setting.current_status != "ended" or not setting.next_academic_year or not setting.next_semester:
        raise ValueError("The current semester must be ended and a next semester must be configured.")

    setting.current_academic_year = setting.next_academic_year
    setting.current_semester = setting.next_semester
    setting.current_start_date = setting.next_start_date
    setting.current_end_date = setting.next_end_date
    setting.current_status = "active"
    (
        setting.next_academic_year,
        setting.next_semester,
        setting.next_start_date,
        setting.next_end_date,
    ) = get_following_semester(setting.current_academic_year, setting.current_semester)
    db.commit()

    create_admin_notification(
        db,
        f"{setting.current_academic_year} {setting.current_semester} has started.",
        "academic_term",
        setting.id,
        "/admin/User-Management?tab=student",
    )


def process_academic_term_schedule(db: Session, today: date | None = None) -> models.AcademicTermSetting:
    setting = get_or_create_academic_term_setting(db)
    current_date = today or date.today()
    if setting.current_status == "active" and setting.current_end_date and current_date >= setting.current_end_date:
        end_current_academic_term(db, setting)
    if (
        setting.current_status == "ended"
        and setting.next_start_date
        and current_date >= setting.next_start_date
    ):
        start_next_academic_term(db, setting)
    return setting


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
        report_owner_user_id=item.report_owner_user_id,
        report_owner_name=item.report_owner_name,
        report_owner_group=item.report_owner_group,
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


print("Admin routes loaded")

MAX_BULK_REGISTRATION_ROWS = 5000


def process_bulk_registration_job(job_id: str, users_list: list[dict], duplicate_action: str):
    db = SessionLocal()
    started_at = datetime.utcnow()

    results = []
    created_count = 0
    replaced_count = 0
    ignored_count = 0

    total_students = len(users_list)

    # Tuning knobs
    lookup_chunk_size = 800      # SQL Server-safe lookup chunk for large 3k+ uploads
    commit_chunk_size = 100      # keep each database transaction small and responsive
    password_hash_chunk_size = 100
    # Keep one CPU-heavy bcrypt worker so bulk registration cannot starve
    # the single web process on a small Azure App Service plan.
    hash_workers = 1

    def push_bulk_progress(processed_count: int, message: str | None = None):
        safe_processed = min(max(processed_count, 0), total_students)
        update_payload = {
            "processed": safe_processed,
            "progress": int((safe_processed / total_students) * 100) if total_students else 100,
            "summary": {
                "total": total_students,
                "created": created_count,
                "replaced": replaced_count,
                "ignored": ignored_count,
                "duplicate_action": duplicate_action
            }
        }
        if message is not None:
            update_payload["message"] = message
        update_bulk_job(job_id, **update_payload)

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
        if total_students == 0:
            update_bulk_job(
                job_id,
                status="completed",
                finished_at=datetime.utcnow().isoformat(),
                progress=100,
                processed=0,
                total=0,
                results=[],
                summary={
                    "total": 0,
                    "created": 0,
                    "replaced": 0,
                    "ignored": 0,
                    "duplicate_action": duplicate_action
                },
                message="No users to process."
            )
            return

        def chunked(seq, size):
            for i in range(0, len(seq), size):
                yield seq[i:i + size]

        # ---------------------------------------------------------
        # PASS 1: normalize rows + detect duplicates inside upload
        # ---------------------------------------------------------
        normalized_rows = []
        seen_student_nos = set()
        seen_emails = set()

        def get_missing_registration_fields(row):
            missing_fields = []
            if not row["student_no"]:
                missing_fields.append("Employee No." if row["is_employee_import"] else "Student ID")
            elif not row["is_employee_import"] and len(row["student_no"]) < 10:
                missing_fields.append("Student ID must be at least 10 digits")
            if not row["first_name"]:
                missing_fields.append("First Name")
            if not row["last_name"]:
                missing_fields.append("Last Name")
            return missing_fields

        for s in users_list:
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

            last_6 = s_id[-6:] if s_id else ""
            email_addr = (
                build_faculty_email(first_n, last_n)
                if is_employee_import and s_id
                else (
                    f"{last_n.lower().replace(' ', '')}.{last_6}@novaliches.sti.edu.ph"
                    if s_id and last_n else ""
                )
            )

            if is_employee_import and not department:
                department = infer_employee_account_label(s_id)

            default_pass = f"STI{s_id}" if s_id else ""
            new_full_name = (
                display_name
                or f"{first_n} {middle_n} {last_n}".replace("  ", " ").strip()
            )

            row = {
                "source_type": source_type,
                "is_employee_import": is_employee_import,
                "student_no": s_id,
                "last_name": last_n,
                "first_name": first_n,
                "middle_name": middle_n,
                "course": course,
                "level": level,
                "batch_id": batch_val,
                "department": department,
                "display_name": display_name,
                "permissions": json.dumps(initial_permissions),
                "email": email_addr,
                "temp_password": default_pass,
                "full_name": new_full_name,
                "hashed_password": None
            }

            missing_fields = get_missing_registration_fields(row)
            if missing_fields:
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
                    "status": f"Ignored - Missing {', '.join(missing_fields)}"
                })
                continue

            email_key = email_addr.lower() if email_addr else ""
            if s_id in seen_student_nos or (email_key and email_key in seen_emails):
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
                continue

            seen_student_nos.add(s_id)
            if email_key:
                seen_emails.add(email_key)

            normalized_rows.append(row)

        processed_seed = len(results)
        push_bulk_progress(
            processed_seed,
            "Validating uploaded users before registration..."
        )

        # ---------------------------------------------------------
        # PASS 2: preload possible existing users in SQL Server-safe chunks
        # ---------------------------------------------------------
        student_nos = [r["student_no"] for r in normalized_rows if r["student_no"]]
        emails = [r["email"] for r in normalized_rows if r["email"]]

        existing_users = []
        max_len = max(len(student_nos), len(emails))

        for i in range(0, max_len, lookup_chunk_size):
            ids_chunk = student_nos[i:i + lookup_chunk_size]
            emails_chunk = emails[i:i + lookup_chunk_size]

            q = db.query(models.User)

            if ids_chunk and emails_chunk:
                rows = q.filter(
                    (models.User.student_no.in_(ids_chunk)) |
                    (models.User.email.in_(emails_chunk))
                ).all()
            elif ids_chunk:
                rows = q.filter(models.User.student_no.in_(ids_chunk)).all()
            elif emails_chunk:
                rows = q.filter(models.User.email.in_(emails_chunk)).all()
            else:
                rows = []

            existing_users.extend(rows)

        existing_by_student_no = {}
        existing_by_email = {}

        for user in existing_users:
            if user.student_no:
                existing_by_student_no[str(user.student_no).strip()] = user
            if user.email:
                existing_by_email[str(user.email).strip().lower()] = user

        # ---------------------------------------------------------
        # PASS 3: hash all required passwords in one persistent pool
        # ---------------------------------------------------------
        from concurrent.futures import as_completed

        def hash_password(row):
            return pwd_context.hash(row["temp_password"])

        def apply_registration_row_to_user(user, row, *, keep_archived: bool):
            user.first_name = row["first_name"]
            user.middle_name = row["middle_name"]
            user.last_name = row["last_name"]
            user.full_name = row["full_name"]
            user.student_no = row["student_no"]
            user.email = row["email"]
            user.course = row["course"]
            user.department = row["department"]
            user.level = row["level"]
            user.batch_id = row["batch_id"]
            user.hashed_password = row["hashed_password"]
            user.must_change_password = True
            user.is_archived = bool(keep_archived)
            user.is_admin = False
            user.permissions = row["permissions"]

        rows_to_hash = []
        for row in normalized_rows:
            email_key = row["email"].strip().lower() if row["email"] else ""
            existing_user = (
                existing_by_student_no.get(row["student_no"])
                or existing_by_email.get(email_key)
            )
            needs_password = (
                existing_user is None
                or (
                    not existing_user.is_admin
                    and (
                        existing_user.is_archived
                        or duplicate_action == "replace"
                    )
                )
            )
            if needs_password:
                rows_to_hash.append(row)

        if rows_to_hash:
            hashed_count = 0
            for password_chunk in chunked(rows_to_hash, password_hash_chunk_size):
                update_bulk_job(
                    job_id,
                    message=(
                        f"Securely preparing passwords "
                        f"{hashed_count + 1}-{hashed_count + len(password_chunk)} "
                        f"of {len(rows_to_hash):,}..."
                    )
                )
                with ThreadPoolExecutor(max_workers=hash_workers) as executor:
                    futures = {
                        executor.submit(hash_password, row): row
                        for row in password_chunk
                    }
                    for future in as_completed(futures):
                        futures[future]["hashed_password"] = future.result()
                hashed_count += len(password_chunk)

        # ---------------------------------------------------------
        # PASS 4: write users in bounded transaction chunks
        # ---------------------------------------------------------
        processed_valid_rows = processed_seed

        for row_chunk in chunked(normalized_rows, commit_chunk_size):
            pending_results = []
            pending_creates = []
            pending_counters = {
                "created": 0,
                "replaced": 0,
                "ignored": 0
            }

            try:
                update_bulk_job(
                    job_id,
                    message=f"Processing users {processed_valid_rows + 1}-{min(processed_valid_rows + len(row_chunk), total_students)} of {total_students}..."
                )

                for row in row_chunk:
                    s_id = row["student_no"]
                    email_addr = row["email"]
                    email_key = email_addr.strip().lower() if email_addr else ""

                    existing_user = existing_by_student_no.get(s_id) or existing_by_email.get(email_key)

                    if existing_user:
                        if existing_user.is_admin:
                            pending_counters["ignored"] += 1
                            pending_results.append({
                                "email": email_addr,
                                "student_no": s_id,
                                "full_name": row["full_name"],
                                "course": row["course"],
                                "department": row["department"],
                                "level": row["level"],
                                "batch_id": row["batch_id"],
                                "temp_password": "",
                                "status": "Ignored - Conflicts with existing admin"
                            })

                        elif existing_user.is_archived:
                            # Semester-end processing archives prior-term students.
                            # Registering one again means they are enrolled for the
                            # current term, so restore the account to the active list.
                            apply_registration_row_to_user(existing_user, row, keep_archived=False)

                            existing_by_student_no[s_id] = existing_user
                            if email_key:
                                existing_by_email[email_key] = existing_user

                            pending_counters["replaced"] += 1
                            pending_results.append({
                                "email": row["email"],
                                "student_no": row["student_no"],
                                "full_name": row["full_name"],
                                "course": row["course"],
                                "department": row["department"],
                                "level": row["level"],
                                "batch_id": row["batch_id"],
                                "temp_password": row["temp_password"],
                                "status": "Re-registered for current term"
                            })

                        elif duplicate_action == "ignore":
                            pending_counters["ignored"] += 1
                            pending_results.append({
                                "email": existing_user.email,
                                "student_no": existing_user.student_no,
                                "full_name": existing_user.full_name or row["full_name"],
                                "course": existing_user.course or row["course"],
                                "department": existing_user.department or row["department"],
                                "level": existing_user.level or row["level"],
                                "batch_id": existing_user.batch_id or row["batch_id"],
                                "temp_password": "",
                                "status": "Ignored - Already registered"
                            })

                        else:
                            apply_registration_row_to_user(existing_user, row, keep_archived=False)

                            existing_by_student_no[s_id] = existing_user
                            if email_key:
                                existing_by_email[email_key] = existing_user

                            pending_counters["replaced"] += 1
                            pending_results.append({
                                "email": row["email"],
                                "student_no": row["student_no"],
                                "full_name": row["full_name"],
                                "course": row["course"],
                                "department": row["department"],
                                "level": row["level"],
                                "batch_id": row["batch_id"],
                                "temp_password": row["temp_password"],
                                "status": "Replaced existing user"
                            })

                    else:
                        user_obj = models.User(
                            first_name=row["first_name"],
                            middle_name=row["middle_name"],
                            last_name=row["last_name"],
                            full_name=row["full_name"],
                            student_no=row["student_no"],
                            email=row["email"],
                            course=row["course"],
                            department=row["department"],
                            level=row["level"],
                            batch_id=row["batch_id"],
                            hashed_password=row["hashed_password"],
                            is_admin=False,
                            must_change_password=True,
                            permissions=row["permissions"]
                        )
                        pending_creates.append(user_obj)

                        pending_counters["created"] += 1
                        pending_results.append({
                            "email": row["email"],
                            "student_no": row["student_no"],
                            "full_name": row["full_name"],
                            "course": row["course"],
                            "department": row["department"],
                            "level": row["level"],
                            "batch_id": row["batch_id"],
                            "temp_password": row["temp_password"],
                            "status": "Created"
                        })

                if pending_creates:
                    db.add_all(pending_creates)

                db.commit()

                results.extend(pending_results)
                created_count += pending_counters["created"]
                replaced_count += pending_counters["replaced"]
                ignored_count += pending_counters["ignored"]
                processed_valid_rows += len(pending_results)
                push_bulk_progress(
                    processed_valid_rows,
                    f"Registered {processed_valid_rows}/{total_students} users..."
                )

            except IntegrityError:
                # Fallback: isolate bad rows one by one
                db.rollback()

                for row in row_chunk:
                    s_id = row["student_no"]
                    email_addr = row["email"]
                    email_key = email_addr.strip().lower() if email_addr else ""
                    existing_user = existing_by_student_no.get(s_id) or existing_by_email.get(email_key)

                    try:
                        if existing_user:
                            if existing_user.is_admin:
                                ignored_count += 1
                                results.append({
                                    "email": email_addr,
                                    "student_no": s_id,
                                    "full_name": row["full_name"],
                                    "course": row["course"],
                                    "department": row["department"],
                                    "level": row["level"],
                                    "batch_id": row["batch_id"],
                                    "temp_password": "",
                                    "status": "Ignored - Conflicts with existing admin"
                                })
                                processed_valid_rows += 1
                                push_bulk_progress(
                                    processed_valid_rows,
                                    f"Registered {processed_valid_rows}/{total_students} users..."
                                )

                            elif existing_user.is_archived:
                                apply_registration_row_to_user(existing_user, row, keep_archived=False)

                                db.commit()

                                existing_by_student_no[s_id] = existing_user
                                if email_key:
                                    existing_by_email[email_key] = existing_user

                                replaced_count += 1
                                results.append({
                                    "email": row["email"],
                                    "student_no": row["student_no"],
                                    "full_name": row["full_name"],
                                    "course": row["course"],
                                    "department": row["department"],
                                    "level": row["level"],
                                    "batch_id": row["batch_id"],
                                    "temp_password": row["temp_password"],
                                    "status": "Re-registered for current term"
                                })
                                processed_valid_rows += 1
                                push_bulk_progress(
                                    processed_valid_rows,
                                    f"Registered {processed_valid_rows}/{total_students} users..."
                                )

                            elif duplicate_action == "ignore":
                                ignored_count += 1
                                results.append({
                                    "email": existing_user.email,
                                    "student_no": existing_user.student_no,
                                    "full_name": existing_user.full_name or row["full_name"],
                                    "course": existing_user.course or row["course"],
                                    "department": existing_user.department or row["department"],
                                    "level": existing_user.level or row["level"],
                                    "batch_id": existing_user.batch_id or row["batch_id"],
                                    "temp_password": "",
                                    "status": "Ignored - Already registered"
                                })
                                processed_valid_rows += 1
                                push_bulk_progress(
                                    processed_valid_rows,
                                    f"Registered {processed_valid_rows}/{total_students} users..."
                                )

                            else:
                                apply_registration_row_to_user(existing_user, row, keep_archived=False)

                                db.commit()

                                existing_by_student_no[s_id] = existing_user
                                if email_key:
                                    existing_by_email[email_key] = existing_user

                                replaced_count += 1
                                results.append({
                                    "email": row["email"],
                                    "student_no": row["student_no"],
                                    "full_name": row["full_name"],
                                    "course": row["course"],
                                    "department": row["department"],
                                    "level": row["level"],
                                    "batch_id": row["batch_id"],
                                    "temp_password": row["temp_password"],
                                    "status": "Replaced existing user"
                                })
                                processed_valid_rows += 1
                                push_bulk_progress(
                                    processed_valid_rows,
                                    f"Registered {processed_valid_rows}/{total_students} users..."
                                )

                        else:
                            user_obj = models.User(
                                first_name=row["first_name"],
                                middle_name=row["middle_name"],
                                last_name=row["last_name"],
                                full_name=row["full_name"],
                                student_no=row["student_no"],
                                email=row["email"],
                                course=row["course"],
                                department=row["department"],
                                level=row["level"],
                                batch_id=row["batch_id"],
                                hashed_password=row["hashed_password"],
                                is_admin=False,
                                must_change_password=True,
                                permissions=row["permissions"]
                            )
                            db.add(user_obj)
                            db.commit()

                            created_count += 1
                            results.append({
                                "email": row["email"],
                                "student_no": row["student_no"],
                                "full_name": row["full_name"],
                                "course": row["course"],
                                "department": row["department"],
                                "level": row["level"],
                                "batch_id": row["batch_id"],
                                "temp_password": row["temp_password"],
                                "status": "Created"
                            })
                            processed_valid_rows += 1
                            push_bulk_progress(
                                processed_valid_rows,
                                f"Registered {processed_valid_rows}/{total_students} users..."
                            )

                    except IntegrityError:
                        db.rollback()
                        ignored_count += 1
                        results.append({
                            "email": row["email"],
                            "student_no": row["student_no"] or "N/A",
                            "full_name": row["full_name"] or "Invalid Row",
                            "course": row["course"],
                            "department": row["department"],
                            "level": row["level"],
                            "batch_id": row["batch_id"],
                            "temp_password": "",
                            "status": "Ignored - Duplicate email or student number conflict"
                        })
                        processed_valid_rows += 1
                        push_bulk_progress(
                            processed_valid_rows,
                            f"Registered {processed_valid_rows}/{total_students} users..."
                        )

                    except Exception as row_error:
                        db.rollback()
                        ignored_count += 1
                        results.append({
                            "email": row["email"],
                            "student_no": row["student_no"] or "N/A",
                            "full_name": row["full_name"] or "Invalid Row",
                            "course": row["course"],
                            "department": row["department"],
                            "level": row["level"],
                            "batch_id": row["batch_id"],
                            "temp_password": "",
                            "status": f"Failed - {str(row_error)[:120]}"
                        })
                        processed_valid_rows += 1
                        push_bulk_progress(
                            processed_valid_rows,
                            f"Registered {processed_valid_rows}/{total_students} users..."
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
            None,
            created_by_admin_id=BULK_REGISTRATION_JOBS.get(job_id, {}).get("requested_by")
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
    current_admin: models.User = Depends(get_current_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if is_root_admin(user) and not is_root_admin(current_admin):
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
    create_admin_notification(
        db,
        f"{current_admin.full_name or current_admin.email} {status} user {user.full_name or user.email}.",
        "user_management_students" if not user.is_admin else "user_management_admin",
        user.id,
        created_by_admin_id=current_admin.id
    )
    return {"message": f"User {user.full_name} has been {status}."}


@router.post("/bulk-toggle-archive")
async def bulk_toggle_archive(
    data: StudentActivationRequest,
    archive: bool,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Archive"))
):
    user_ids = list(dict.fromkeys(data.user_ids))
    if not user_ids:
        raise HTTPException(status_code=400, detail="No users selected.")

    chunk_size = 1000
    updated_count = 0

    if archive:
        for start in range(0, len(user_ids), chunk_size):
            user_id_chunk = user_ids[start:start + chunk_size]
            updated_count += db.query(models.User).filter(
                models.User.id.in_(user_id_chunk),
                models.User.id != current_admin.id,
                models.User.email != ROOT_ADMIN_EMAIL,
                models.User.is_archived == False
            ).update(
                {
                    models.User.is_archived: True,
                    models.User.permissions: json.dumps([])
                },
                synchronize_session=False
            )
    else:
        users: list[models.User] = []
        for start in range(0, len(user_ids), chunk_size):
            user_id_chunk = user_ids[start:start + chunk_size]
            users.extend(
                db.query(models.User).filter(
                    models.User.id.in_(user_id_chunk),
                    models.User.id != current_admin.id,
                    models.User.email != ROOT_ADMIN_EMAIL,
                    models.User.is_archived == True
                ).all()
            )

        for user in users:
            permissions = parse_permissions(user.permissions)
            permissions = [permission for permission in permissions if permission != DELETE_QUEUE_PERMISSION]
            user.permissions = json.dumps(permissions)
            user.is_archived = False
            updated_count += 1

    if updated_count == 0:
        raise HTTPException(status_code=404, detail="No eligible users found.")

    db.commit()

    status = "archived" if archive else "restored"
    return {
        "message": f"{updated_count} user account(s) {status} successfully.",
        "count": updated_count,
        "requested_count": len(user_ids)
    }

@router.post("/move-to-delete/{user_id}")
async def move_user_to_delete(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Delete"))
):
    user = db.query(models.User).filter(models.User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if is_root_admin(user):
        raise HTTPException(status_code=404, detail="User not found")

    permissions = parse_permissions(user.permissions)
    user.is_archived = True
    user.archived_at = datetime.utcnow()
    if DELETE_QUEUE_PERMISSION not in permissions:
        permissions.append(DELETE_QUEUE_PERMISSION)
    user.permissions = json.dumps(permissions)
    db.commit()
    create_admin_notification(
        db,
        f"{current_admin.full_name or current_admin.email} moved user {user.full_name or user.email} to Trash.",
        "user_management_students" if not user.is_admin else "user_management_admin",
        user.id,
        created_by_admin_id=current_admin.id
    )

    return {"message": f"User {user.full_name} moved to Trash."}


@router.post("/bulk-move-to-delete")
async def bulk_move_users_to_delete(
    data: StudentActivationRequest,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Delete"))
):
    user_ids = list(dict.fromkeys(data.user_ids))
    if not user_ids:
        raise HTTPException(status_code=400, detail="No users selected.")

    users: list[models.User] = []
    chunk_size = 1000
    for start in range(0, len(user_ids), chunk_size):
        user_id_chunk = user_ids[start:start + chunk_size]
        users.extend(
            db.query(models.User).filter(
                models.User.id.in_(user_id_chunk),
                models.User.email != ROOT_ADMIN_EMAIL,
                models.User.id != current_admin.id
            ).all()
        )

    if not users:
        raise HTTPException(status_code=404, detail="No eligible users found.")

    moved_count = 0
    for user in users:
        permissions = parse_permissions(user.permissions)
        user.is_archived = True
        user.archived_at = datetime.utcnow()
        if DELETE_QUEUE_PERMISSION not in permissions:
            permissions.append(DELETE_QUEUE_PERMISSION)
        user.permissions = json.dumps(permissions)
        moved_count += 1

    db.commit()

    return {
        "message": f"{moved_count} user account(s) moved to Trash successfully.",
        "count": moved_count,
        "requested_count": len(user_ids)
    }

# ROUTE 2: Permanent Delete (Hard Delete)
@router.delete("/permanent-delete/{user_id}")
async def permanent_delete(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Delete"))
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if is_root_admin(user):
        raise HTTPException(status_code=404, detail="User not found")

    try:
        deleted_user_name = user.full_name or user.email or f"User #{user_id}"
        deleted_user_is_admin = bool(user.is_admin)
        delete_user_and_related_records(db, user)
        db.commit()
        create_admin_notification(
            db,
            f"{deleted_user_name} was permanently deleted from User Management.",
            "user_management_admin" if deleted_user_is_admin else "user_management_students",
            user_id,
            created_by_admin_id=current_admin.id
        )
        
        return {"message": "User and all related records (messages, claims, items) deleted."}

    except Exception as e:
        db.rollback()
        print(f"Delete Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Database Integrity Error: User has active records.")


@router.delete("/bulk-permanent-delete")
async def bulk_permanent_delete(
    data: StudentActivationRequest,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Delete"))
):
    user_ids = list(dict.fromkeys(data.user_ids))
    if not user_ids:
        raise HTTPException(status_code=400, detail="No users selected.")

    users: list[models.User] = []
    chunk_size = 500
    for start in range(0, len(user_ids), chunk_size):
        user_id_chunk = user_ids[start:start + chunk_size]
        users.extend(
            db.query(models.User).filter(
                models.User.id.in_(user_id_chunk),
                models.User.email != ROOT_ADMIN_EMAIL
            ).all()
        )

    if not users:
        raise HTTPException(status_code=404, detail="No eligible users found for deletion.")

    deleted_count = 0
    try:
        for user in users:
            delete_user_and_related_records(db, user)
            deleted_count += 1
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Bulk Delete Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Database Integrity Error: Some users still have active records.")

    return {
        "message": f"{deleted_count} user account(s) deleted permanently.",
        "count": deleted_count,
        "requested_count": len(user_ids)
    }

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

    import torch
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
    if is_root_admin(admin):
        return ADMIN_PERMISSION_KEYS

    # If permissions are stored as a JSON string in DB, decode them
    if isinstance(admin.permissions, str):
        return json.loads(admin.permissions)
    return admin.permissions # Return list directly if already a list

@router.post("/items/confirm-match/{lost_id}/{found_id}")
async def confirm_match(
    lost_id: int,
    found_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    lost_item = db.query(models.Item).filter(models.Item.id == lost_id).first()
    found_item = db.query(models.Item).filter(models.Item.id == found_id).first()

    if not lost_item or not found_item:
        raise HTTPException(status_code=404, detail="Items not found")

    # This is where the magic happens
    lost_item.is_matched = True
    found_item.is_matched = True

    db.commit()
    return {"message": "Items successfully matched!"}


@router.get("/items/found")
def get_found_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    items = db.query(models.Item).filter(
        models.Item.status == "found",
        models.Item.archived == False,
        models.Item.deleted == False,
    ).all()
    return [serialize_inventory_item(db, item) for item in items]

@router.get("/items/found/archived")
def get_archived_found_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    items = db.query(models.Item).filter(
        models.Item.status == "found",
        models.Item.archived == True,
        models.Item.deleted == False,
    ).all()
    return [serialize_inventory_item(db, item) for item in items]

@router.get("/items/found/deleted")
def get_deleted_found_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    items = db.query(models.Item).filter(
        models.Item.status == "found",
        models.Item.deleted == True,
    ).all()
    return [serialize_inventory_item(db, item) for item in items]

@router.get("/items/lost")
def get_lost_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    items = db.query(models.Item).filter(
        models.Item.status == "lost",
        models.Item.archived == False,
        models.Item.deleted == False,
    ).all()
    return [serialize_inventory_item(db, item) for item in items]

@router.get("/items/lost/archived")
def get_archived_lost_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    items = db.query(models.Item).filter(
        models.Item.status == "lost",
        models.Item.archived == True,
        models.Item.deleted == False,
    ).all()
    return [serialize_inventory_item(db, item) for item in items]

@router.get("/items/lost/deleted")
def get_deleted_lost_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    items = db.query(models.Item).filter(
        models.Item.status == "lost",
        models.Item.deleted == True,
    ).all()
    return [serialize_inventory_item(db, item) for item in items]
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
    request: Request
):
    return templates.TemplateResponse(
        "Admin Pages/User_Management.html",
        {"request": request}
    )
@router.get("/Messages")
def admin_Messages( # Renamed this function
    request: Request
):
   
    return templates.TemplateResponse(
        "Admin Pages/Admin_Message.html",
        {"request": request} 
    )

@router.get("/Lost_Items_Report")
def admin_lost_items_report( # Renamed this function
    request: Request
):

    
    return templates.TemplateResponse(
        "Admin Pages/Lost_item_Report.html",
        {"request": request} 
    )

@router.get("/Found_Items_Report")
def admin_found_items_report( # Renamed this function
    request: Request
):
    
    return templates.TemplateResponse(
        "Admin Pages/Found_item_Report.html",
         {"request": request} 
    )

@router.get("/Claim-Management" )
def admin_claim_management( # Renamed this function
    request: Request
):  
    
    return templates.TemplateResponse(
        "Admin Pages/Claim_Management.html",
        {"request": request} 
    )
@router.get("/Reports")
def admin_reports(
    request: Request
):
    return templates.TemplateResponse(
        "Admin Pages/Reports.html",
        {"request": request}
    )
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
    current_user: models.User = Depends(get_current_admin) 
):
    user = current_user
    
    if not user:
        return {"error": "User not found"}

    # Handle Image Upload
    if profile_img and profile_img.filename:
        os.makedirs(STATIC_PROFILE_PICS_DIR, exist_ok=True)
        file_extension = os.path.splitext(profile_img.filename)[1]
        db_file_path = f"static/profile_pics/user_{user.id}{file_extension}"
        file_path = os.path.join(STATIC_PROFILE_PICS_DIR, f"user_{user.id}{file_extension}")
        
        with open(file_path, "wb") as buffer:
            buffer.write(await profile_img.read())
        
        user.profile_pic = db_file_path

    # Update Text Fields (Email remains read-only for security)
    if full_name: user.full_name = full_name
    if student_no: user.student_no = student_no
    if course: user.course = course
    if section: user.section = section

    db.commit()
    create_admin_notification(
        db,
        f"{user.full_name or user.email} updated the admin profile information.",
        "user_management_admin",
        user.id,
        "/admin/Profile",
        created_by_admin_id=user.id
    )
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
    request: Request
):
   
    return templates.TemplateResponse(
        "Admin Pages/Confiscated_Item.html",
        {"request": request} 
    )   

@router.get("/Content-management")
def admin_content_management(
    request: Request
):
    
    return templates.TemplateResponse(
        "Admin Pages/Content_Management.html",
        {"request": request} 
    )
@router.get("/Content-management/features")
def admin_content_management(
    request: Request
):
    
    return templates.TemplateResponse(
        "Admin Pages/admin_cms_features.html",
        {"request": request} 
    )
@router.get("/Content-management/about")
def admin_content_management(
    request: Request
):
    
    return templates.TemplateResponse(
        "Admin Pages/admin_cms_about.html",
        {"request": request} 
    )


@router.get("/Content-Editor")
async def content_editor_page(
    request: Request
):
    # You can add logic here to fetch existing content from the DB 
    # to pre-fill the inputs if you want!
    return templates.TemplateResponse(
        "/Admin Pages/admin_cms.html",
        {"request": request}
        )

@router.get("/pending-items")
def get_pending_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    auto_archive_pending(db)

    items = db.query(models.PendingItem).filter(
        models.PendingItem.archived == False,
        models.PendingItem.deleted == False,
    ).order_by(models.PendingItem.created_at.desc()).all()

    return [serialize_pending_item(db, item) for item in items]


@router.get("/pending-items/archived")
def get_archived_pending_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    items = db.query(models.PendingItem).filter(
        models.PendingItem.archived == True,
        models.PendingItem.deleted == False,
    ).order_by(models.PendingItem.created_at.desc()).all()

    return [serialize_pending_item(db, item) for item in items]

@router.get("/pending-items/deleted")
def get_deleted_pending_items(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    items = db.query(models.PendingItem).filter(
        models.PendingItem.deleted == True
    ).order_by(models.PendingItem.created_at.desc()).all()
    return [serialize_pending_item(db, item) for item in items]

@router.get("/departments")
async def get_departments(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    # Fetches the list we inserted (Registrar, IT Dept, etc.)
    return db.query(models.Department).all()

@router.get("/category")
async def get_caregory(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
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
    create_admin_notification(
        db,
        f"Department '{new_department.name}' was added in Content Management.",
        "new_report",
        new_department.id,
        "/admin/Content-management",
        created_by_admin_id=admin.id
    )
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

    department_name = department.name
    db.delete(department)
    db.commit()
    create_admin_notification(
        db,
        f"Department '{department_name}' was deleted from Content Management.",
        "new_report",
        department_id,
        "/admin/Content-management",
        created_by_admin_id=admin.id
    )
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
    create_admin_notification(
        db,
        f"Category '{new_category.name}' was added in Content Management.",
        "new_report",
        new_category.id,
        "/admin/Content-management",
        created_by_admin_id=admin.id
    )
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

    category_name = category.name
    db.delete(category)
    db.commit()
    create_admin_notification(
        db,
        f"Category '{category_name}' was deleted from Content Management.",
        "new_report",
        category_id,
        "/admin/Content-management",
        created_by_admin_id=admin.id
    )
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

    first_name = admin_in.first_name.strip()
    middle_name = (admin_in.middle_name or "").strip()
    last_name = admin_in.last_name.strip()
    full_name = (
        admin_in.full_name.strip()
        if admin_in.full_name and admin_in.full_name.strip()
        else f"{first_name} {middle_name} {last_name}".replace("  ", " ").strip()
    )
    admin_id = admin_in.student_no.strip()

    if not first_name or not last_name:
        raise HTTPException(status_code=400, detail="First name and last name are required")
    if not admin_id:
        raise HTTPException(status_code=400, detail="Admin / Employee ID is required")
    if not (admin_in.department or "").strip():
        raise HTTPException(status_code=400, detail="Department / Office is required")

    existing = db.query(models.User).filter(
        or_(
            models.User.email == admin_in.email,
            models.User.student_no == admin_id,
        )
    ).first()
    if existing:
        if existing.student_no == admin_id:
            raise HTTPException(status_code=400, detail="Admin / Employee ID is already registered")
        raise HTTPException(status_code=400, detail="Admin email already registered")

    temp_password = secrets.token_urlsafe(8)
    new_admin = models.User(
        student_no=admin_id,
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        full_name=full_name,
        email=admin_in.email,
        hashed_password=pwd_context.hash(temp_password),
        is_admin=True,
        permissions=json.dumps(requested_permissions),
        department=admin_in.department.strip(),
        section=admin_in.section,
        must_change_password=True,
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    create_admin_notification(
        db,
        f"New admin account created for {full_name}.",
        "user_management_admin",
        new_admin.id,
        created_by_admin_id=current_admin.id,
    )
    return {
        "message": "Admin created successfully",
        "temp_password": temp_password,
        "admin_id": admin_id,
    }


@router.get("/academic-term")
def get_academic_term(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin),
):
    permissions = parse_permissions(admin.permissions)
    if not is_root_admin(admin) and not ({"User-Management", "Content-management"} & set(permissions)):
        raise HTTPException(status_code=403, detail="Access denied.")
    setting = process_academic_term_schedule(db)
    return serialize_academic_term_setting(setting)


@router.put("/academic-term")
def update_academic_term(
    data: AcademicTermScheduleUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("Content-management")),
):
    if data.current_end_date <= data.current_start_date:
        raise HTTPException(status_code=400, detail="Current semester end date must be after its start date.")
    if data.next_start_date <= data.current_end_date:
        raise HTTPException(status_code=400, detail="Next semester must start after the current semester ends.")
    if data.next_end_date <= data.next_start_date:
        raise HTTPException(status_code=400, detail="Next semester end date must be after its start date.")
    if data.current_semester not in {"1st Semester", "2nd Semester"} or data.next_semester not in {"1st Semester", "2nd Semester"}:
        raise HTTPException(status_code=400, detail="Invalid semester.")

    setting = get_or_create_academic_term_setting(db)
    if setting.current_status == "active":
        active_term_changed = any([
            data.current_academic_year != setting.current_academic_year,
            data.current_semester != setting.current_semester,
            data.current_start_date != setting.current_start_date,
            data.current_end_date != setting.current_end_date,
        ])
        if active_term_changed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The current semester is already active and cannot be changed. "
                    "End the semester before editing its academic year, semester, or dates."
                ),
            )

    setting.current_academic_year = data.current_academic_year
    setting.current_semester = data.current_semester
    setting.current_start_date = data.current_start_date
    setting.current_end_date = data.current_end_date
    setting.next_academic_year = data.next_academic_year
    setting.next_semester = data.next_semester
    setting.next_start_date = data.next_start_date
    setting.next_end_date = data.next_end_date
    db.commit()

    create_admin_notification(
        db,
        f"{data.current_academic_year} {data.current_semester} is scheduled to end on "
        f"{data.current_end_date.strftime('%B %d, %Y')}. Its active student accounts will be archived. "
        f"{data.next_academic_year} {data.next_semester} starts on {data.next_start_date.strftime('%B %d, %Y')}.",
        "academic_term",
        setting.id,
        "/admin/User-Management",
    )
    return serialize_academic_term_setting(setting)


@router.post("/academic-term/end")
def manually_end_academic_term(
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("User-Management-Archive")),
):
    setting = get_or_create_academic_term_setting(db)
    archived_count = end_current_academic_term(db, setting, admin.id)
    return {
        "message": f"{setting.current_academic_year} {setting.current_semester} ended.",
        "archived_count": archived_count,
        "term": serialize_academic_term_setting(setting),
    }


@router.post("/academic-term/reactivate")
def reactivate_academic_term(
    data: AcademicTermReactivateRequest,
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("User-Management-Archive")),
):
    setting = get_or_create_academic_term_setting(db)
    if setting.current_status != "ended":
        raise HTTPException(status_code=409, detail="Only an ended semester can be reactivated.")
    if data.new_end_date <= date.today():
        raise HTTPException(status_code=400, detail="Choose a new end date after today.")
    if setting.next_start_date and data.new_end_date >= setting.next_start_date:
        raise HTTPException(
            status_code=400,
            detail="The new end date must be before the next semester starts.",
        )

    transition = (
        db.query(models.AcademicTermTransition)
        .filter(
            models.AcademicTermTransition.academic_year == setting.current_academic_year,
            models.AcademicTermTransition.semester == setting.current_semester,
            models.AcademicTermTransition.reactivated_at == None,
        )
        .order_by(models.AcademicTermTransition.ended_at.desc())
        .first()
    )

    archived_ids: list[int] = []
    if transition:
        try:
            archived_ids = [int(user_id) for user_id in json.loads(transition.archived_user_ids or "[]")]
        except (TypeError, ValueError, json.JSONDecodeError):
            archived_ids = []

    query = db.query(models.User).filter(
        models.User.is_admin == False,
        models.User.is_archived == True,
    )
    if archived_ids:
        # SQL Server limits a statement to 2,100 parameters. Large semesters can
        # contain several thousand students, so restore the archived IDs in
        # bounded queries instead of one oversized IN clause.
        candidates = []
        unique_archived_ids = list(dict.fromkeys(archived_ids))
        for offset in range(0, len(unique_archived_ids), 1000):
            id_chunk = unique_archived_ids[offset:offset + 1000]
            candidates.extend(
                query.filter(models.User.id.in_(id_chunk)).all()
            )
    else:
        # Compatibility for a semester ended before transition tracking was installed.
        candidates = query.filter(
            models.User.batch_id.like(f"BATCH-{setting.current_academic_year} %")
        ).all()

    students = [user for user in candidates if not user_is_faculty_account(user)]
    for student in students:
        student.is_archived = False

    setting.current_status = "active"
    setting.current_end_date = data.new_end_date
    if transition:
        transition.reactivated_by_admin_id = admin.id
        transition.reactivated_at = datetime.utcnow()
        transition.replacement_end_date = data.new_end_date
    db.commit()

    create_admin_notification(
        db,
        f"{setting.current_academic_year} {setting.current_semester} was reactivated until "
        f"{data.new_end_date.strftime('%B %d, %Y')}. {len(students)} student account(s) were restored.",
        "academic_term",
        setting.id,
        "/admin/User-Management?tab=student",
    )
    return {
        "message": f"{setting.current_academic_year} {setting.current_semester} is active again.",
        "restored_count": len(students),
        "term": serialize_academic_term_setting(setting),
    }


@router.post("/academic-term/start")
def manually_start_academic_term(
    db: Session = Depends(get_db),
    admin: models.User = Depends(check_permission("User-Management-Archive")),
):
    setting = get_or_create_academic_term_setting(db)
    try:
        start_next_academic_term(db, setting)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": f"{setting.current_academic_year} {setting.current_semester} started.",
        "term": serialize_academic_term_setting(setting),
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
    if is_root_admin(user) and not is_root_admin(admin):
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
    process_academic_term_schedule(db)
    users = db.query(models.User).all()
    user_list = []
    
    for u in users:
        if is_root_admin(u) and not is_root_admin(admin):
            continue

        # 1. Handle permissions safely
        perms = parse_permissions(u.permissions)
        is_student_active = True if u.is_admin else student_has_portal_access(u)

        # 2. Append the formatted dictionary
        user_list.append({
            "id": u.id,
            "first_name": u.first_name or "",
            "middle_name": u.middle_name or "",
            "last_name": u.last_name or "",
            "full_name": u.full_name or "N/A",
            "student_no": u.student_no or "N/A",
            "email": u.email,
            "batch_id": u.batch_id or "",
            "department": u.department or "N/A",
            "course": u.course or "",
            "section": u.section or "",
            "level": u.level or "",
            "course_section": f"{u.course or ''} {u.section or ''}".strip() or "N/A",
            "profile_pic": deployed_static_path(u.profile_pic),
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "is_admin": u.is_admin,
            "is_archived": u.is_archived,
            "must_change_password": u.must_change_password,
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
    if activated_count > 0:
        create_admin_notification(
            db,
            f"{activated_count} student account(s) were activated for portal access.",
            "user_management_students",
            students[0].id if students else None,
            created_by_admin_id=current_admin.id
        )

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
    if deactivated_count > 0:
        create_admin_notification(
            db,
            f"{deactivated_count} student account(s) were deactivated for portal access.",
            "user_management_students",
            students[0].id if students else None,
            created_by_admin_id=current_admin.id
        )

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
    if is_root_admin(user) and not is_root_admin(current_admin):
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
        user.id,
        created_by_admin_id=current_admin.id
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
    create_admin_notification(
        db,
        f"{len(students)} student account(s) from batch {batch_id} were archived.",
        "user_management_students",
        students[0].id if students else None,
        created_by_admin_id=admin.id
    )

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
    create_admin_notification(
        db,
        f"{len(students)} student account(s) from batch {batch_id} were restored.",
        "user_management_students",
        students[0].id if students else None,
        created_by_admin_id=admin.id
    )

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
        sample_student_id = students[0].id if students else None
        for student in students:
            delete_user_and_related_records(db, student)
        db.commit()
        create_admin_notification(
            db,
            f"{count} archived student account(s) from batch {batch_id} were permanently deleted.",
            "user_management_students",
            sample_student_id,
            created_by_admin_id=admin.id
        )
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
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(check_permission("User-Management-Create"))
):
    students_list = data.get("students", []) or data.get("users", [])
    duplicate_action = str(data.get("duplicate_action", "ignore")).strip().lower()
    if duplicate_action not in {"ignore", "replace"}:
        duplicate_action = "ignore"

    if not isinstance(students_list, list) or len(students_list) == 0:
        raise HTTPException(status_code=400, detail="No users were provided for registration.")
    if len(students_list) > MAX_BULK_REGISTRATION_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"One bulk registration request can process up to {MAX_BULK_REGISTRATION_ROWS:,} users. Please split this upload."
        )

    term_setting = process_academic_term_schedule(db)
    if term_setting.current_status != "active":
        raise HTTPException(
            status_code=409,
            detail="The previous semester has ended and the next semester has not started yet."
        )
    automatic_batch_id = (
        f"BATCH-{term_setting.current_academic_year} {term_setting.current_semester}"
    )
    students_list = [
        {**student, "batch_id": automatic_batch_id}
        for student in students_list
        if isinstance(student, dict)
    ]
    if not students_list:
        raise HTTPException(status_code=400, detail="No valid users were provided for registration.")

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
async def approve_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
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
    db.flush()

    matched_lost_item = None
    if pending.matched_item_id:
        matched_lost_item = db.query(models.Item).filter(
            models.Item.id == pending.matched_item_id,
            models.Item.status == "lost",
            models.Item.archived == False
        ).first()

    if matched_lost_item:
        new_item.is_matched = True
        matched_lost_item.is_matched = True
        prepend_lost_possible_match(
            matched_lost_item,
            serialize_found_item_match(new_item, 0.55, previous_pending_id=pending.id)
        )
        claim = ensure_pending_claim_for_pair(
            db,
            lost_item=matched_lost_item,
            found_item=new_item,
            claimant_id=matched_lost_item.user_id or pending.user_id,
            similarity_score="Auto Match"
        )
        db.flush()
        create_admin_notification(
            db,
            f"Approved found item #{new_item.id} was linked to lost item #{matched_lost_item.id}.",
            "match",
            claim.id,
            f"/admin/Reports?report_type=claim&claim_id={claim.id}",
            created_by_admin_id=current_admin.id
        )

    # 3. Remove from pending
    db.delete(pending)
    db.commit()
    create_admin_notification(
        db,
        f"Pending item #{item_id} was approved and moved to active inventory.",
        "new_report",
        new_item.id,
        "/admin/Found_Items_Report",
        created_by_admin_id=current_admin.id
    )

    return {"status": "success", "message": "Item approved and moved to inventory"}



@router.post("/archive-pending/{pending_id}")
def archive_pending(
    pending_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    pending = db.query(models.PendingItem).filter(models.PendingItem.id == pending_id).first()
    if not pending:
        raise HTTPException(404, "Pending item not found")

    pending.archived = True # Just hide it
    pending.deleted = False
    db.commit()
    create_admin_notification(
        db,
        f"Pending item #{pending_id} was archived from the approval queue.",
        "new_report",
        pending_id,
        "/admin/Found_Items_Report",
        created_by_admin_id=getattr(admin, "id", None)
    )
    return {"message": "Item archived"}


@router.delete("/pending-items/{pending_id}/dispose")
def dispose_pending_item(
    pending_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin)
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
        create_admin_notification(
            db,
            f"Pending item #{pending_id} was disposed and moved to the hidden reference dataset.",
            "new_report",
            pending_id,
            "/admin/Found_Items_Report",
            created_by_admin_id=current_user.id
        )
        return {"status": "success", "message": "Pending item disposed"}
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not dispose pending item")

@router.post("/archive-found/{item_id}")
def archive_found_item(
    item_id: int, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(get_current_admin)
):
    # 1. Search in the Items table
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # 2. FIX: Change 'is_archived' to 'archived' to match your models.py
    item.archived = True 
    item.deleted = False
    db.commit()

    return {"status": "success", "message": "Item moved to archives"}


@router.post("/recover-pending/{pending_id}")
def recover_pending(
    pending_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin)
):
    pending = db.query(models.PendingItem).filter(models.PendingItem.id == pending_id).first()
    if pending:
        pending.archived = False
        pending.deleted = False
        db.commit()
        create_admin_notification(
            db,
            f"Pending item #{pending_id} was restored to the approval queue.",
            "new_report",
            pending_id,
            "/admin/Found_Items_Report",
            created_by_admin_id=current_user.id
        )
        return {"status": "success", "message": "Pending item restored to approval queue", "record_type": "pending"}

    # Fallback: if the UI thought this was pending but the archived record already lives
    # in the main found-items table, recover that item instead of hard-failing.
    item = db.query(models.Item).filter(models.Item.id == pending_id).first()
    if item:
        item.archived = False
        item.deleted = False
        db.commit()
        create_admin_notification(
            db,
            f"Archived found item #{pending_id} was restored to active inventory.",
            "new_report",
            pending_id,
            "/admin/Found_Items_Report",
            created_by_admin_id=current_user.id
        )
        return {"status": "success", "message": "Archived found item restored to active inventory", "record_type": "found"}

    raise HTTPException(status_code=404, detail="Pending item not found")

@router.put("/pending-items/{pending_id}/delete")
def move_pending_item_to_deleted(
    pending_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    pending = db.query(models.PendingItem).filter(models.PendingItem.id == pending_id).first()
    if not pending:
        raise HTTPException(status_code=404, detail="Pending item not found")
    pending.archived = True
    pending.deleted = True
    db.commit()
    return {"status": "success", "message": "Pending item moved to Deleted Items"}

@router.post("/recover-lost/{item_id}") # Change the path here
def recover_lost_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin)
):
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Report not found")

    item.archived = False # This is the "magic" line that restores it
    item.deleted = False
    db.commit()
    create_admin_notification(
        db,
        f"Lost report #{item_id} was restored to the active list.",
        "new_report",
        item_id,
        "/admin/Lost_Items_Report",
        created_by_admin_id=current_user.id
    )
    return {"status": "success", "message": "Lost report restored to active list"}

@router.post("/recover-found/{item_id}")
def recover_found_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin)
):
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.archived = False
    item.deleted = False
    db.commit()
    create_admin_notification(
        db,
        f"Found item #{item_id} was restored to active inventory.",
        "new_report",
        item_id,
        "/admin/Found_Items_Report",
        created_by_admin_id=current_user.id
    )
    return {"status": "success", "message": "Item restored to active inventory"}

@router.post("/reset-student-password")
async def reset_student_password(
    data: dict, 
    db: Session = Depends(get_db), 
    current_admin: models.User = Depends(check_permission("User-Management-Reset"))
):
    email = data.get("email")
    user = db.query(models.User).filter(models.User.email == email).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if is_root_admin(user) and not is_root_admin(current_admin):
        raise HTTPException(status_code=404, detail="User not found")

    # Keep student/faculty temp passwords predictable; admins without IDs get a secure random suffix.
    student_no = str(user.student_no or "").strip()
    new_temp = f"STI{student_no}" if student_no else "STI-" + str(uuid.uuid4())[:8]
    
    # 2. Hash the new password using bcrypt for security
    user.hashed_password = pwd_context.hash(new_temp)
    
    # 3. FORCE PASSWORD CHANGE: Set flag back to True (1)
    user.must_change_password = True
    
    db.commit()
    create_admin_notification(
        db,
        f"Password was reset for user {user.full_name or user.email}.",
        "user_management_students",
        user.id,
        created_by_admin_id=current_admin.id
    )
    
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
    report_owner_user_id: int = Form(None),
    report_owner_name: str = Form(None),
    report_owner_group: str = Form(None),
    brand: str = Form(None),
    color: str = Form(None),
    description: str = Form(None),
    location: str = Form(...),
    date: str = Form(None),
    time_found: str = Form(None),
    image_embedding: str = Form(None), 
    possible_matches: str = Form(None),
    ai_score: float = Form(0.0),       
    matched_item_id: int = Form(None), 
    db: Session = Depends(get_db),
    # 1. Add this dependency to get the logged-in user's info
    current_user: models.User = Depends(get_current_admin) 
):
    # 2. Save the file
    try:
        resolved_category = resolve_category_name(db, category_id=category_id, category_name=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    for upload, label in (
        (file, "Main image"),
        (extra_image_1, "Optional image 2"),
        (extra_image_2, "Optional image 3"),
    ):
        try:
            validate_upload_file_size(upload, label=label)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    saved_possible_matches = normalize_saved_possible_matches(possible_matches)
    report_owner_user = None
    if report_owner_user_id:
        report_owner_user = db.query(models.User).filter(
            models.User.id == report_owner_user_id,
            models.User.is_admin == False,
            models.User.is_archived == False,
        ).first()
    if not report_owner_user:
        raise HTTPException(status_code=400, detail="Please select an existing student or faculty record for this lost item.")

    owner_name = format_user_display_name(report_owner_user, "Unknown User")
    owner_group = (
        (report_owner_user.section or "").strip()
        or (report_owner_user.course or "").strip()
        or ("Teacher" if user_is_faculty_account(report_owner_user) else "")
        or (report_owner_group or "").strip()
        or None
    )

    new_item = models.Item(
        status="lost",
        category_id=category_id,
        category=category,
        department=department,
        report_owner_user_id=report_owner_user.id,
        report_owner_name=owner_name,
        report_owner_group=owner_group,
        user_id=current_user.id,  # <--- SETS THE UPLOADER RECORD
        description=f"[{item_name}] {description}" if description else item_name,
        brand=brand,
        color=color,
        location=location,
        image_path=saved_path, 
        image_embedding=normalized_image_embedding, 
        possible_matches=saved_possible_matches,
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
            target_url="/admin/Lost_Items_Report",
            created_by_admin_id=current_user.id
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
    current_user: models.User = Depends(get_current_admin) 
):
    # 2. Save the file
    try:
        resolved_category = resolve_category_name(db, category_id=category_id, category_name=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    for upload, label in (
        (file, "Main image"),
        (extra_image_1, "Optional image 2"),
        (extra_image_2, "Optional image 3"),
    ):
        try:
            validate_upload_file_size(upload, label=label)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
                prepend_lost_possible_match(
                    lost_item,
                    serialize_found_item_match(new_item, ai_score)
                )
                ensure_pending_claim_for_pair(
                    db,
                    lost_item=lost_item,
                    found_item=new_item,
                    claimant_id=lost_item.user_id or new_item.user_id or current_user.id,
                    similarity_score=f"{ai_score * 100:.1f}%"
                )
                if lost_item.user_id:
                    create_student_notification(
                        db,
                        lost_item.user_id,
                        f"Possible match found: {current_user.full_name} registered a found {category} that may match your lost item.",
                        "student_match",
                        f"/student/Lost-report?item_id={lost_item.id}&show_match=1"
                    )

        db.commit()
        db.refresh(new_item)

        # 7. Notification
        notify_admin(
            db,
            f"Admin {current_user.full_name} reported: {item_name}",
            related_id=new_item.id,
            target_url="/admin/Found_Items_Report",
            created_by_admin_id=current_user.id
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
    current_user: models.User = Depends(get_current_admin)
):
    # 1. Find the item
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # 2. Update the status
    item.archived = True
    item.deleted = False
    
    try:
        db.commit()
        # Optional: Log who archived it
        print(f"Admin {current_user.full_name} archived item {item_id}")
        return {"status": "success", "message": "Item moved to archive"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not archive item")

@router.put("/items/{item_id}/delete")
async def move_item_to_deleted(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.archived = True
    item.deleted = True
    db.commit()
    return {"status": "success", "message": "Item moved to Deleted Items"}

@router.delete("/items/{item_id}/dispose")
async def dispose_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin)
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
async def get_stats(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    return {
        "welcome": f"Hello {current_admin.email}",
        "pending_count": db.query(models.PendingItem.id).filter(
            models.PendingItem.archived == False
        ).count(),
        "found_count": db.query(models.Item.id).filter(
            models.Item.status == "found",
            models.Item.archived == False
        ).count(),
        "approved_claim_count": db.query(models.Claim.id).filter(
            models.Claim.status == "approved"
        ).count(),
    }


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
    current_admin: models.User = Depends(get_current_admin),
    limit: int = 50,
):
    limit = max(1, min(limit, 100))
    notifications = db.query(models.Notification)\
        .filter(
            ~models.Notification.type.in_(["chat", "student_match", "student_update"]),
            or_(
                models.Notification.created_by_admin_id == None,
                models.Notification.created_by_admin_id == current_admin.id
            )
        )\
        .order_by(models.Notification.created_at.desc())\
        .limit(limit)\
        .all()
    
    return notifications

@router.get("/notifications/unread-count")
def get_notification_unread_count(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    unread_count = db.query(models.Notification).filter(
        ~models.Notification.type.in_(["chat", "student_match", "student_update"]),
        or_(
            models.Notification.created_by_admin_id == None,
            models.Notification.created_by_admin_id == current_admin.id
        ),
        models.Notification.is_read == False
    ).count()
    return {"unread_count": unread_count}

@router.post("/notifications/{notif_id}/read")
def mark_read(
    notif_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    notif = db.query(models.Notification).filter(
        models.Notification.id == notif_id,
        ~models.Notification.type.in_(["chat", "student_match", "student_update"]),
        or_(
            models.Notification.created_by_admin_id == None,
            models.Notification.created_by_admin_id == current_admin.id
        )
    ).first()
    if notif:
        notif.is_read = True
        db.commit()
    return {"status": "success"}

@router.post("/notifications/mark-all-read")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    db.query(models.Notification).filter(
        ~models.Notification.type.in_(["chat", "student_match", "student_update"]),
        or_(
            models.Notification.created_by_admin_id == None,
            models.Notification.created_by_admin_id == current_admin.id
        ),
        models.Notification.is_read == False
    ).update({models.Notification.is_read: True}, synchronize_session=False)
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
    create_admin_notification(
        db,
        f"{user.full_name or user.email} updated admin settings.",
        "user_management_admin",
        user.id,
        "/admin/Settings",
        created_by_admin_id=current_admin.id
    )
    return {"status": "success", "message": "Settings applied across system"}


@router.post("/create-announcement")
async def create_announcement(
    title: str = Form(...),
    content: str = Form(...),
    file: UploadFile = File(...), # Changed from 'image' to 'file'
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
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
    announcement_id = current_post.id if current_post else new_post.id
    announcement_title = current_post.title if current_post else new_post.title
    create_admin_notification(
        db,
        f"Announcement '{announcement_title}' was updated in Content Management.",
        "new_report",
        announcement_id,
        "/admin/Content-management",
        created_by_admin_id=current_admin.id
    )
    
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
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
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
    create_admin_notification(
        db,
        f"Confiscated item #{new_item.id} was created.",
        "confiscated_items",
        new_item.id,
        "/admin/Confiscated-items",
        created_by_admin_id=current_admin.id,
    )
    
    return {"message": "Success", "id": new_item.id}

@router.get("/get-confiscated-items")
async def get_confiscated_items(
    view: str = "active",
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    query = db.query(models.ConfiscatedItem)
    if view == "disposal":
        query = query.filter(models.ConfiscatedItem.disposal_status == "for_disposal")
    elif view == "disposed":
        query = query.filter(models.ConfiscatedItem.disposal_status == "disposed")
    else:
        query = query.filter(models.ConfiscatedItem.disposal_status == "active")
    items = query.order_by(models.ConfiscatedItem.created_at.desc()).all()
    return items


@router.put("/confiscated/{item_id}/disposal")
def update_confiscated_disposal(
    item_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    item = db.query(models.ConfiscatedItem).filter(models.ConfiscatedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Confiscated item not found")
    action = str(payload.get("action") or "").strip().lower()
    statuses = {
        "schedule": "for_disposal",
        "cancel": "active",
        "complete": "disposed",
    }
    if action not in statuses:
        raise HTTPException(status_code=400, detail="Invalid disposal action")
    item.disposal_status = statuses[action]
    item.disposal_note = str(payload.get("note") or "").strip()[:500] or None
    item.disposal_updated_at = datetime.utcnow()
    db.commit()
    labels = {
        "schedule": "marked for disposal",
        "cancel": "returned to confiscated items",
        "complete": "recorded as disposed",
    }
    create_admin_notification(
        db,
        f"Confiscated item #{item_id} was {labels[action]}.",
        "confiscated_disposal",
        item_id,
        "/admin/Confiscated-items?view=disposal",
        created_by_admin_id=current_admin.id,
    )
    return {"message": f"Item {labels[action]}", "status": item.disposal_status}


@router.get("/audit-logs")
def get_audit_logs(
    search: str = "",
    limit: int = 200,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    limit = max(1, min(limit, 500))
    query = db.query(models.Notification).filter(
        models.Notification.created_by_admin_id.isnot(None)
    )
    if search.strip():
        query = query.filter(models.Notification.message.ilike(f"%{search.strip()}%"))
    logs = query.order_by(models.Notification.created_at.desc()).limit(limit).all()
    admin_ids = {log.created_by_admin_id for log in logs if log.created_by_admin_id}
    admins = {
        user.id: user
        for user in db.query(models.User).filter(models.User.id.in_(admin_ids)).all()
    } if admin_ids else {}
    return [{
        "id": log.id,
        "admin": format_user_display_name(admins.get(log.created_by_admin_id), "Unknown admin"),
        "action": log.message,
        "module": (log.type or "system").replace("_", " ").title(),
        "target_url": log.target_url,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    } for log in logs]


@router.get("/get-confiscated-item/{item_id}")
async def get_confiscated_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
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
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
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
    create_admin_notification(
        db,
        f"Confiscated item #{item_id} was updated.",
        "confiscated_items",
        item_id,
        "/admin/Confiscated-items",
        created_by_admin_id=current_admin.id,
    )
    return {"message": "Confiscated item updated", "item": item}


@router.delete("/delete-confiscated/{item_id}")
async def delete_confiscated_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    item = db.query(models.ConfiscatedItem).filter(models.ConfiscatedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Confiscated item not found")

    item_label = item.category or f"Item #{item_id}"
    db.delete(item)
    db.commit()
    create_admin_notification(
        db,
        f"Confiscated item '{item_label}' was permanently deleted.",
        "confiscated_items",
        item_id,
        "/admin/Confiscated-items",
        created_by_admin_id=current_admin.id,
    )
    return {"message": "Confiscated item deleted"}
