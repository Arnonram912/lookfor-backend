from fastapi import APIRouter, Request, Response, UploadFile, File, Form, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import models
from database import get_db
from security import get_current_user
from fastapi import HTTPException
import os
import shutil
import io
from datetime import datetime
import uuid
from clip_test import get_clip_components
from PIL import Image
import torch
import numpy as np
import json
from utils import save_file, resolve_category_name, validate_upload_file_size
from clip_test import get_text_embedding, get_image_embedding, get_multi_image_embedding
from models import SettingsUpdate


router = APIRouter(prefix="/student", tags=["Student"])
templates = Jinja2Templates(directory="templates")
STUDENT_ACCESS_PERMISSION = "Student-Portal-Access"

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def parse_permissions(raw_permissions) -> list[str]:
    try:
        if isinstance(raw_permissions, str):
            return json.loads(raw_permissions)
        return raw_permissions or []
    except Exception:
        return []


def get_active_student_user(
    current_user: models.User = Depends(get_current_user)
):
    if current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admins cannot access student actions")

    permissions = parse_permissions(current_user.permissions)
    if STUDENT_ACCESS_PERMISSION not in permissions:
        raise HTTPException(
            status_code=403,
            detail="Your student account is still deactivated. Please wait for admin activation."
        )

    return current_user


def create_student_notification(
    db: Session,
    user_id: int,
    message: str,
    notif_type: str = "student_match",
    target_url: str | None = None
):
    if target_url is None:
        if notif_type == "chat":
            target_url = "/student/Messages"
        elif notif_type in {"student_match", "student_update"}:
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
            "image_path": match.get("image_path"),
            "brand": match.get("brand"),
            "color": match.get("color"),
            "description": match.get("description"),
        })

    return json.dumps(cleaned_matches) if cleaned_matches else None


def ensure_student_claim_for_pair(
    db: Session,
    lost_item: models.Item,
    found_item: models.Item,
    claimant_id: int,
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
        status="pending",
        similarity_score=similarity_score
    )
    db.add(new_claim)
    db.flush()
    return new_claim


@router.get("/notifications")
async def get_student_notifications(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user)
):
    notifications = db.query(models.Notification).filter(
        or_(
            and_(models.Notification.type == "chat", models.Notification.related_id == current_user.id),
            and_(models.Notification.type.in_(["student_match", "student_update"]), models.Notification.related_id == current_user.id)
        )
    ).order_by(models.Notification.created_at.desc()).limit(10).all()

    return notifications


@router.get("/notifications/unread-count")
async def get_student_notification_unread_count(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user)
):
    unread_count = db.query(models.Notification).filter(
        or_(
            and_(models.Notification.type == "chat", models.Notification.related_id == current_user.id),
            and_(models.Notification.type.in_(["student_match", "student_update"]), models.Notification.related_id == current_user.id)
        ),
        models.Notification.is_read == False
    ).count()

    return {"unread_count": unread_count}


@router.post("/notifications/{notif_id}/read")
async def mark_student_notification_read(
    notif_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user)
):
    notif = db.query(models.Notification).filter(models.Notification.id == notif_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    is_owned_student_notif = notif.related_id == current_user.id and notif.type in {"chat", "student_match", "student_update"}
    if not is_owned_student_notif:
        raise HTTPException(status_code=403, detail="You do not have access to this notification")

    notif.is_read = True
    db.commit()
    return {"status": "success"}

@router.post("/found")
async def report_found_item(
    item_name: str = Form(...), # Added this to match your JS
    category_id: int = Form(None),
    category: str = Form(...),
    brand: str = Form(None),    # NEW: Brand
    color: str = Form(None),    # NEW: Color
    description: str = Form(None),
    location: str = Form(...),
    date: str = Form(None),
    time: str = Form(None),
    time_found: str = Form(None),
    image: UploadFile = File(...),
    extra_image_1: UploadFile = File(None),
    extra_image_2: UploadFile = File(None),
    image_embedding: str = Form(None),
    matched_item_id: int = Form(None),
    ai_score: float = Form(0.0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user)
):
    # 2. Image Handling
    allowed_types = ["image/jpeg", "image/png", "image/jpg", "image/webp"]
    if image.content_type not in allowed_types:
        raise HTTPException(400, detail="Invalid image type")

    for upload, label in (
        (image, "Main image"),
        (extra_image_1, "Optional image 2"),
        (extra_image_2, "Optional image 3"),
    ):
        try:
            validate_upload_file_size(upload, label=label)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        resolved_category = resolve_category_name(db, category_id=category_id, category_name=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    query_images = []
    for upload in (image, extra_image_1, extra_image_2):
        if not upload or not upload.filename:
            continue
        if upload.content_type not in allowed_types:
            raise HTTPException(400, detail="Invalid image type")

        image_bytes = await upload.read()
        await upload.seek(0)
        if not image_bytes:
            continue

        try:
            query_images.append(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="One of the uploaded images is invalid.") from exc

    db_path = save_file(image, resolved_category)
    parsed_date = None
    if date and date.strip():
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date format. Please use YYYY-MM-DD.") from exc

    is_auto_match = ai_score >= 0.55 and matched_item_id is not None
    computed_embedding = image_embedding or ""
    if query_images:
        computed_embedding = json.dumps(get_multi_image_embedding(query_images).tolist())

    resolved_time_found = (time_found or time or "").strip() or None

    # 3. SAVE TO PENDING TABLE
    pending_item = models.PendingItem(
        item_name=item_name,    # Added
        category=category,
        brand=brand,            # NEW: Saved here
        color=color,            # NEW: Saved here
        description=description,
        location=location,
        date=parsed_date,
        time_found=resolved_time_found,
        image_path=db_path,
        image_embedding=computed_embedding,
        matched_item_id=matched_item_id,
        user_id=current_user.id,
        created_at=datetime.utcnow(),
        archived=False
    )

    db.add(pending_item)
    db.flush()

    matched_lost_item = None
    if is_auto_match:
        matched_lost_item = db.query(models.Item).filter(
            models.Item.id == matched_item_id,
            models.Item.status == "lost"
        ).first()
        if matched_lost_item:
            admin_match_score = f"{ai_score * 100:.1f}%"
            db.add(models.Notification(
                message=f"AI MATCH ({admin_match_score}): Found {category} may match Lost Item #{matched_item_id}.",
                type="match",
                related_id=pending_item.id,
                target_url="/admin/Found_Items_Report",
                is_read=False,
                created_at=datetime.utcnow()
            ))

            if matched_lost_item.user_id and matched_lost_item.user_id != current_user.id:
                reporter_name = current_user.full_name or current_user.email or "A student"
                create_student_notification(
                    db,
                    matched_lost_item.user_id,
                    f"Possible match found: {reporter_name} submitted a found {category} that may match your lost item.",
                    "student_match"
                )
    else:
        db.add(models.Notification(
            message=f"New Found Report: {category} ({item_name}) submitted by {current_user.full_name or current_user.email}.",
            type="new_report",
            related_id=pending_item.id,
            target_url="/admin/Found_Items_Report",
            is_read=False,
            created_at=datetime.utcnow()
        ))

    db.commit()
    db.refresh(pending_item)

    return {
        "message": "Item reported successfully",
        "item_id": pending_item.id,
        "status": "pending_approval",
        "is_matched": False,
        "has_possible_match": bool(matched_lost_item)
    }

# Create a dedicated route for students
@router.post("/update-profile")
async def update_student_profile(
    full_name: str = Form(None),
    student_no: str = Form(None),
    course: str = Form(None),
    section: str = Form(None),
    profile_img: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user) 
):
    user = current_user
    
    if not user:
        return {"error": "User not found"}

    # Handle Image Upload
    if profile_img and profile_img.filename:
        os.makedirs("static/profile_pics", exist_ok=True)
        file_extension = os.path.splitext(profile_img.filename)[1]
        file_path = f"static/profile_pics/student_{user.id}{file_extension}"
        
        with open(file_path, "wb") as buffer:
            buffer.write(await profile_img.read())
        
        user.profile_pic = file_path

    # Update Student-Specific Fields
    user.full_name = full_name
    user.student_no = student_no
    user.course = course
    user.section = section

    db.commit()
    create_student_notification(
        db,
        user.id,
        "Your student profile was updated successfully.",
        "student_update",
        "/student/profile"
    )
    db.commit()
    return {"message": "Student profile updated successfully"}

@router.get("/dashboard")
def Student_dashboard(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    # REMOVED "admin": current_admin from the dictionary below
    return templates.TemplateResponse(
        "student2.0.html",
        {"request": request} 
    )

@router.get("/Messages")
def Student_messages(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return templates.TemplateResponse(
        "Student Pages/Student_Messages.html",
        {"request": request} 
    )
@router.get("/Lost-report")
def report_lost_item(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return templates.TemplateResponse(
        "Student Pages/Student_LostReport.html",
        {"request": request} 
    )
@router.get("/Found-report")
def report_found_item(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return templates.TemplateResponse(
        "Student Pages/Student_FoundReport.html",
        {"request": request} 
    )

@router.get("/profile")
def view_profile(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return templates.TemplateResponse(
        "Student Pages/Student_Profile.html",
        {"request": request} 
    )

@router.get("/settings")
def view_settings(
    request: Request,
    response: Response
):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return templates.TemplateResponse(
        "Student Pages/Student_Settings.html",
        {"request": request} 
    )


@router.post("/update-settings")
async def update_student_settings(
    data: SettingsUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user),
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.two_factor_enabled = bool(data.two_factor)
    user.push_notifications = bool(data.notifications)
    user.theme_mode = (data.theme or "light")[:20]
    user.font_size = max(12, min(24, int(data.font_size)))
    db.commit()
    create_student_notification(
        db,
        user.id,
        "Your student settings were updated successfully.",
        "student_update",
        "/student/settings"
    )
    db.commit()

    return {"status": "success", "message": "Student settings updated successfully"}


# ... (your existing imports)
@router.get("/items/found/me")
async def get_my_found_items(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user)
):
    pending = db.query(models.PendingItem).filter(
        models.PendingItem.user_id == current_user.id
    ).all()
    
    approved = db.query(models.Item).filter(
        models.Item.user_id == current_user.id,
        models.Item.status == "found"
    ).all()

    results = []
    
    for p in pending:
        results.append({
            "display_status": "Pending Approval",
            "data": {
                "id": p.id,
                "item_name": p.item_name,
                "category": p.category,
                "brand": p.brand,
                "color": p.color,
                "location": p.location,
                "image_path": p.image_path,
                "description": p.description,
                "date": p.date,
                "time_found": p.time_found,
                "uploader_name": current_user.full_name
            }
        })
        
    for a in approved:
        display_status = "Matched" if a.is_matched else "Approved"
        results.append({
            "display_status": display_status,
            "data": {
                "id": a.id,
                "item_name": a.category,
                "category": a.category,
                "brand": a.brand,
                "color": a.color,
                "location": a.location,
                "image_path": a.image_path,
                "description": a.description,
                "date": a.date,
                "time_found": a.time_found,
                "uploader_name": current_user.full_name,
                "is_matched": bool(a.is_matched)
            }
        })
        
    return results
@router.post("/items/lost/report")
async def submit_user_lost_report(
    item_name: str = Form(...),
    category: str = Form(...),
    category_id: int = Form(...),
    location: str = Form(...),
    description: str = Form(None),
    brand: str = Form(None),
    color: str = Form(None),
    date: str = Form(None),
    image: UploadFile = File(None),
    extra_image_1: UploadFile = File(None),
    extra_image_2: UploadFile = File(None),
    image_embedding: str = Form(None), # Embedding from frontend AI call
    possible_matches: str = Form(None),
    matched_item_id: int = Form(None), # Found ID if user confirmed a match
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user)
):
    # 1. Handle the image upload using your save_file helper
    saved_path = None
    query_images = []

    for upload, label in (
        (image, "Main image"),
        (extra_image_1, "Optional image 2"),
        (extra_image_2, "Optional image 3"),
    ):
        try:
            validate_upload_file_size(upload, label=label)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if image and image.filename:
        image_bytes = await image.read()
        await image.seek(0)
        if image_bytes:
            try:
                query_images.append(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Invalid primary image upload.") from exc

        try:
            resolved_category = resolve_category_name(db, category_id=category_id, category_name=category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        saved_path = save_file(image, resolved_category)

    for extra_upload in (extra_image_1, extra_image_2):
        if not extra_upload or not extra_upload.filename:
            continue
        extra_bytes = await extra_upload.read()
        await extra_upload.seek(0)
        if not extra_bytes:
            continue
        try:
            query_images.append(Image.open(io.BytesIO(extra_bytes)).convert("RGB"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="One of the optional images is invalid.") from exc

    computed_embedding = image_embedding or ""
    if query_images:
        computed_embedding = json.dumps(get_multi_image_embedding(query_images).tolist())

    # 2. Date Parsing
    parsed_date = None
    if date and date.strip():
        try:
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            parsed_date = None

    # 3. Create the Item Record
    saved_possible_matches = normalize_saved_possible_matches(possible_matches)

    is_auto_match = matched_item_id is not None

    new_report = models.Item(
        status="lost",
        category_id=category_id,
        category=category,
        brand=brand,
        color=color,
        description=description,
        location=location,
        image_path=saved_path,
        image_embedding=computed_embedding,
        possible_matches=saved_possible_matches,
        user_id=current_user.id,
        date=parsed_date,
        is_matched=is_auto_match,
        department=None, # Explicitly no department for student reports
        is_surrendered=False, # Students keep their lost item (it's lost!)
        created_at=datetime.utcnow()
    )

    try:
        db.add(new_report)
        db.flush() # Generate new_report.id for relationships

        # 4. Handle possible match and notification logic
        if matched_item_id:
            if not current_user.student_no:
                raise HTTPException(
                    status_code=400,
                    detail="Your account does not have a student number yet. Please update your profile or contact an admin before claiming an item."
                )

            found_item = db.query(models.Item).filter(models.Item.id == matched_item_id).first()
            if not found_item or found_item.status != "found" or found_item.archived:
                raise HTTPException(status_code=404, detail="Selected possible match is no longer available.")

            new_report.is_matched = True
            found_item.is_matched = True
            new_claim = ensure_student_claim_for_pair(
                db,
                lost_item=new_report,
                found_item=found_item,
                claimant_id=current_user.id
            )

            # Notification for Admin (Match)
            notif = models.Notification(
                message=f"Possible AI match: {current_user.full_name} reported a lost item that may match Item #{matched_item_id}",
                type="match",
                related_id=new_claim.id,
                target_url=f"/admin/Reports?report_type=claim&claim_id={new_claim.id}",
                is_read=False
            )
            db.add(notif)
        else:
            # Notification for Admin (New General Report)
            notif = models.Notification(
                message=f"New Lost Report: {category} ({item_name}) from {current_user.full_name}",
                type="new_report",
                related_id=new_report.id,
                target_url="/admin/Lost_Items_Report",
                is_read=False
            )
            db.add(notif)

        db.commit()
        db.refresh(new_report)
        
        return {
            "status": "success", 
            "item_id": new_report.id,
            "is_matched": bool(new_report.is_matched),
            "has_possible_match": bool(matched_item_id)
        }

    except Exception as e:
        db.rollback()
        print(f"Database Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit report")
@router.get("/api/items/lost/me")
async def get_my_lost_reports(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_active_student_user)
):
    # Change 'LostItem' to 'Item' to match your models.py
    reports = db.query(models.Item).filter(
        models.Item.user_id == current_user.id,
        models.Item.status == "lost",
        models.Item.archived == 0
    ).all()
    
    return reports

# --- Your existing page routes below ---

@router.get("/Lost-report")
def report_lost_item(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return templates.TemplateResponse("Student Pages/Student_LostReport.html", {"request": request})

# ... (rest of your routes)
