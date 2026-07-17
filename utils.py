import os
import re
import io
from uuid import uuid4
from urllib.parse import quote
from sqlalchemy import func
from sqlalchemy.orm import Session
import models

# CHANGE THIS: Point it inside the static directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_AZURE_APP_SERVICE = bool(
    os.getenv("WEBSITE_SITE_NAME") or os.getenv("WEBSITE_INSTANCE_ID")
)
DEFAULT_UPLOAD_FOLDER = (
    os.path.join(os.sep, "home", "data", "uploads")
    if IS_AZURE_APP_SERVICE
    else os.path.join(BASE_DIR, "static", "uploads")
)
UPLOAD_FOLDER = os.path.abspath(
    os.getenv("UPLOAD_FOLDER", "").strip()
    or DEFAULT_UPLOAD_FOLDER
)
UPLOAD_URL_PREFIX = "/uploads"
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
    original_name = os.path.basename(file.filename or "upload.bin")
    filename = f"{uuid4()}_{original_name}"
    file_bytes = file.file.read()

    cloudinary_url = upload_to_cloudinary_if_configured(
        file_bytes=file_bytes,
        filename=filename,
        category_folder=category_folder,
    )
    if cloudinary_url:
        return cloudinary_url

    target_folder = os.path.join(UPLOAD_FOLDER, category_folder)
    os.makedirs(target_folder, exist_ok=True)

    # This is the physical path on your computer/server
    file_path = os.path.join(target_folder, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(file_bytes)

    # Store a public URL rather than a container filesystem path. The mounted
    # upload directory may live outside /app (for example /home on Azure).
    return f"{UPLOAD_URL_PREFIX}/{category_folder}/{filename}"


def upload_to_cloudinary_if_configured(file_bytes: bytes, filename: str, category_folder: str) -> str | None:
    storage_provider = os.getenv("IMAGE_STORAGE_PROVIDER", "").strip().lower()
    has_cloudinary_credentials = bool(
        os.getenv("CLOUDINARY_URL")
        or (
            os.getenv("CLOUDINARY_CLOUD_NAME")
            and os.getenv("CLOUDINARY_API_KEY")
            and os.getenv("CLOUDINARY_API_SECRET")
        )
    )

    if storage_provider not in {"cloudinary", ""} or not has_cloudinary_credentials:
        return None

    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError as exc:
        raise RuntimeError("Cloudinary storage is configured, but the cloudinary package is not installed.") from exc

    if not os.getenv("CLOUDINARY_URL"):
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
            secure=True,
        )

    public_id = os.path.splitext(filename)[0]
    upload_result = cloudinary.uploader.upload(
        io.BytesIO(file_bytes),
        folder=f"lookfor/{category_folder}",
        public_id=public_id,
        resource_type="image",
        overwrite=False,
    )

    return upload_result.get("secure_url") or upload_result.get("url")


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


def format_user_display_name(user: models.User | None, fallback: str = "Unknown User") -> str:
    if not user:
        return fallback

    full_name = str(getattr(user, "full_name", "") or "").strip()
    if full_name:
        return full_name

    name_parts = [
        getattr(user, "first_name", None),
        getattr(user, "middle_name", None),
        getattr(user, "last_name", None),
    ]
    built_name = " ".join(str(part).strip() for part in name_parts if part and str(part).strip())
    if built_name:
        return built_name

    return fallback


def format_item_code(status: str | None, item_id: int | None, existing_code: str | None = None) -> str | None:
    if existing_code:
        return existing_code
    if item_id is None:
        return None

    normalized_status = str(status or "").strip().lower()
    if normalized_status == "lost":
        prefix = "LOST"
    elif normalized_status == "found":
        prefix = "FOUND"
    elif normalized_status in {"pending_found", "pending"}:
        prefix = "PENDING-FOUND"
    else:
        prefix = "ITEM"

    return f"{prefix}-{int(item_id):06d}"


def item_display_id(item: models.Item) -> int | None:
    return getattr(item, "item_id", None) or getattr(item, "id", None)


def item_display_code(item: models.Item) -> str | None:
    return format_item_code(
        getattr(item, "status", None),
        item_display_id(item),
        getattr(item, "item_code", None),
    )


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
