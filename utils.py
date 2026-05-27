import os
import re
from uuid import uuid4
from urllib.parse import quote
from sqlalchemy import func
from sqlalchemy.orm import Session
import models

# CHANGE THIS: Point it inside the static directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join("static", "uploads") 
MAX_REPORT_IMAGE_BYTES = 5 * 1024 * 1024

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


def public_file_url(path: str | None, fallback: str | None = None) -> str | None:
    raw_path = str(path or "").strip().split("?", 1)[0]
    if not raw_path:
        return fallback

    if raw_path.startswith(("http://", "https://", "//")):
        return raw_path

    normalized_path = raw_path.replace("\\", "/")
    if normalized_path.startswith("/"):
        return quote(normalized_path, safe="/%")

    return "/" + quote(normalized_path, safe="/%")


def validate_upload_file_size(file, max_bytes: int = MAX_REPORT_IMAGE_BYTES, label: str = "Image"):
    if not file or not getattr(file, "filename", None):
        return

    stream = getattr(file, "file", None)
    if stream is None:
        return

    current_position = stream.tell()
    stream.seek(0, os.SEEK_END)
    file_size = stream.tell()
    stream.seek(current_position)

    if file_size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise ValueError(f"{label} must be 5 MB or smaller.")


def notify_admin(db: Session, message: str, notif_type: str = "MATCH_ALERT", related_id: int = None):
    new_notif = models.Notification(
        message=message,
        type=notif_type,
        related_id=related_id
    )
    db.add(new_notif)
    db.commit()
