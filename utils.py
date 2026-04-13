import os
import re
from uuid import uuid4
from sqlalchemy import func
from sqlalchemy.orm import Session
import models

# CHANGE THIS: Point it inside the static directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join("static", "uploads") 

# Create folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def sanitize_upload_category(category: str | None) -> str:
    normalized = str(category or "").strip().lower()
    if not normalized:
        return "uncategorized"

    normalized = normalized.replace("&", "and")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    return normalized or "uncategorized"


def resolve_category_name(
    db: Session,
    category_id: int | None = None,
    category_name: str | None = None
) -> str:
    category = None

    if category_id is not None:
        category = db.query(models.Category).filter(models.Category.id == category_id).first()
    elif category_name:
        normalized_name = str(category_name).strip().lower()
        category = db.query(models.Category).filter(
            func.lower(models.Category.name) == normalized_name
        ).first()

    if not category or not category.name or not str(category.name).strip():
        raise ValueError("Selected category was not found in the categories table.")

    return str(category.name).strip()


def save_file(file, category: str | None = None):
    category_folder = sanitize_upload_category(category)
    target_folder = os.path.join(UPLOAD_FOLDER, category_folder)
    os.makedirs(target_folder, exist_ok=True)

    original_name = os.path.basename(file.filename or "upload.bin")
    filename = f"{uuid4()}_{original_name}"

    # This is the physical path on your computer/server
    file_path = os.path.join(target_folder, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(file.file.read())

    # IMPORTANT: Return the path starting with 'static/' 
    # so the database stores a URL the browser can understand.
    return file_path.replace("\\", "/")


def notify_admin(db: Session, message: str, notif_type: str = "MATCH_ALERT", related_id: int = None):
    new_notif = models.Notification(
        message=message,
        type=notif_type,
        related_id=related_id
    )
    db.add(new_notif)
    db.commit()
