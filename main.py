import os, shutil, json, time, numpy as np, io
import asyncio
import sys
import smtplib
from datetime import datetime, timedelta, date
from typing import List
from email.message import EmailMessage
from PIL import Image
from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException, status, Header, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload, load_only
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv
import secrets
import string
import bcrypt 
import uuid
from uuid import uuid4
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
import models  # This is already there
from database import engine, get_db
from utils import UPLOAD_FOLDER, public_file_url, save_file, resolve_category_name, validate_upload_file_size, format_item_code
from sqlalchemy import and_, or_, func
from sqlalchemy import text
from clip_test import (
    get_similarity_score,
    find_matches_in_dataset,
    get_text_embedding,
    get_image_embedding,
    get_multi_image_embedding,
    get_clip_components
)
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from admin_messages import router as admin_messages_router
from admin_routes import ADMIN_PERMISSION_KEYS, ROOT_ADMIN_EMAIL, router as admin_router, create_admin_notification, process_academic_term_schedule
from student_routes import router as student_router
from security import (
    pwd_context,
    create_access_token,
    get_current_user,
    get_current_admin,
    verify_password,
    get_password_hash,
    get_login_email_candidates,
)

if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load environment variables from .env file
load_dotenv()

# --- 2. DATABASE & APP INITIALIZATION ---
models.Base.metadata.create_all(bind=engine)


app = FastAPI(title="LookFor Admin Dashboard")

app.include_router(admin_router)
app.include_router(student_router)
app.include_router(admin_messages_router)



pending_items = []
main_items = []
archive_items = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
STATIC_UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
STATIC_PROFILE_PICS_DIR = os.path.join(STATIC_DIR, "profile_pics")
DEFAULT_PROFILE_PIC = "static/photos/default-student-avatar.jpg"

os.makedirs(STATIC_UPLOADS_DIR, exist_ok=True)
os.makedirs(STATIC_PROFILE_PICS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=STATIC_UPLOADS_DIR), name="uploads")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
# This makes sure we always use the SAME folder at the very top of your project
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads") # No "static/" prefix here

os.makedirs(UPLOAD_DIR, exist_ok=True)

PAGE_ALIASES = {
    "/": {
        "alias": "a26e5a70-842d-5491-9b8c-b61a8ca8b966",
        "template": "landing.html",
        "label": "Landing",
    },
    "/login": {
        "alias": "4a2eaf02-397b-5056-9df5-79abe6c14b94",
        "template": "index.html",
        "label": "Login",
    },
    "/explore": {
        "alias": "a5908eca-4f65-54c8-bdfb-78722c278680",
        "template": "explorefeature.html",
        "label": "Explore",
    },
    "/about": {
        "alias": "6384a023-7141-53be-867e-37b9fd08a7e6",
        "template": "aboutlookfor.html",
        "label": "About",
    },
    "/admin/dashboard": {
        "alias": "e93ae889-11fa-5e89-9bda-0083b7f07538",
        "template": "admin.20.html",
        "label": "Admin Dashboard",
        "no_store": True,
    },
    "/admin/User-Management": {
        "alias": "6e1f2095-4d3c-5a1b-b77b-0a476a2d3740",
        "template": "Admin Pages/User_Management.html",
        "label": "User Management",
    },
    "/admin/Messages": {
        "alias": "073de3ca-5067-553d-90ba-9033ea9be665",
        "template": "Admin Pages/Admin_Message.html",
        "label": "Admin Messages",
    },
    "/admin/Lost_Items_Report": {
        "alias": "6a12cb4b-be2c-83ec-ae4b-671169ad8496",
        "template": "Admin Pages/Lost_item_Report.html",
        "label": "Lost Items Report",
    },
    "/admin/Found_Items_Report": {
        "alias": "f63b7f52-4bb0-5d24-8a09-80b3d1f77db2",
        "template": "Admin Pages/Found_item_Report.html",
        "label": "Found Items",
    },
    "/admin/Claim-Management": {
        "alias": "f97a07ee-7138-519e-8e81-c077ced9ee0a",
        "template": "Admin Pages/Claim_Management.html",
        "label": "Claim Management",
    },
    "/admin/Reports": {
        "alias": "8c2dc56e-79ae-5939-890e-315c8a959b32",
        "template": "Admin Pages/Reports.html",
        "label": "Reports",
    },
    "/admin/Profile": {
        "alias": "0e9d22b0-07ed-5a24-aa20-6063d5c9ebfa",
        "template": "Admin Pages/Admin_Profile.html",
        "label": "Admin Profile",
        "no_store": True,
    },
    "/admin/Settings": {
        "alias": "7d38a2ff-96c7-5851-875e-7a3112aeddf1",
        "template": "Admin Pages/Setting.html",
        "label": "Admin Settings",
        "no_store": True,
    },
    "/admin/Confiscated-items": {
        "alias": "dd5c6fcb-8cb9-54c8-bb07-d8b3f6e2aa79",
        "template": "Admin Pages/Confiscated_Item.html",
        "label": "Confiscated Items",
    },
    "/admin/Content-management": {
        "alias": "ab3bc951-819c-5bd7-aa04-2740b55a64a4",
        "template": "Admin Pages/Content_Management.html",
        "label": "Content Management",
    },
    "/admin/Content-management/features": {
        "alias": "cf6ffae9-1082-5e37-b051-3fffd2866f74",
        "template": "Admin Pages/admin_cms_features.html",
        "label": "Content Features",
    },
    "/admin/Content-management/about": {
        "alias": "cb34df2e-2169-53c8-897d-cac57f3ae592",
        "template": "Admin Pages/admin_cms_about.html",
        "label": "Content About",
    },
    "/admin/Content-Editor": {
        "alias": "d5e2c76e-2d33-5318-ba15-b150695800aa",
        "template": "Admin Pages/admin_cms.html",
        "label": "Content Editor",
    },
    "/student/dashboard": {
        "alias": "1372b8da-4295-5e64-b0c6-376dcfb310ad",
        "template": "student2.0.html",
        "label": "Student Dashboard",
        "no_store": True,
    },
    "/student/Messages": {
        "alias": "bf9af01e-6b61-56aa-b2fd-43b592474c81",
        "template": "Student Pages/Student_Messages.html",
        "label": "Student Messages",
        "no_store": True,
    },
    "/student/Lost-report": {
        "alias": "d42d0341-7220-58bf-a645-ea50972513ae",
        "template": "Student Pages/Student_LostReport.html",
        "label": "Student Lost Report",
        "no_store": True,
    },
    "/student/Found-report": {
        "alias": "0ca573bb-ece0-5781-87b8-b9bcf42fcc3d",
        "template": "Student Pages/Student_FoundReport.html",
        "label": "Student Found Report",
        "no_store": True,
    },
    "/student/profile": {
        "alias": "49546104-8ce2-52b6-ac6f-b67c42712b7e",
        "template": "Student Pages/Student_profile.html",
        "label": "Student Profile",
        "no_store": True,
    },
    "/student/settings": {
        "alias": "4f67af6c-1801-509b-916f-5d8daa20bd0d",
        "template": "Student Pages/Student_Settings.html",
        "label": "Student Settings",
        "no_store": True,
    },
}

PAGE_ALIAS_BY_ID = {
    data["alias"]: {"path": path, **data}
    for path, data in PAGE_ALIASES.items()
}


def set_no_store_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"


@app.middleware("http")
async def redirect_page_paths_to_aliases(request: Request, call_next):
    if request.method == "GET" and request.url.path in PAGE_ALIASES:
        alias_path = f"/c/{PAGE_ALIASES[request.url.path]['alias']}"
        if request.url.query:
            alias_path = f"{alias_path}?{request.url.query}"
        return RedirectResponse(alias_path, status_code=307)
    return await call_next(request)


@app.get("/c/{alias_id}")
def hashed_page(alias_id: str, request: Request, response: Response):
    page = PAGE_ALIAS_BY_ID.get(alias_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    if page.get("no_store"):
        set_no_store_headers(response)

    return templates.TemplateResponse(page["template"], {"request": request})

GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
MFA_CODE_EXPIRE_MINUTES = int(os.getenv("MFA_CODE_EXPIRE_MINUTES", "10"))
MFA_PENDING_LOGINS: dict[str, dict] = {}
PASSWORD_RESET_PENDING: dict[str, dict] = {}


class MFASettingsUpdate(BaseModel):
    two_factor: bool
    notifications: bool = True
    theme: str = "light"
    font_size: int = 16


class MFAVerifyRequest(BaseModel):
    email: EmailStr
    code: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str | None = None
    new_password: str


def ensure_user_settings_columns():
    statements = [
        """
        IF COL_LENGTH('users', 'two_factor_enabled') IS NULL
        BEGIN
            ALTER TABLE users ADD two_factor_enabled BIT NOT NULL CONSTRAINT DF_users_two_factor_enabled DEFAULT 0
        END
        """,
        """
        IF COL_LENGTH('users', 'push_notifications') IS NULL
        BEGIN
            ALTER TABLE users ADD push_notifications BIT NOT NULL CONSTRAINT DF_users_push_notifications DEFAULT 1
        END
        """,
        """
        IF COL_LENGTH('users', 'theme_mode') IS NULL
        BEGIN
            ALTER TABLE users ADD theme_mode NVARCHAR(20) NOT NULL CONSTRAINT DF_users_theme_mode DEFAULT 'light'
        END
        """,
        """
        IF COL_LENGTH('users', 'font_size') IS NULL
        BEGIN
            ALTER TABLE users ADD font_size INT NOT NULL CONSTRAINT DF_users_font_size DEFAULT 16
        END
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_item_possible_matches_column():
    statement = """
    IF COL_LENGTH('items', 'possible_matches') IS NULL
    BEGIN
        ALTER TABLE items ADD possible_matches NVARCHAR(MAX) NULL
    END
    """
    with engine.begin() as connection:
        connection.execute(text(statement))


def ensure_item_lifecycle_columns():
    statements = [
        """
        IF COL_LENGTH('items', 'deleted') IS NULL
        BEGIN
            ALTER TABLE items ADD deleted BIT NOT NULL CONSTRAINT DF_items_deleted DEFAULT 0
        END
        """,
        """
        IF COL_LENGTH('pending_items', 'deleted') IS NULL
        BEGIN
            ALTER TABLE pending_items ADD deleted BIT NOT NULL CONSTRAINT DF_pending_items_deleted DEFAULT 0
        END
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_confiscated_disposal_columns():
    statements = [
        """
        IF COL_LENGTH('confiscated_items', 'disposal_status') IS NULL
        BEGIN
            ALTER TABLE confiscated_items ADD disposal_status NVARCHAR(30) NOT NULL
                CONSTRAINT DF_confiscated_disposal_status DEFAULT 'active'
        END
        """,
        """
        IF COL_LENGTH('confiscated_items', 'disposal_note') IS NULL
        BEGIN
            ALTER TABLE confiscated_items ADD disposal_note NVARCHAR(500) NULL
        END
        """,
        """
        IF COL_LENGTH('confiscated_items', 'disposal_updated_at') IS NULL
        BEGIN
            ALTER TABLE confiscated_items ADD disposal_updated_at DATETIME2 NULL
        END
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_item_report_owner_columns():
    statements = [
        """
        IF COL_LENGTH('items', 'report_owner_user_id') IS NULL
        BEGIN
            ALTER TABLE items ADD report_owner_user_id INT NULL
        END
        """,
        """
        IF COL_LENGTH('items', 'report_owner_name') IS NULL
        BEGIN
            ALTER TABLE items ADD report_owner_name NVARCHAR(255) NULL
        END
        """,
        """
        IF COL_LENGTH('items', 'report_owner_group') IS NULL
        BEGIN
            ALTER TABLE items ADD report_owner_group NVARCHAR(100) NULL
        END
        """,
        """
        IF COL_LENGTH('reference_items', 'report_owner_user_id') IS NULL
        BEGIN
            ALTER TABLE reference_items ADD report_owner_user_id INT NULL
        END
        """,
        """
        IF COL_LENGTH('reference_items', 'report_owner_name') IS NULL
        BEGIN
            ALTER TABLE reference_items ADD report_owner_name NVARCHAR(255) NULL
        END
        """,
        """
        IF COL_LENGTH('reference_items', 'report_owner_group') IS NULL
        BEGIN
            ALTER TABLE reference_items ADD report_owner_group NVARCHAR(100) NULL
        END
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_item_id_column():
    statement = """
    IF COL_LENGTH('items', 'item_id') IS NULL
    BEGIN
        ALTER TABLE items ADD item_id AS id
    END
    """
    with engine.begin() as connection:
        connection.execute(text(statement))


def ensure_item_code_column():
    statement = """
    IF COL_LENGTH('items', 'item_code') IS NULL
    BEGIN
        ALTER TABLE items ADD item_code AS
            CASE
                WHEN status = 'lost' THEN 'LOST-' + RIGHT('000000' + CONVERT(VARCHAR(20), id), 6)
                WHEN status = 'found' THEN 'FOUND-' + RIGHT('000000' + CONVERT(VARCHAR(20), id), 6)
                ELSE 'ITEM-' + RIGHT('000000' + CONVERT(VARCHAR(20), id), 6)
            END
    END
    """
    with engine.begin() as connection:
        connection.execute(text(statement))


def ensure_notification_columns():
    statements = [
        """
        IF COL_LENGTH('notifications', 'target_url') IS NULL
        BEGIN
            ALTER TABLE notifications ADD target_url NVARCHAR(500) NULL
        END
        """,
        """
        IF COL_LENGTH('notifications', 'created_by_admin_id') IS NULL
        BEGIN
            ALTER TABLE notifications ADD created_by_admin_id INT NULL
        END
        """
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def ensure_report_module_indexes():
    statements = [
        """
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_items_report_module' AND object_id = OBJECT_ID('items'))
        BEGIN
            CREATE INDEX ix_items_report_module ON items (archived, status, created_at)
        END
        """,
        """
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_items_user_id' AND object_id = OBJECT_ID('items'))
        BEGIN
            CREATE INDEX ix_items_user_id ON items (user_id)
        END
        """,
        """
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_claims_created_at' AND object_id = OBJECT_ID('claims'))
        BEGIN
            CREATE INDEX ix_claims_created_at ON claims (created_at)
        END
        """,
        """
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_claim_decision_reports_claim_id' AND object_id = OBJECT_ID('claim_decision_reports'))
        BEGIN
            CREATE INDEX ix_claim_decision_reports_claim_id ON claim_decision_reports (claim_id)
        END
        """,
        """
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_reference_items_deleted_at' AND object_id = OBJECT_ID('reference_items'))
        BEGIN
            CREATE INDEX ix_reference_items_deleted_at ON reference_items (deleted_at)
        END
        """,
        """
        IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_confiscated_items_created_at' AND object_id = OBJECT_ID('confiscated_items'))
        BEGIN
            CREATE INDEX ix_confiscated_items_created_at ON confiscated_items (created_at)
        END
        """,
    ]

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def cleanup_expired_mfa_codes():
    now = datetime.utcnow()
    expired_keys = [
        email for email, payload in MFA_PENDING_LOGINS.items()
        if payload.get("expires_at") and payload["expires_at"] <= now
    ]
    for email in expired_keys:
        MFA_PENDING_LOGINS.pop(email, None)


def cleanup_expired_password_reset_codes():
    now = datetime.utcnow()
    expired_keys = [
        email for email, payload in PASSWORD_RESET_PENDING.items()
        if payload.get("expires_at") and payload["expires_at"] <= now
    ]
    for email in expired_keys:
        PASSWORD_RESET_PENDING.pop(email, None)


def send_email_code(recipient_email: str, verification_code: str):
    if not GMAIL_SENDER_EMAIL or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail SMTP credentials are not configured")

    message = EmailMessage()
    message["Subject"] = "LookFor login verification code"
    message["From"] = GMAIL_SENDER_EMAIL
    message["To"] = recipient_email

    message.set_content(
        f"""Hello,

We received a request to log in to your LookFor account.

Your verification code for LookFor is: {verification_code}
This code expires in {MFA_CODE_EXPIRE_MINUTES} minutes.

If you did not request this code, please ignore this email or secure your account if you suspect unauthorized access.

- LookFor Team"""
    )

    message.add_alternative(
        f"""
        <html>
            <body>
                <p>Hello,</p>
                <p>We received a request to log in to your LookFor account.</p>
                <p><strong>Your verification code for LookFor is: {verification_code}</strong></p>
                <p>This code expires in {MFA_CODE_EXPIRE_MINUTES} minutes.</p>
                <p>If you did not request this code, please ignore this email or secure your account if you suspect unauthorized access.</p>
                <p>- LookFor Team</p>
            </body>
        </html>
        """,
        subtype="html"
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
        smtp.send_message(message)


def send_password_reset_code(recipient_email: str, verification_code: str):
    if not GMAIL_SENDER_EMAIL or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail SMTP credentials are not configured")

    message = EmailMessage()
    message["Subject"] = "LookFor password reset code"
    message["From"] = GMAIL_SENDER_EMAIL
    message["To"] = recipient_email

    message.set_content(
        f"""Hello,

We received a request to reset the password for your LookFor account.

Your password reset code is: {verification_code}
This code expires in {MFA_CODE_EXPIRE_MINUTES} minutes.

If you did not request this reset, you can safely ignore this email.

- LookFor Team"""
    )

    message.add_alternative(
        f"""
        <html>
            <body>
                <p>Hello,</p>
                <p>We received a request to reset the password for your LookFor account.</p>
                <p><strong>Your password reset code is: {verification_code}</strong></p>
                <p>This code expires in {MFA_CODE_EXPIRE_MINUTES} minutes.</p>
                <p>If you did not request this reset, you can safely ignore this email.</p>
                <p>- LookFor Team</p>
            </body>
        </html>
        """,
        subtype="html"
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_SENDER_EMAIL, GMAIL_APP_PASSWORD)
        smtp.send_message(message)


def build_auth_response(user: models.User):
    access_token = create_access_token(
        data={
            "sub": user.email,
            "id": user.id,
            "is_admin": user.is_admin,
            "must_change": bool(user.must_change_password),
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_admin": user.is_admin
    }


def update_last_login(db: Session, user: models.User):
    user.last_login = datetime.now()
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Update failed: {e}")


def issue_mfa_code(user: models.User):
    cleanup_expired_mfa_codes()
    verification_code = f"{secrets.randbelow(1000000):06d}"
    MFA_PENDING_LOGINS[user.email.lower()] = {
        "user_id": user.id,
        "code": verification_code,
        "expires_at": datetime.utcnow() + timedelta(minutes=MFA_CODE_EXPIRE_MINUTES),
    }
    send_email_code(user.email, verification_code)
    return {
        "step": "mfa_required",
        "email": user.email,
        "expires_in_minutes": MFA_CODE_EXPIRE_MINUTES,
    }



def auto_archive_pending(db: Session):
    limit = datetime.utcnow() - timedelta(days=3)

    expired = db.query(models.PendingItem).filter(
        models.PendingItem.created_at < limit,
        models.PendingItem.archived == False
    ).all()

    for item in expired:
        item.archived = True

    db.commit()

        

# --- 4. STARTUP TASKS (Ensure Admin Access) ---
@app.on_event("startup")
def create_default_admin():
    ensure_user_settings_columns()
    ensure_item_id_column()
    ensure_item_code_column()
    ensure_item_possible_matches_column()
    ensure_item_lifecycle_columns()
    ensure_confiscated_disposal_columns()
    ensure_item_report_owner_columns()
    ensure_notification_columns()
    ensure_report_module_indexes()
    db = next(get_db())
    try:
        process_academic_term_schedule(db)
        admin_email = ROOT_ADMIN_EMAIL
        admin_full_name = "LookForAdministrator"
        admin = db.query(models.User).filter(models.User.email == admin_email).first()
        if not admin:
            hashed_pw = pwd_context.hash("STI_Admin_2026")
            new_admin = models.User(
                email=admin_email,
                hashed_password=hashed_pw,
                full_name=admin_full_name,
                is_admin=True,
                must_change_password=False
            )
            db.add(new_admin)
            db.commit()
            print(f"Created Admin: {admin_email}")
            admin = new_admin

        if admin and admin.full_name != admin_full_name:
            admin.full_name = admin_full_name
            db.commit()
            print(f"Updated root admin name to {admin_full_name}")

        target_admin = db.query(models.User).filter(
            models.User.id == admin.id
        ).first() if admin else None

        if target_admin:
            root_changed = False
            if not target_admin.is_admin:
                target_admin.is_admin = True
                root_changed = True

            if target_admin.must_change_password:
                target_admin.must_change_password = False
                root_changed = True

            try:
                current_permissions = json.loads(target_admin.permissions) if target_admin.permissions else []
            except (json.JSONDecodeError, TypeError):
                current_permissions = []

            required_permissions = ADMIN_PERMISSION_KEYS

            updated_permissions = list(dict.fromkeys(current_permissions + required_permissions))
            if updated_permissions != current_permissions:
                target_admin.permissions = json.dumps(updated_permissions)
                root_changed = True

            if root_changed:
                db.commit()
                print(f"Normalized root admin access for {admin_full_name}")

    finally:
        db.close()

# --- 5. AUTHENTICATION ROUTES ---
from fastapi.security import OAuth2PasswordRequestForm

@app.post("/token")
async def login_for_access_token(
    db: Session = Depends(get_db), 
    form_data: OAuth2PasswordRequestForm = Depends()
):
    login_candidates = get_login_email_candidates(form_data.username)

    # 1. Check if email exists
    user = db.query(models.User).filter(models.User.email.in_(login_candidates)).first()

    if not user:
        raise HTTPException(
            status_code=401, detail="invalid_email"
        )
    if bool(user.is_archived):
        raise HTTPException(
            status_code=403,
            detail="account_archived"
        )

    # 2. Check if password is correct
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="wrong_password"
        )

    if getattr(user, "two_factor_enabled", False):
        try:
            return issue_mfa_code(user)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"mfa_email_failed:{exc}"
            ) from exc

    update_last_login(db, user)
    return build_auth_response(user)


@app.post("/auth/verify-mfa")
async def verify_mfa_code(
    payload: MFAVerifyRequest,
    db: Session = Depends(get_db),
):
    cleanup_expired_mfa_codes()
    email = payload.email.lower().strip()
    pending_login = MFA_PENDING_LOGINS.get(email)

    if not pending_login:
        raise HTTPException(status_code=401, detail="mfa_session_expired")

    if pending_login["code"] != payload.code.strip():
        raise HTTPException(status_code=401, detail="invalid_mfa_code")

    user = db.query(models.User).filter(
        models.User.id == pending_login["user_id"],
        models.User.email == email,
    ).first()

    if not user:
        MFA_PENDING_LOGINS.pop(email, None)
        raise HTTPException(status_code=404, detail="user_not_found")
    if bool(user.is_archived):
        MFA_PENDING_LOGINS.pop(email, None)
        raise HTTPException(status_code=403, detail="account_archived")

    MFA_PENDING_LOGINS.pop(email, None)
    update_last_login(db, user)
    return build_auth_response(user)


@app.post("/auth/request-password-reset")
async def request_password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    cleanup_expired_password_reset_codes()
    login_candidates = get_login_email_candidates(payload.email)
    user = db.query(models.User).filter(models.User.email.in_(login_candidates)).first()

    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    if bool(user.is_archived):
        raise HTTPException(status_code=403, detail="account_archived")

    reset_code = f"{secrets.randbelow(1000000):06d}"
    PASSWORD_RESET_PENDING[user.email.lower()] = {
        "user_id": user.id,
        "code": reset_code,
        "expires_at": datetime.utcnow() + timedelta(minutes=MFA_CODE_EXPIRE_MINUTES),
    }

    try:
        send_password_reset_code(user.email, reset_code)
    except Exception as exc:
        PASSWORD_RESET_PENDING.pop(user.email.lower(), None)
        raise HTTPException(
            status_code=503,
            detail=f"password_reset_email_failed:{exc}"
        ) from exc

    return {
        "status": "reset_code_sent",
        "email": user.email,
        "expires_in_minutes": MFA_CODE_EXPIRE_MINUTES,
    }


@app.post("/auth/reset-password")
async def reset_password_with_code(
    payload: PasswordResetConfirmRequest,
    db: Session = Depends(get_db),
):
    cleanup_expired_password_reset_codes()
    email = payload.email.lower().strip()
    pending_reset = PASSWORD_RESET_PENDING.get(email)

    if not pending_reset:
        raise HTTPException(status_code=401, detail="password_reset_session_expired")

    if pending_reset["code"] != payload.code.strip():
        raise HTTPException(status_code=401, detail="invalid_reset_code")

    new_password = (payload.new_password or "").strip()
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="password_too_short")

    user = db.query(models.User).filter(
        models.User.id == pending_reset["user_id"],
        models.User.email == email,
    ).first()

    if not user:
        PASSWORD_RESET_PENDING.pop(email, None)
        raise HTTPException(status_code=404, detail="user_not_found")
    if bool(user.is_archived):
        PASSWORD_RESET_PENDING.pop(email, None)
        raise HTTPException(status_code=403, detail="account_archived")

    user.hashed_password = get_password_hash(new_password)
    user.must_change_password = False
    db.commit()

    PASSWORD_RESET_PENDING.pop(email, None)
    return {"status": "password_reset_success"}


@app.get("/auth/settings")
async def get_auth_settings(
    current_user: models.User = Depends(get_current_user),
):
    return {
        "two_factor": bool(getattr(current_user, "two_factor_enabled", False)),
        "notifications": bool(getattr(current_user, "push_notifications", True)),
        "theme": getattr(current_user, "theme_mode", "light") or "light",
        "font_size": int(getattr(current_user, "font_size", 16) or 16),
    }


@app.post("/auth/settings")
async def update_auth_settings(
    payload: MFASettingsUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.two_factor_enabled = bool(payload.two_factor)
    user.push_notifications = bool(payload.notifications)
    user.theme_mode = (payload.theme or "light")[:20]
    user.font_size = max(12, min(24, int(payload.font_size)))
    db.commit()

    return {
        "status": "success",
        "message": "Settings updated successfully",
    }


@app.post("/auth/refresh")
async def refresh_access_token(
    current_user: models.User = Depends(get_current_user),
):
    access_token = create_access_token(
        data={
            "sub": current_user.email,
            "id": current_user.id,
            "is_admin": current_user.is_admin,
            "must_change": bool(current_user.must_change_password),
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "is_admin": current_user.is_admin,
    }

# --- 6. PAGE ROUTES (HTML) ---
@app.get("/")
def landing_page(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/admin/Content-management")
def admin_content_management_page(request: Request):
    return templates.TemplateResponse("Admin Pages/admin_cms.html", {"request": request})

@app.get("/admin/Content-management/features")
def admin_content_management_features_page(request: Request):
    return templates.TemplateResponse("Admin Pages/admin_cms_features.html", {"request": request})

@app.get("/admin/Content-management/about")
def admin_content_management_about_page(request: Request):
    return templates.TemplateResponse("Admin Pages/admin_cms_about.html", {"request": request})

@app.get("/explore")
def explore_page(request: Request):
    return templates.TemplateResponse("explorefeature.html", {"request": request})
@app.get("/about")
def about_page(request: Request):
    return templates.TemplateResponse("aboutlookfor.html", {"request": request})


@app.get("/download/lookfor-app.apk", include_in_schema=False)
def download_android_app():
    apk_path = os.path.join(STATIC_DIR, "downloads", "lookfor-app.apk")
    if not os.path.isfile(apk_path):
        raise HTTPException(status_code=404, detail="Android app download is unavailable.")

    return FileResponse(
        path=apk_path,
        # Some Android browsers inspect an APK's ZIP container and append
        # ".zip" despite the APK MIME type. A generic binary attachment plus
        # an explicit filename reliably preserves the .apk extension.
        media_type="application/octet-stream",
        filename="LookFor-Android.apk",
        headers={
            "Content-Disposition": (
                'attachment; filename="LookFor-Android.apk"; '
                "filename*=UTF-8''LookFor-Android.apk"
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-transform",
        },
    )



@app.post("/auth/change-password")
async def change_password(
    data: ChangePasswordRequest,
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    new_password = (data.new_password or "").strip()
    if not new_password:
        raise HTTPException(status_code=400, detail="Password is required")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")

    # Fetch user from DB
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    current_password = (data.current_password or "").strip()
    if not user.must_change_password:
        if not current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        if not verify_password(current_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

    if verify_password(new_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    # Requirement: Hash the new password using bcrypt (PBI-002: 14)
    user.hashed_password = get_password_hash(new_password)
    
    # Requirement: Update the database (PBI-002: 15)
    user.must_change_password = False 
    db.commit()

    return {"message": "Password updated successfully"}


# --- 8. AI & UPLOAD ROUTES ---
def generate_temp_password(length=8):
    # Generates a random string like 'aB3dE5gH'
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))
# Updated part of your main.py


def get_user_display_name(user: models.User) -> str:
    return (
        user.full_name
        or " ".join(
            part for part in [user.first_name, user.middle_name, user.last_name] if part
        ).strip()
        or user.email
        or "Unknown User"
    )


def get_user_role_label(user: models.User) -> str:
    if user.is_admin:
        return "Admin"

    has_department = bool((user.department or "").strip()) and (user.department or "").strip() != "N/A"
    has_course = bool((user.course or "").strip())
    has_section = bool((user.section or "").strip())

    return "Faculty" if has_department and not has_course and not has_section else "Student"


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


@app.get("/api/current-user")
def get_current_user_profile(current_user: models.User = Depends(get_current_user)):
    role_label = get_user_role_label(current_user)
    is_student_active = True

    if not current_user.is_admin:
        try:
            permissions = json.loads(current_user.permissions) if isinstance(current_user.permissions, str) else (current_user.permissions or [])
        except Exception:
            permissions = []
        is_student_active = "Student-Portal-Access" in permissions

    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "student_no": current_user.student_no,
        "course": current_user.course,
        "section": current_user.section,
        "level": getattr(current_user, "level", None),
        "department": current_user.department,
        "profile_pic": deployed_static_path(current_user.profile_pic),
        "is_admin": bool(current_user.is_admin),
        "role_label": role_label,
        "is_student_active": is_student_active,
        "must_change_password": bool(getattr(current_user, "must_change_password", False)),
        "two_factor_enabled": bool(getattr(current_user, "two_factor_enabled", False)),
        "push_notifications": bool(getattr(current_user, "push_notifications", True)),
        "theme_mode": getattr(current_user, "theme_mode", "light") or "light",
        "font_size": int(getattr(current_user, "font_size", 16) or 16),
    }

# --- LOGIC A: QUICK SEARCH (Compare only, no saving) ---
# LOGIC A: QUICK SEARCH (Immediate feedback, no DB storage)
@app.get("/api/users/search")
def search_users(
    q: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    search_text = (q or "").strip().lower()
    search_terms = [term for term in search_text.split() if term]
    query = db.query(models.User)

    for term in search_terms:
        query = query.filter(
            or_(
                func.lower(models.User.email).contains(term),
                func.lower(models.User.full_name).contains(term),
                func.lower(models.User.student_no).contains(term),
                func.lower(models.User.course).contains(term),
                func.lower(models.User.department).contains(term),
                func.lower(models.User.section).contains(term)
            )
        )

    if current_user.is_admin:
        query = query.filter(models.User.id != current_user.id)
    else:
        query = query.filter(models.User.is_admin == True)

    users = query.limit(300 if current_user.is_admin and not search_text else 10).all()

    return [
        {
            "id": u.id,
            "email": u.email,
            "full_name": get_user_display_name(u),
            "role_label": get_user_role_label(u),
            "student_no": u.student_no,
            "course": u.course,
            "section": u.section,
            "department": u.department,
        }
        for u in users
    ]

@app.get("/api/quick-search")
async def quick_search(
    q: str = Query(...),
    category: str = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.Item).filter(
        models.Item.status.ilike("found"),
        models.Item.archived == False
    )

    if category:
        query = query.filter(models.Item.category.ilike(f"%{category}%"))

    found_items = query.all()

    matches = [
        item for item in found_items
        if q.lower() in item.description.lower()
    ]

    if not found_items:
        return {"match_percentage": 0, "match_found": False}

    percentage = (len(matches) / len(found_items)) * 100

    return {
        "match_found": len(matches) > 0,
        "match_percentage": round(percentage, 2),
        "total_items": len(found_items),
        "matched_items": len(matches)
    }




@app.post("/api/quick-compare")
async def quick_compare(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        validate_upload_file_size(file, label="Main image")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


    
    # Process image
    image_bytes = await file.read()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    model_obj, processor_obj = get_clip_components()
    inputs = processor_obj(images=img, return_tensors="pt")

    import torch
    with torch.no_grad():
        outputs = model_obj.get_image_features(**inputs)
        if hasattr(outputs, "pooler_output"):
            feat = outputs.pooler_output
        else:
            feat = outputs
        feat = feat / feat.norm(p=2, dim=-1, keepdim=True)
        search_vec = feat.cpu().numpy().flatten()

    # Fetch Found items
    items = db.query(models.Item).filter(
        models.Item.status.ilike("found"),
        models.Item.image_embedding != None
    ).all()

    if not items:
        return {"highest_score": 0.0, "message": "No found items in database"}

    highest_score = 0.0
    best_item = None

    for item in items:
        stored_vec = np.array(json.loads(item.image_embedding)).flatten()
        score = float(np.dot(search_vec, stored_vec))
        if score > highest_score:
            highest_score = score
            best_item = item

    return {
        "highest_score": highest_score,
        "matched_item": {
            "id": best_item.id if best_item else None,
            "category": best_item.category if best_item else None,
            "description": best_item.description if best_item else None,
            "image_path": public_file_url(best_item.image_path) if best_item else None,
        }
    }

def normalize_match_value(value):
    return " ".join(str(value or "").strip().lower().split())


def build_item_dataset_text(item):
    name_part = ""
    if item.description:
        if item.description.startswith("[") and "]" in item.description:
            name_part = item.description[1:item.description.index("]")]
        else:
            name_part = item.description.split(".")[0][:80]

    parts = [
        f"category {item.category}" if item.category else "",
        f"name {name_part}" if name_part else "",
        f"brand {item.brand}" if item.brand else "",
        f"color {item.color}" if item.color else "",
        f"location {item.location}" if item.location else "",
        f"department {item.department}" if item.department else "",
        f"description {item.description}" if item.description else "",
    ]
    return ". ".join(part for part in parts if part)


def get_reference_bonus(candidate_item, query_vec, references):
    candidate_brand = normalize_match_value(getattr(candidate_item, "brand", None))
    candidate_color = normalize_match_value(getattr(candidate_item, "color", None))

    filtered_references = []
    for reference in references:
        reference_brand = normalize_match_value(getattr(reference, "brand", None))
        reference_color = normalize_match_value(getattr(reference, "color", None))

        brand_matches = not candidate_brand or not reference_brand or candidate_brand == reference_brand
        color_matches = not candidate_color or not reference_color or candidate_color == reference_color

        if brand_matches and color_matches:
            filtered_references.append(reference)

    if not filtered_references:
        filtered_references = references

    similarity_scores = []
    for reference in filtered_references:
        if not reference.image_embedding:
            continue
        try:
            reference_vec = np.array(json.loads(reference.image_embedding)).flatten()
            similarity_scores.append(float(np.dot(query_vec, reference_vec)))
        except Exception:
            continue

    if not similarity_scores:
        return 0.0

    top_scores = sorted(similarity_scores, reverse=True)[:3]
    return max(0.0, sum(top_scores) / len(top_scores)) * 0.08


def compute_text_detail_matches(
    db: Session,
    *,
    category: str,
    location: str,
    description: str | None,
    brand: str | None,
    color: str | None,
    status: str,
    search_vec: np.ndarray,
    query_text_vec: np.ndarray,
    exclude_item_id: int | None = None,
):
    normalized_status = " ".join(str(status or "").strip().lower().split())
    normalized_category = (category or "").strip()
    if normalized_status not in {"lost", "found"}:
        return {
            "highest_score": 0.0,
            "generated_embedding": search_vec.tolist(),
            "matched_item": None,
            "matched_items": [],
            "action": "no_match"
        }

    target_status = "found" if normalized_status == "lost" else "lost"

    if not normalized_category:
        return {
            "highest_score": 0.0,
            "generated_embedding": search_vec.tolist() if isinstance(search_vec, np.ndarray) else list(search_vec),
            "matched_item": None,
            "matched_items": [],
            "action": "no_match"
        }

    strict_match_threshold = 0.55
    possible_match_threshold = 0.45   # adjust if needed

    def item_category_name(item: models.Item) -> str:
        return item.category_relationship.name if getattr(item, "category_relationship", None) else item.category

    def score_items(items: list[models.Item], reference_items: list[models.ReferenceItem]) -> list[dict]:
        matches = []
        for item in items:
            try:
                if not item.image_embedding:
                    continue

                stored_vec = np.array(json.loads(item.image_embedding)).flatten()
                image_score = float(np.dot(search_vec, stored_vec))

                item_dataset_text = build_item_dataset_text(item)
                text_score = 0.0
                if item_dataset_text:
                    dataset_text_vec = get_text_embedding(item_dataset_text)
                    text_score = float(np.dot(query_text_vec, dataset_text_vec))

                score = (image_score * 0.6) + (text_score * 0.4)

                normalized_brand = normalize_match_value(brand)
                item_brand = normalize_match_value(item.brand)
                if normalized_brand and item_brand and normalized_brand == item_brand:
                    score += 0.08
                elif normalized_brand and item_brand and normalized_brand != item_brand:
                    score -= 0.12

                normalized_color = normalize_match_value(color)
                item_color = normalize_match_value(item.color)
                if normalized_color and item_color and normalized_color == item_color:
                    score += 0.05
                elif normalized_color and item_color and normalized_color != item_color:
                    score -= 0.20

                normalized_location = normalize_match_value(location)
                item_location = normalize_match_value(item.location)
                if normalized_location and item_location and (
                    normalized_location in item_location or item_location in normalized_location
                ):
                    score += 0.03

                score += get_reference_bonus(item, search_vec, reference_items)

                if score >= possible_match_threshold:
                    matches.append({
                        "id": item.id,
                        "score": round(score, 4),
                        "category": item_category_name(item),
                        "location": item.location,
                        "image_path": public_file_url(item.image_path),
                        "brand": item.brand,
                        "color": item.color,
                        "description": item.description,
                    })

            except Exception as e:
                print(f"Error: {e}")
                continue
        return matches

    candidate_items = db.query(models.Item).outerjoin(models.Category).filter(
        models.Item.status.ilike(target_status),
        models.Item.is_matched == False,
        models.Item.archived == False
    ).all()

    if exclude_item_id is not None:
        candidate_items = [item for item in candidate_items if item.id != exclude_item_id]

    reference_items = db.query(models.ReferenceItem).filter(
        models.ReferenceItem.status.ilike(target_status),
        models.ReferenceItem.image_embedding.isnot(None)
    ).all()

    all_matches = score_items(candidate_items, reference_items)

    # Sort highest to lowest
    all_matches.sort(key=lambda x: x["score"], reverse=True)
    all_matches = all_matches[:3]

    best_match = all_matches[0] if all_matches else None
    highest_score = best_match["score"] if best_match else 0.0

    return {
        "highest_score": round(highest_score, 4),
        "generated_embedding": search_vec.tolist() if isinstance(search_vec, np.ndarray) else list(search_vec),
        "matched_item": best_match if best_match and highest_score >= strict_match_threshold else None,
        "matched_items": all_matches,
        "action": "show_match" if all_matches else "no_match",
        "warning": None,
    }


# ============================================
# API: Compare Text Details
# ============================================
@app.post("/api/compare-text-details")
async def compare_text_details(
    category: str = Form(...),
    location: str = Form(...),
    description: str = Form(None),
    brand: str = Form(None),
    color: str = Form(None),
    status: str = Form(...),
    image: UploadFile = File(...),
    extra_image_1: UploadFile = File(None),
    extra_image_2: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    for upload, label in (
        (image, "Main image"),
        (extra_image_1, "Optional image 2"),
        (extra_image_2, "Optional image 3"),
    ):
        try:
            validate_upload_file_size(upload, label=label)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    parts = [f"A {color}" if color else "An item", f"{brand}" if brand else "", f"{category}"]
    description_prompt = " ".join(filter(None, parts))
    description_text = (description or "").strip()
    text_query = f"{description_prompt} at {location}. {description_text}".strip()

    query_images = []
    for upload in (image, extra_image_1, extra_image_2):
        if not upload or not upload.filename:
            continue
        image_bytes = await upload.read()
        await upload.seek(0)
        if not image_bytes:
            continue
        try:
            query_images.append(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid uploaded image: {upload.filename}") from exc

    if not query_images:
        raise HTTPException(status_code=400, detail="At least one image is required.")

    image_vec = get_multi_image_embedding(query_images)
    query_text_vec = get_text_embedding(text_query)

    search_vec = (image_vec * 0.6) + (query_text_vec * 0.4)
    search_norm = np.linalg.norm(search_vec)
    if search_norm != 0:
        search_vec = search_vec / search_norm

    return compute_text_detail_matches(
        db,
        category=category,
        location=location,
        description=description,
        brand=brand,
        color=color,
        status=status,
        search_vec=search_vec,
        query_text_vec=query_text_vec,
    )


@app.get("/api/items/{item_id}/possible-matches")
def get_saved_item_possible_matches(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    item = db.query(models.Item).filter(models.Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if item.status != "lost":
        return {
            "highest_score": 0.0,
            "generated_embedding": [],
            "matched_item": None,
            "matched_items": [],
            "action": "no_match"
        }

    current_user_name = format_user_display_name(current_user).strip().lower()
    legacy_name_matches = (
        not getattr(item, "report_owner_user_id", None)
        and current_user_name
        and str(getattr(item, "report_owner_name", "") or "").strip().lower() == current_user_name
    )
    user_owns_report = (
        item.user_id == current_user.id
        or getattr(item, "report_owner_user_id", None) == current_user.id
        or legacy_name_matches
    )
    if not current_user.is_admin and not user_owns_report:
        raise HTTPException(status_code=403, detail="You do not have access to this item")

    if item.possible_matches:
        try:
            saved_matches = json.loads(item.possible_matches)
            saved_matches = saved_matches if isinstance(saved_matches, list) else []
        except Exception:
            saved_matches = []

        if saved_matches:
            saved_matches = saved_matches[:3]
            best_match = saved_matches[0]
            highest_score = float(best_match.get("score", 0) or 0)
            return {
                "highest_score": round(highest_score, 4),
                "generated_embedding": [],
                "matched_item": best_match if highest_score >= 0.55 else None,
                "matched_items": saved_matches,
                "action": "show_match"
            }

    text_query_parts = [
        f"A {item.color}" if item.color else "An item",
        f"{item.brand}" if item.brand else "",
        f"{item.category}" if item.category else "",
    ]
    description_prompt = " ".join(filter(None, text_query_parts))
    description_text = (item.description or "").strip()
    text_query = f"{description_prompt} at {item.location or 'Unknown'}. {description_text}".strip()
    query_text_vec = get_text_embedding(text_query)

    image_vec = None
    if item.image_embedding:
        try:
            image_vec = np.array(json.loads(item.image_embedding)).flatten()
        except Exception:
            image_vec = None

    if image_vec is not None and image_vec.size:
        search_vec = (image_vec * 0.6) + (query_text_vec * 0.4)
    else:
        search_vec = query_text_vec

    search_norm = np.linalg.norm(search_vec)
    if search_norm != 0:
        search_vec = search_vec / search_norm

    return compute_text_detail_matches(
        db,
        category=item.category,
        location=item.location or "Unknown",
        description=item.description,
        brand=item.brand,
        color=item.color,
        status=item.status,
        search_vec=search_vec,
        query_text_vec=query_text_vec,
        exclude_item_id=item.id,
    )


@app.get("/api/users/list")
def get_conversation_partners(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    # 1. Find all User IDs involved in a conversation with the logged-in user
    # This works for both Students AND Admins
    msg_partners = db.query(models.Message.sender_id, models.Message.recipient_id).filter(
        or_(
            models.Message.sender_id == current_user.id,
            models.Message.recipient_id == current_user.id
        )
    ).all()

    # 2. Extract unique IDs (excluding the current user)
    partner_ids = set()
    latest_by_partner_id = {}
    for s_id, r_id in msg_partners:
        if s_id != current_user.id:
            partner_ids.add(s_id)
        if r_id != current_user.id:
            partner_ids.add(r_id)

    # 3. If a student has NO history yet, we manually add the Admin 
    # so they have someone to talk to for the first time.
    if not current_user.is_admin and not partner_ids:
        admin = db.query(models.User).filter(models.User.is_admin == True).first()
        if admin:
            partner_ids.add(admin.id)

    # 4. Fetch the User objects
    users = db.query(models.User).filter(models.User.is_admin == True if not current_user.is_admin else models.User.id.in_(partner_ids)).all()
    # Note: The logic above ensures students see Admins, and Admins see their history.

    if partner_ids:
        latest_messages = (
            db.query(models.Message)
            .filter(
                or_(
                    models.Message.sender_id == current_user.id,
                    models.Message.recipient_id == current_user.id
                )
            )
            .order_by(models.Message.created_at.desc(), models.Message.id.desc())
            .all()
        )

        for message in latest_messages:
            partner_id = message.recipient_id if message.sender_id == current_user.id else message.sender_id
            if partner_id in partner_ids and partner_id not in latest_by_partner_id:
                latest_by_partner_id[partner_id] = message

    result = []
    for u in users:
        latest_message = latest_by_partner_id.get(u.id)
        unread_count = db.query(models.Message).filter(
            models.Message.sender_id == u.id,
            models.Message.recipient_id == current_user.id,
            func.trim(func.lower(models.Message.status)) == "unread"
        ).count()
        
        result.append({
            "id": u.id,
            "email": u.email,
            "full_name": get_user_display_name(u),
            "is_admin": u.is_admin,
            "has_unread": unread_count > 0,
            "role_label": get_user_role_label(u),
            "student_no": u.student_no,
            "last_message": latest_message.content if latest_message else "",
            "last_message_at": latest_message.created_at if latest_message else None,
            "is_outgoing": bool(latest_message and latest_message.sender_id == current_user.id),
        })

    result.sort(key=lambda user: user["last_message_at"] or datetime.min, reverse=True)
    return result

@app.get("/api/messages/unread-count")
def get_message_unread_count(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    unread_count = db.query(models.Message).filter(
        models.Message.recipient_id == current_user.id,
        func.trim(func.lower(models.Message.status)) == "unread"
    ).count()

    return {"unread_count": unread_count}

@app.get("/api/messages/recent")
def get_recent_message_interactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    limit: int = 20,
):
    limit = max(1, min(limit, 50))
    recent_messages = (
        db.query(models.Message)
        .options(joinedload(models.Message.sender), joinedload(models.Message.recipient))
        .filter(models.Message.recipient_id == current_user.id)
        .order_by(models.Message.created_at.desc(), models.Message.id.desc())
        .limit(200)
        .all()
    )

    interactions = []
    seen_partner_ids = set()

    for message in recent_messages:
        partner = message.sender
        if not partner or partner.id in seen_partner_ids:
            continue

        seen_partner_ids.add(partner.id)
        unread_count = db.query(models.Message).filter(
            models.Message.sender_id == partner.id,
            models.Message.recipient_id == current_user.id,
            func.trim(func.lower(models.Message.status)) == "unread"
        ).count()

        interactions.append({
            "partner_id": partner.id,
            "partner_name": get_user_display_name(partner),
            "partner_email": partner.email,
            "role_label": get_user_role_label(partner),
            "last_message": message.content or "",
            "last_message_at": message.created_at,
            "is_outgoing": False,
            "unread_count": unread_count,
        })

        if len(interactions) >= limit:
            break

    return interactions


def serialize_pending_found_match(pending_item: models.PendingItem, score: float | None = None) -> dict:
    return {
        "id": pending_item.id,
        "score": round(float(score or 0), 4),
        "category": pending_item.category,
        "location": pending_item.location,
        "image_path": public_file_url(pending_item.image_path),
        "brand": pending_item.brand,
        "color": pending_item.color,
        "description": pending_item.description,
        "source": "pending_found",
    }


def prepend_lost_possible_match(lost_item: models.Item, match_payload: dict) -> int:
    existing_matches = []
    if lost_item.possible_matches:
        try:
            parsed_matches = json.loads(lost_item.possible_matches)
            existing_matches = parsed_matches if isinstance(parsed_matches, list) else []
        except Exception:
            existing_matches = []

    match_id = match_payload.get("id")
    match_source = match_payload.get("source", "found")
    deduped_matches = [
        match for match in existing_matches
        if not (
            isinstance(match, dict)
            and match.get("id") == match_id
            and match.get("source", "found") == match_source
        )
    ]
    updated_matches = [match_payload, *deduped_matches][:3]
    lost_item.possible_matches = json.dumps(updated_matches)
    return len(updated_matches)


@app.post("/api/save-found-item")
async def save_found_item(
    item_name: str = Form(...),
    category: str = Form(...),
    description: str = Form(None),
    location: str = Form(...),
    brand: str = Form(None),
    color: str = Form(None),
    date: str = Form(...),
    time_found: str = Form(None),
    image: UploadFile = File(...),
    image_embedding: str = Form(...), # Received from the previous AI call
    matched_item_id: int = Form(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1. SAVE THE IMAGE FILE
    try:
        validate_upload_file_size(image, label="Main image")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        resolved_category = resolve_category_name(db, category_name=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    image_bytes = await image.read()
    await image.seek(0)
    save_path = save_file(image, resolved_category)
        
    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    
    # 2. SAVE TO PENDING
    try:
        search_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        normalized_image_embedding = json.dumps(get_image_embedding(search_img).tolist())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Image Error: {str(e)}")

    new_pending = models.PendingItem(
        item_name=item_name,
        category=category,
        description=description,
        location=location,
        brand=brand,
        color=color,
        date=date_obj,
        time_found=time_found,
        image_path=save_path,
        image_embedding=normalized_image_embedding,
        matched_item_id=matched_item_id,
        user_id=current_user.id
    )
    
    db.add(new_pending)

    db.commit()
    db.refresh(new_pending)

    # 4. NOTIFICATION
    notif_msg = f"Match Found! A {category} matches Lost Item #{matched_item_id}." if matched_item_id else f"New {category} reported at {location}."
    
    admin_notif = models.Notification(
        message=notif_msg,
        type="match" if matched_item_id else "new_report",
        related_id=new_pending.id,
        target_url="/admin/Found_Items_Report",
        is_read=False,
        created_at=datetime.now() 
    )
    
    db.add(admin_notif)

    if matched_item_id:
        matched_lost_item = db.query(models.Item).filter(
            models.Item.id == matched_item_id,
            models.Item.status == "lost",
            models.Item.archived == False
        ).first()

        if matched_lost_item:
            new_pending.matched_item_id = matched_lost_item.id
            possible_match_count = prepend_lost_possible_match(
                matched_lost_item,
                serialize_pending_found_match(new_pending, 0.55)
            )

            if matched_lost_item.user_id:
                reporter_name = format_user_display_name(current_user)
                db.add(models.Notification(
                    message=f"New possible match found: {reporter_name} submitted a found {category} that may match your lost item. You now have {possible_match_count} possible match(es). It is waiting for admin approval.",
                    type="student_match",
                    related_id=matched_lost_item.user_id,
                    target_url=f"/student/Lost-report?item_id={matched_lost_item.id}&show_match=1",
                    is_read=False,
                    created_at=datetime.utcnow()
                ))

    db.commit()
    
    return {
        "message": "Submitted successfully",
        "pending_id": new_pending.id,
        "item_code": format_item_code("pending_found", new_pending.id),
        "reported_by": format_user_display_name(current_user),
    }


@app.post("/api/lost-report-upload")
async def lost_report_upload(
    category: str = Form(...),
    description: str = Form(None),
    location: str = Form(...),
    date: str = Form(...),
    # Added these from your updated model
    brand: str = Form(None),
    color: str = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    # Added to identify which student is reporting
    current_user: models.User = Depends(get_current_user) 
):
    try:
        validate_upload_file_size(image, label="Main image")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 1. Process and Save File
    image_content = await image.read()
    await image.seek(0) 
    try:
        resolved_category = resolve_category_name(db, category_name=category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db_image_path = save_file(image, resolved_category)

    # 2. Generate Image Embedding
    try:
        img = Image.open(io.BytesIO(image_content)).convert("RGB")
        image_vec = get_image_embedding(img)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Image Error: {str(e)}")

    # 3. Generate Text Embedding
    # Added brand and color to the AI's "understanding" of the item
    description_text = (description or "").strip()
    text_query = f"a {color or ''} {brand or ''} {category} described as {description_text}".strip()
    text_vec = get_text_embedding(text_query)

    def normalize_match_value(value):
        return " ".join(str(value or "").strip().lower().split())

    # 4. AI COMPARISON LOGIC
    found_items = db.query(models.Item).filter(
        models.Item.status.ilike("found"),
        models.Item.archived == False,
        models.Item.image_embedding.isnot(None)
    ).all()

    best_match_id = None
    final_score = 0.0
    THRESHOLD = 0.55
    matched_found_item = None

    for item in found_items:
        try:
            stored_vec = np.array(json.loads(item.image_embedding)).flatten()
            
            # Multimodal Math
            img_sim = float(np.dot(image_vec, stored_vec))
            text_sim = float(np.dot(text_vec, stored_vec))
            current_score = (img_sim * 0.5) + (text_sim * 0.5)

            normalized_brand = normalize_match_value(brand)
            item_brand = normalize_match_value(item.brand)
            if normalized_brand and item_brand and normalized_brand == item_brand:
                current_score += 0.08
            elif normalized_brand and item_brand and normalized_brand != item_brand:
                current_score -= 0.12

            normalized_color = normalize_match_value(color)
            item_color = normalize_match_value(item.color)
            if normalized_color and item_color and normalized_color == item_color:
                current_score += 0.05
            elif normalized_color and item_color and normalized_color != item_color:
                current_score -= 0.20

            normalized_location = normalize_match_value(location)
            item_location = normalize_match_value(item.location)
            if normalized_location and item_location and (
                normalized_location in item_location or item_location in normalized_location
            ):
                current_score += 0.03

            if current_score > final_score:
                best_match_id = item.id
                final_score = current_score
                matched_found_item = item
        except Exception as e:
            continue

    ai_match_found = final_score >= THRESHOLD and matched_found_item is not None

    # 5. SAVE THE NEW LOST ITEM (Using all updated columns)
    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    
    new_lost_report = models.Item(
        status="lost",
        category=category,
        brand=brand,        # NEW
        color=color,        # NEW
        description=description,
        location=location,
        date=date_obj,
        image_path=db_image_path,
        image_embedding=json.dumps(image_vec.tolist()),
        user_id=current_user.id, # NEW
        is_matched=False,
        archived=False
    )

    db.add(new_lost_report)
    db.flush() 

    # 6. HANDLE THE "FOUND" ITEM, CLAIM, AND NOTIFICATIONS
    if ai_match_found and matched_found_item:
        # Create the automated claim
        match_percentage = f"{final_score * 100:.1f}%"
        new_claim = models.Claim(
            lost_item_id=new_lost_report.id,
            found_item_id=best_match_id,
            claimant_id=current_user.id, 
            similarity_score=match_percentage,
            status="pending"
        )
        db.add(new_claim)
        db.flush()

        # Admin Match Notification
        admin_notif = models.Notification(
            message=f"🔥 AI MATCH ({match_percentage}): Lost {category} ({brand}) vs Found #{best_match_id}",
            type="match",
            related_id=new_claim.id,
            target_url=f"/admin/Reports?report_type=claim&claim_id={new_claim.id}",
            is_read=False
        )
        db.add(admin_notif)
    else:
        # Standard Admin Notification for new submission
        report_notif = models.Notification(
            message=f"New Lost Report: {category} ({brand}) lost at {location}.",
            type="new_report",
            related_id=new_lost_report.id,
            target_url="/admin/Lost_Items_Report",
            is_read=False
        )
        db.add(report_notif)

    db.commit()
    db.refresh(new_lost_report)
    
    return {
        "status": "success", 
        "ai_match": ai_match_found, 
        "item_id": new_lost_report.id,
        "item_code": format_item_code("lost", new_lost_report.id, getattr(new_lost_report, "item_code", None)),
        "reported_by": format_user_display_name(current_user),
        "match_score": f"{final_score * 100:.1f}%" if ai_match_found else None,
        "is_matched": False
    }
    

@app.get("/api/messages/history/{other_user_id}")
async def get_chat_history(
    other_user_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    unread_messages = db.query(models.Message).filter(
        models.Message.sender_id == other_user_id,
        models.Message.recipient_id == current_user.id,
        func.trim(func.lower(models.Message.status)) == "unread"
    ).all()

    for message in unread_messages:
        message.status = "read"

    if unread_messages:
        db.commit()

    # This finds all messages where:
    # (I sent to them) OR (They sent to me)
    messages = db.query(models.Message).filter(
        or_(
            (models.Message.sender_id == current_user.id) & (models.Message.recipient_id == other_user_id),
            (models.Message.sender_id == other_user_id) & (models.Message.recipient_id == current_user.id)
        )
    ).order_by(models.Message.created_at.asc()).all()
    
    return messages

@app.post("/api/messages/read/{other_user_id}")
async def mark_chat_as_read(
    other_user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    unread_messages = db.query(models.Message).filter(
        models.Message.sender_id == other_user_id,
        models.Message.recipient_id == current_user.id,
        func.trim(func.lower(models.Message.status)) == "unread"
    ).all()

    for message in unread_messages:
        message.status = "read"

    db.commit()
    return {"success": True, "updated": len(unread_messages)}

@app.delete("/api/messages/conversation/{other_user_id}")
async def delete_conversation(
    other_user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    deleted_count = db.query(models.Message).filter(
        or_(
            (models.Message.sender_id == current_user.id) & (models.Message.recipient_id == other_user_id),
            (models.Message.sender_id == other_user_id) & (models.Message.recipient_id == current_user.id)
        )
    ).delete(synchronize_session=False)

    db.commit()
    return {"success": True, "deleted": deleted_count}

@app.post("/api/messages/send")
async def send_message(
    recipient_id: int = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    recipient = db.query(models.User).filter(models.User.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")

    # 1. Save the actual Message
    new_msg = models.Message(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        content=content
    )
    db.add(new_msg)
    db.flush() 

    # 2. TRIGGER NOTIFICATION (Using existing related_id column)
    if not current_user.is_admin:
        # Student sending to Admin
        new_notif = models.Notification(
            message=f"New message from {current_user.full_name or current_user.email}",
            type="chat",
            related_id=0,  # 0 signifies an Admin-bound notification
            target_url="/admin/Messages",
            is_read=False
        )
        db.add(new_notif)
    
    else:
        admin_name = current_user.full_name or current_user.email or "LookFor Admin"
        new_notif = models.Notification(
            message=f"{admin_name} sent you a message.",
            type="chat",
            related_id=recipient_id,
            target_url="/admin/Messages" if recipient.is_admin else "/student/Messages",
            is_read=False
        )
        db.add(new_notif)

    db.commit()
    return {"status": "success"}

@app.get("/api/admin/claims")
def get_claims(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    # Join Claim with Item to get both Lost and Found details in one go
    claims = db.query(models.Claim).order_by(models.Claim.created_at.desc()).all()
    
    if not claims:
        print("DEBUG: No claims found in the database.")
        return []

    results = []
    for claim in claims:
        lost = db.query(models.Item).filter(models.Item.id == claim.lost_item_id).first()
        found = db.query(models.Item).filter(models.Item.id == claim.found_item_id).first()
        proof = db.query(models.ClaimProof).filter(models.ClaimProof.claim_id == claim.id).first()
        
        if not found:
            continue

        claimant_name = format_user_display_name(claim.claimant)

        results.append({
            "id": claim.id,
            "similarity": claim.similarity_score or "Manual Match",
            "status": claim.status,
            "lost_item": {
                "category": lost.category if lost else "No lost report",
                "image": public_file_url(lost.image_path) if lost else None
            },
            "found_item": {"category": found.category, "image": public_file_url(found.image_path)},
            "claimant": {
                "name": claimant_name,
                "student_no": proof.claimant_student_no if proof else None,
                "id_image": public_file_url(proof.id_image_path) if proof else None,
                "has_proof": bool(proof and proof.id_image_path)
            },
            "report": build_claim_report_payload(claim, db)
        })
    return results


def sync_claim_item_match_flags(db: Session, lost_item_id: int | None, found_item_id: int | None):
    if lost_item_id:
        lost_item = db.query(models.Item).filter(models.Item.id == lost_item_id).first()
        if lost_item:
            lost_has_active_claim = db.query(models.Claim).filter(
                models.Claim.lost_item_id == lost_item_id,
                models.Claim.status.in_(["pending", "approved"])
            ).first()
            lost_item.is_matched = bool(lost_has_active_claim)

    if found_item_id:
        found_item = db.query(models.Item).filter(models.Item.id == found_item_id).first()
        if found_item:
            found_has_active_claim = db.query(models.Claim).filter(
                models.Claim.found_item_id == found_item_id,
                models.Claim.status.in_(["pending", "approved"])
            ).first()
            found_item.is_matched = bool(found_has_active_claim)


def format_user_display_name(user: models.User | None) -> str:
    if not user:
        return "Unknown User"

    return (
        user.full_name
        or " ".join(
            part for part in [
                user.first_name,
                user.middle_name,
                user.last_name,
            ] if part
        ).strip()
        or "Unknown User"
    )


def apply_claim_decision(
    db: Session,
    claim: models.Claim,
    action: str
):
    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Unsupported claim action")

    if action == "approve":
        claim.status = "approved"
        claim.admin_decision_date = datetime.utcnow()

        lost_item = db.query(models.Item).filter(models.Item.id == claim.lost_item_id).first()
        found_item = db.query(models.Item).filter(models.Item.id == claim.found_item_id).first()
        if lost_item:
            lost_item.is_matched = True
        if found_item:
            found_item.is_matched = True

        db.query(models.Claim).filter(
            models.Claim.id != claim.id,
            or_(
                models.Claim.lost_item_id == claim.lost_item_id,
                models.Claim.found_item_id == claim.found_item_id
            ),
            models.Claim.status == "pending"
        ).update(
            {
                models.Claim.status: "rejected",
                models.Claim.admin_decision_date: datetime.utcnow()
            },
            synchronize_session=False
        )
    else:
        claim.status = "rejected"
        claim.admin_decision_date = datetime.utcnow()
        sync_claim_item_match_flags(db, claim.lost_item_id, claim.found_item_id)


def build_claim_report_payload(
    claim: models.Claim,
    db: Session,
    decision_report: models.ClaimDecisionReport | None = None
):
    lost = claim.lost_item or db.query(models.Item).filter(models.Item.id == claim.lost_item_id).first()
    found = claim.found_item or db.query(models.Item).filter(models.Item.id == claim.found_item_id).first()
    proof = claim.proof or db.query(models.ClaimProof).filter(models.ClaimProof.claim_id == claim.id).first()
    report = decision_report
    if report is None:
        report = db.query(models.ClaimDecisionReport).filter(
            models.ClaimDecisionReport.claim_id == claim.id
        ).first()

    claimant = claim.claimant
    claimant_name = format_user_display_name(claimant)
    claimant_student_no = (
        proof.claimant_student_no
        if proof and proof.claimant_student_no
        else (claimant.student_no if claimant else None)
    )
    claimant_department_or_course = None
    if claimant:
        claimant_department_or_course = claimant.course or claimant.department

    item_name = None
    if lost:
        item_name = getattr(lost, "item_name", None) or lost.category
    elif found:
        item_name = getattr(found, "item_name", None) or found.category

    lost_item_id = getattr(lost, "item_id", None) or (lost.id if lost else None)
    found_item_id = getattr(found, "item_id", None) or (found.id if found else None)
    lost_item_code = getattr(lost, "item_code", None) if lost else None
    found_item_code = getattr(found, "item_code", None) if found else None
    status_label = "Claimed" if claim.status == "approved" else (claim.status.title() if claim.status else "Pending")

    return {
        "claim_id": claim.id,
        "lost_item_id": lost_item_id,
        "found_item_id": found_item_id,
        "lost_item_code": lost_item_code,
        "found_item_code": found_item_code,
        "item_name": item_name or "Unspecified Item",
        "date_claimed": claim.created_at.isoformat() if claim.created_at else None,
        "status": status_label,
        "claimant": {
            "full_name": claimant_name,
            "student_employee_id": claimant_student_no or "Not available",
            "department_course": claimant_department_or_course or "Not available",
            "proof_id_image": public_file_url(proof.id_image_path) if proof else None,
        },
        "item_description": {
            "item_id": lost_item_id or found_item_id,
            "item_code": lost_item_code or found_item_code,
            "item_name": (
                getattr(lost, "item_name", None)
                or (lost.category if lost else None)
                or getattr(found, "item_name", None)
                or (found.category if found else None)
                or "Unspecified Item"
            ),
            "brand": (
                (lost.brand if lost and lost.brand else None)
                or (found.brand if found and found.brand else None)
                or "Not specified"
            ),
            "color": (
                (lost.color if lost and lost.color else None)
                or (found.color if found and found.color else None)
                or "Not specified"
            ),
            "date_lost": (
                lost.date.isoformat() if lost and lost.date
                else (found.date.isoformat() if found and found.date else None)
            ),
            "location_lost": (
                (lost.location if lost and lost.location else None)
                or (found.location if found and found.location else None)
                or "Not specified"
            ),
        },
        "matched_item": {
            "category": found.category if found else "Unknown",
            "image": public_file_url(found.image_path) if found else None,
        },
        "report_image": public_file_url(report.report_image_path) if report else None,
        "report_exists": bool(report),
    }


@app.post("/api/admin/claims/{claim_id}/approve")
def approve_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    claim = db.query(models.Claim).filter(models.Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    apply_claim_decision(db, claim, "approve")

    db.commit()
    return {"status": "success", "message": "Claim approved"}


@app.post("/api/admin/claims/{claim_id}/reject")
def reject_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    claim = db.query(models.Claim).filter(models.Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    apply_claim_decision(db, claim, "reject")

    db.commit()
    return {"status": "success", "message": "Claim rejected"}


@app.post("/api/admin/claims/{claim_id}/decision-report")
async def create_claim_decision_report(
    claim_id: int,
    action: str = Form(...),
    report_image: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    claim = db.query(models.Claim).filter(models.Claim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    action = (action or "").strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Action must be approve or reject")

    report = db.query(models.ClaimDecisionReport).filter(
        models.ClaimDecisionReport.claim_id == claim_id
    ).first()
    if not report:
        report = models.ClaimDecisionReport(
            claim_id=claim_id,
            created_by_admin_id=current_admin.id,
        )
        db.add(report)

    if report_image and report_image.filename:
        report.report_image_path = save_file(report_image, "claim-reports")

    report.decision_status = "approved" if action == "approve" else "rejected"
    report.created_by_admin_id = current_admin.id
    report.created_at = datetime.utcnow()

    apply_claim_decision(db, claim, action)

    db.commit()
    db.refresh(claim)

    return {
        "status": "success",
        "message": f"Claim {action}d and report saved",
        "report": build_claim_report_payload(claim, db)
    }


@app.get("/api/admin/report-module")
def get_report_module_data(
    report_type: str = Query("all"),
    date_range: str = Query(""),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    category: str = Query(""),
    location: str = Query(""),
    search: str = Query(""),
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    normalized_report_type = " ".join(str(report_type or "all").strip().lower().replace("-", "_").split())
    report_type_aliases = {
        "lost and found": "lost_found",
        "lost & found": "lost_found",
        "lostfound": "lost_found",
        "lost_found_items": "lost_found",
    }
    report_type = report_type_aliases.get(normalized_report_type, normalized_report_type)
    valid_report_types = {"all", "lost", "found", "lost_found", "claim", "confiscated", "disposal"}
    if report_type not in valid_report_types:
        report_type = "all"

    def normalize(value) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def display_name(user: models.User | None) -> str:
        return format_user_display_name(user)

    def item_report_id(item: models.Item | None) -> int | None:
        if not item:
            return None
        return getattr(item, "item_id", None) or item.id

    def item_report_code(item: models.Item | None) -> str | None:
        if not item:
            return None
        report_id = item_report_id(item)
        if getattr(item, "item_code", None):
            return item.item_code
        prefix = "LOST" if item.status == "lost" else ("FOUND" if item.status == "found" else "ITEM")
        return f"{prefix}-{report_id:06d}" if report_id is not None else None

    def parse_date(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.strptime(value.strip(), "%Y-%m-%d").date()
            except ValueError:
                return None
        return None

    def in_selected_range(value) -> bool:
        record_date = parse_date(value)
        if not record_date:
            return True

        today = datetime.utcnow().date()
        if date_range == "today":
            return record_date == today
        if date_range == "7days":
            return record_date >= today - timedelta(days=7)
        if date_range == "30days":
            return record_date >= today - timedelta(days=30)
        if date_range == "3months":
            return record_date >= today - timedelta(days=90)
        if date_range == "custom":
            start = parse_date(start_date)
            end = parse_date(end_date)
            if start and record_date < start:
                return False
            if end and record_date > end:
                return False
        return True

    rows: list[dict] = []

    if report_type in {"all", "lost", "found", "lost_found"}:
        item_query = (
            db.query(models.Item)
            .options(
                load_only(
                    models.Item.id,
                    models.Item.item_id,
                    models.Item.item_code,
                    models.Item.status,
                    models.Item.category,
                    models.Item.created_at,
                    models.Item.report_owner_user_id,
                    models.Item.report_owner_name,
                    models.Item.report_owner_group,
                    models.Item.brand,
                    models.Item.color,
                    models.Item.archived,
                    models.Item.location,
                    models.Item.date,
                    models.Item.user_id,
                    models.Item.description,
                    models.Item.image_path,
                ),
                joinedload(models.Item.owner).load_only(
                    models.User.id,
                    models.User.full_name,
                    models.User.first_name,
                    models.User.middle_name,
                    models.User.last_name,
                ),
            )
            .filter(models.Item.archived == False)
        )
        if report_type == "lost":
            item_query = item_query.filter(models.Item.status == "lost")
        elif report_type == "found":
            item_query = item_query.filter(models.Item.status == "found")
        elif report_type == "lost_found":
            item_query = item_query.filter(models.Item.status.in_(["lost", "found"]))

        for item in item_query.order_by(models.Item.created_at.desc()).all():
            owner = item.owner
            report_item_id = item_report_id(item)
            report_item_code = item_report_code(item)
            reported_person_name = str(getattr(item, "report_owner_name", "") or "").strip()
            reported_person_group = str(getattr(item, "report_owner_group", "") or "").strip()
            reported_by = reported_person_name or display_name(owner)
            rows.append({
                "row_type": item.status or "item",
                "row_id": report_item_code or f"ITEM-{report_item_id}",
                "item_id": report_item_id,
                "item_code": report_item_code,
                "item": item.category or "Unspecified Item",
                "category": item.category or "Uncategorized",
                "location": item.location or "Not specified",
                "status": "Lost" if item.status == "lost" else "Found",
                "date": item.date.isoformat() if item.date else (item.created_at.isoformat() if item.created_at else None),
                "reported_by": reported_by,
                "image_path": public_file_url(item.image_path),
                "details": {
                    "Item Code": report_item_code or "Not specified",
                    "Item ID": report_item_id,
                    "Title": item.category or "Unspecified Item",
                    "Type": "Lost Item" if item.status == "lost" else "Found Item",
                    "Category": item.category or "Uncategorized",
                    "Brand": item.brand or "Not specified",
                    "Color": item.color or "Not specified",
                    "Location": item.location or "Not specified",
                    "Description": item.description or "No description provided.",
                    "Reported By": reported_by,
                    "Section / Role": reported_person_group or "Not specified",
                    "Entered By": display_name(owner),
                    "Date": item.date.isoformat() if item.date else "Not specified",
                },
                "claim_payload": None,
            })

    if report_type in {"all", "claim"}:
        claim_query = (
            db.query(models.Claim)
            .options(
                load_only(
                    models.Claim.id,
                    models.Claim.lost_item_id,
                    models.Claim.found_item_id,
                    models.Claim.claimant_id,
                    models.Claim.status,
                    models.Claim.created_at,
                ),
                joinedload(models.Claim.lost_item).load_only(
                    models.Item.id,
                    models.Item.item_id,
                    models.Item.item_code,
                    models.Item.category,
                    models.Item.brand,
                    models.Item.color,
                    models.Item.date,
                    models.Item.location,
                ),
                joinedload(models.Claim.found_item).load_only(
                    models.Item.id,
                    models.Item.item_id,
                    models.Item.item_code,
                    models.Item.category,
                    models.Item.brand,
                    models.Item.color,
                    models.Item.date,
                    models.Item.location,
                    models.Item.image_path,
                ),
                joinedload(models.Claim.claimant).load_only(
                    models.User.id,
                    models.User.full_name,
                    models.User.first_name,
                    models.User.middle_name,
                    models.User.last_name,
                    models.User.student_no,
                    models.User.course,
                    models.User.department,
                ),
                joinedload(models.Claim.proof).load_only(
                    models.ClaimProof.claim_id,
                    models.ClaimProof.claimant_student_no,
                    models.ClaimProof.id_image_path,
                ),
            )
            .order_by(models.Claim.created_at.desc())
        )
        claims = claim_query.all()
        claim_ids = [claim.id for claim in claims]
        decision_reports = {}
        if claim_ids:
            decision_reports = {
                report.claim_id: report
                for report in db.query(models.ClaimDecisionReport)
                .filter(models.ClaimDecisionReport.claim_id.in_(claim_ids))
                .all()
            }

        for claim in claims:
            report = build_claim_report_payload(claim, db, decision_reports.get(claim.id))
            rows.append({
                "row_type": "claim",
                "row_id": f"CL-{claim.id}",
                "item_id": report["item_description"]["item_id"],
                "item_code": report["item_description"]["item_code"],
                "item": report["item_name"],
                "category": report["item_description"]["item_name"],
                "location": report["item_description"]["location_lost"],
                "status": report["status"],
                "date": report["date_claimed"],
                "reported_by": report["claimant"]["full_name"],
                "image_path": report["matched_item"]["image"],
                "details": {
                    "Claim ID": claim.id,
                    "Lost Item Code": report["lost_item_code"] or "Not specified",
                    "Lost Item ID": report["lost_item_id"] or "Not specified",
                    "Found Item Code": report["found_item_code"] or "Not specified",
                    "Found Item ID": report["found_item_id"] or "Not specified",
                    "Item name": report["item_name"],
                    "Status": report["status"],
                    "Date claimed": report["date_claimed"] or "Not specified",
                    "Claimant": report["claimant"]["full_name"],
                    "Student/Employee ID": report["claimant"]["student_employee_id"],
                    "Department/Course": report["claimant"]["department_course"],
                    "Brand": report["item_description"]["brand"],
                    "Color": report["item_description"]["color"],
                    "Date Lost": report["item_description"]["date_lost"] or "Not specified",
                    "Location Lost": report["item_description"]["location_lost"],
                },
                "claim_payload": report,
                "claim_id": claim.id,
            })

    if report_type in {"all", "confiscated"}:
        for confiscated in (
            db.query(models.ConfiscatedItem)
            .options(
                load_only(
                    models.ConfiscatedItem.id,
                    models.ConfiscatedItem.category,
                    models.ConfiscatedItem.brand,
                    models.ConfiscatedItem.color,
                    models.ConfiscatedItem.date_confiscated,
                    models.ConfiscatedItem.location,
                    models.ConfiscatedItem.estimated_time,
                    models.ConfiscatedItem.reason,
                    models.ConfiscatedItem.image_path,
                    models.ConfiscatedItem.created_at,
                )
            )
            .order_by(models.ConfiscatedItem.created_at.desc())
            .all()
        ):
            rows.append({
                "row_type": "confiscated",
                "row_id": f"CONF-{confiscated.id}",
                "item_id": confiscated.id,
                "item_code": f"CONF-{confiscated.id:06d}",
                "item": confiscated.category or "Confiscated Item",
                "category": confiscated.category or "Uncategorized",
                "location": confiscated.location or "Not specified",
                "status": "Confiscated",
                "date": confiscated.date_confiscated.isoformat() if confiscated.date_confiscated else (confiscated.created_at.isoformat() if confiscated.created_at else None),
                "reported_by": "Admin",
                "image_path": public_file_url(confiscated.image_path),
                "details": {
                    "Item ID": confiscated.id,
                    "Item Code": f"CONF-{confiscated.id:06d}",
                    "Title": confiscated.category or "Confiscated Item",
                    "Reason": confiscated.reason or "Not specified",
                    "Brand": confiscated.brand or "Not specified",
                    "Color": confiscated.color or "Not specified",
                    "Location": confiscated.location or "Not specified",
                    "Estimated Time": confiscated.estimated_time or "Not specified",
                    "Date": confiscated.date_confiscated.isoformat() if confiscated.date_confiscated else "Not specified",
                },
                "claim_payload": None,
            })

    if report_type in {"all", "disposal"}:
        reference_items = (
            db.query(models.ReferenceItem)
            .options(
                load_only(
                    models.ReferenceItem.id,
                    models.ReferenceItem.category,
                    models.ReferenceItem.status,
                    models.ReferenceItem.brand,
                    models.ReferenceItem.color,
                    models.ReferenceItem.location,
                    models.ReferenceItem.user_id,
                    models.ReferenceItem.deleted_reason,
                    models.ReferenceItem.deleted_at,
                    models.ReferenceItem.image_path,
                )
            )
            .order_by(models.ReferenceItem.deleted_at.desc())
            .all()
        )
        owner_ids = {ref.user_id for ref in reference_items if ref.user_id}
        reference_owners = {}
        if owner_ids:
            reference_owners = {
                user.id: user
                for user in db.query(models.User).filter(models.User.id.in_(owner_ids)).all()
            }

        for ref in reference_items:
            owner = reference_owners.get(ref.user_id)
            rows.append({
                "row_type": "disposal",
                "row_id": f"REF-{ref.id}",
                "item_id": ref.id,
                "item_code": f"REF-{ref.id:06d}",
                "item": ref.category or "Disposed Item",
                "category": ref.category or "Uncategorized",
                "location": ref.location or "Not specified",
                "status": "Disposed",
                "date": ref.deleted_at.isoformat() if ref.deleted_at else None,
                "reported_by": display_name(owner),
                "image_path": public_file_url(ref.image_path),
                "details": {
                    "Item ID": ref.id,
                    "Item Code": f"REF-{ref.id:06d}",
                    "Title": ref.category or "Disposed Item",
                    "Status": ref.status or "Unknown",
                    "Deleted Reason": ref.deleted_reason or "Not specified",
                    "Brand": ref.brand or "Not specified",
                    "Color": ref.color or "Not specified",
                    "Location": ref.location or "Not specified",
                    "Deleted At": ref.deleted_at.isoformat() if ref.deleted_at else "Not specified",
                },
                "claim_payload": None,
            })

    filtered_rows = []
    normalized_category = normalize(category)
    normalized_location = normalize(location)
    normalized_search = normalize(search)

    for row in rows:
        if normalized_category and normalize(row["category"]) != normalized_category:
            continue
        if normalized_location and normalized_location not in normalize(row["location"]):
            continue
        if normalized_search:
            haystack = normalize(" ".join([
                str(row["row_id"]),
                str(row.get("item_id") or ""),
                str(row["item"]),
                str(row["category"]),
                str(row["location"]),
                str(row["status"]),
                str(row["reported_by"]),
            ]))
            if normalized_search not in haystack:
                continue
        if not in_selected_range(row["date"]):
            continue
        filtered_rows.append(row)

    summary = {
        "total": len(filtered_rows),
        "lost": sum(1 for row in filtered_rows if row["row_type"] == "lost"),
        "found": sum(1 for row in filtered_rows if row["row_type"] == "found"),
        "confiscated": sum(1 for row in filtered_rows if row["row_type"] == "confiscated"),
        "claim": sum(1 for row in filtered_rows if row["row_type"] == "claim"),
    }

    category_options = sorted({row["category"] for row in rows if row["category"] and row["category"] != "Uncategorized"})
    location_options = sorted({row["location"] for row in rows if row["location"] and row["location"] != "Not specified"})

    return {
        "summary": summary,
        "rows": filtered_rows,
        "filters": {
            "categories": category_options,
            "locations": location_options,
        },
    }




@app.post("/api/admin/manual-claim")
def create_manual_claim(
    found_item_id: int = Form(...),
    lost_item_id: int = Form(...),
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    found_item = db.query(models.Item).filter(models.Item.id == found_item_id).first()
    lost_item = db.query(models.Item).filter(models.Item.id == lost_item_id).first()

    if not found_item or not lost_item:
        raise HTTPException(status_code=404, detail="Lost or found item not found")

    if found_item.status != "found" or lost_item.status != "lost":
        raise HTTPException(status_code=400, detail="Items must be one found item and one lost item")

    if found_item.archived or lost_item.archived:
        raise HTTPException(status_code=400, detail="Archived items cannot be used for manual claims")

    found_category = (found_item.category or "").strip().lower()
    lost_category = (lost_item.category or "").strip().lower()
    if found_category and lost_category and found_category != lost_category:
        raise HTTPException(status_code=400, detail="Manual claims can only be created for items in the same category")

    existing_active_claim = db.query(models.Claim).filter(
        models.Claim.lost_item_id == lost_item_id,
        models.Claim.found_item_id == found_item_id,
        models.Claim.status.in_(["pending", "approved"])
    ).first()
    if existing_active_claim:
        lost_item.is_matched = True
        found_item.is_matched = True
        db.commit()
        return {
            "status": "success",
            "message": "A claim for this pair already exists.",
            "claim_id": existing_active_claim.id,
            "existing": True
        }

    conflicting_found_claim = db.query(models.Claim).filter(
        models.Claim.found_item_id == found_item_id,
        models.Claim.status == "approved"
    ).first()
    if conflicting_found_claim:
        raise HTTPException(status_code=409, detail="This found item is already part of an approved claim")

    conflicting_lost_claim = db.query(models.Claim).filter(
        models.Claim.lost_item_id == lost_item_id,
        models.Claim.status == "approved"
    ).first()
    if conflicting_lost_claim:
        raise HTTPException(status_code=409, detail="This lost item is already part of an approved claim")

    new_claim = models.Claim(
        lost_item_id=lost_item_id,
        found_item_id=found_item_id,
        claimant_id=lost_item.user_id or current_admin.id,
        similarity_score="Manual Match",
        status="pending",
    )
    lost_item.is_matched = True
    found_item.is_matched = True
    db.add(new_claim)
    db.add(
        models.Notification(
            message=f"Manual claim created for Lost Item #{lost_item_id} and Found Item #{found_item_id}.",
            type="match",
            related_id=lost_item_id,
            target_url="/admin/Claim-Management",
            is_read=False
        )
    )
    db.commit()
    db.refresh(new_claim)

    return {"status": "success", "message": "Manual claim created", "claim_id": new_claim.id}


@app.post("/api/admin/direct-claim")
def create_direct_claim(
    found_item_id: int = Form(...),
    claimant_user_id: int = Form(...),
    claim_id_image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin)
):
    found_item = db.query(models.Item).filter(models.Item.id == found_item_id).first()
    claimant = db.query(models.User).filter(models.User.id == claimant_user_id).first()

    if not found_item:
        raise HTTPException(status_code=404, detail="Found item not found")
    if found_item.status != "found":
        raise HTTPException(status_code=400, detail="Only found items can be claimed directly")
    if found_item.archived:
        raise HTTPException(status_code=400, detail="Archived items cannot be claimed directly")
    if not claimant:
        raise HTTPException(status_code=404, detail="Claimant not found")

    existing_active_claim = db.query(models.Claim).filter(
        models.Claim.found_item_id == found_item_id,
        models.Claim.claimant_id == claimant_user_id,
        models.Claim.lost_item_id.is_(None),
        models.Claim.status.in_(["pending", "approved"])
    ).first()
    if existing_active_claim:
        found_item.is_matched = True
        db.commit()
        return {
            "status": "success",
            "message": "A direct claim for this user and item already exists.",
            "claim_id": existing_active_claim.id,
            "existing": True
        }

    proof_image_path = None
    if claim_id_image and claim_id_image.filename:
        proof_image_path = save_file(claim_id_image, "claim-proofs")

    new_claim = models.Claim(
        lost_item_id=None,
        found_item_id=found_item_id,
        claimant_id=claimant_user_id,
        similarity_score="Office Claim",
        status="pending",
    )
    found_item.is_matched = True
    db.add(new_claim)
    db.flush()

    if proof_image_path:
        db.add(
            models.ClaimProof(
                claim_id=new_claim.id,
                claimant_user_id=claimant_user_id,
                claimant_student_no=claimant.student_no,
                id_image_path=proof_image_path
            )
        )

    db.add(
        models.Notification(
            message=f"Office direct claim created for Found Item #{found_item_id}.",
            type="match",
            related_id=found_item_id,
            target_url="/admin/Claim-Management",
            is_read=False
        )
    )
    db.commit()
    db.refresh(new_claim)

    return {"status": "success", "message": "Direct office claim created", "claim_id": new_claim.id}


# main.py or student_routes.py
@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    categories = db.query(models.Category).all()
    return [{"id": c.id, "name": c.name} for c in categories]
@app.get("/api/announcements")
async def get_announcements(db: Session = Depends(get_db)):
    # Return only the current active announcement.
    latest = db.query(models.Announcement).order_by(models.Announcement.created_at.desc()).first()
    if not latest:
        return []

    return [{
        "id": latest.id,
        "title": latest.title or "",
        "content": latest.content or "",
        "image_url": public_file_url(latest.image_url, "/static/photos/placeholder.png"),
        "created_at": latest.created_at.isoformat() if latest.created_at else None,
    }]

@app.get("/api/students")
def get_students(
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    students = db.query(models.User).filter(models.User.is_admin == False).all()
    
    result = []
    for s in students:
        # Check for unread messages
        has_unread = db.query(models.Message).filter(
            models.Message.sender_id == s.id,
            models.Message.status == "unread"
        ).first() is not None
        
        result.append({
            "id": s.id,
            "email": s.email,
            "has_unread": has_unread
        })
    return result
    
def save_and_replace_file(new_file: UploadFile, old_path: str = None):
    """Saves new file and deletes the old one from the system."""
    
    # 1. Delete the old file if it exists
    if old_path:
        # Convert database path (static/uploads/file.png) back to physical system path
        full_old_path = os.path.join(BASE_DIR, old_path.replace("/", os.sep))
        if os.path.exists(full_old_path):
            try:
                os.remove(full_old_path)
                print(f"Deleted old file: {full_old_path}")
            except Exception as e:
                print(f"Error deleting old file: {e}")

    # 2. Save the new file
    filename = f"{uuid()}_{new_file.filename}"
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(new_file.file.read())

    # 3. Return the web-friendly path for the database
    # Result looks like: static/uploads/uuid_name.png
    return os.path.join("static", "uploads", filename).replace("\\", "/")

    
@app.post("/admin/api/update-content/bulk")
async def update_bulk_content(
    hero_title: str = Form(None),
    hero_desc: str = Form(None),
    app_eyebrow: str = Form(None),
    app_button_label: str = Form(None),
    app_notice: str = Form(None),
    app_apk_url: str = Form(None),
    faq_title: str = Form(None),
    faq_desc: str = Form(None),
    why_title: str = Form(None),
    why_desc_1: str = Form(None),
    why_desc_2: str = Form(None),
    why_img: UploadFile = File(None), 
    cta_title: str = Form(None),      # Added
    cta_desc: str = Form(None),       # Added
    cta_img: UploadFile = File(None),  # Added
    reunite_title: str = Form(None),   # Added
    reunite_desc: str = Form(None),  # Added
    how_it_works_title: str = Form(None),  # Added
    how_it_works_desc: str = Form(None),  # Added
    features_main_title: str = Form(None),
    features_main_sub: str = Form(None),
    feature_1_title: str = Form(None),
    feature_1_desc: str = Form(None),
    feature_1_img: UploadFile = File(None),
    feature_2_title: str = Form(None),
    feature_2_desc: str = Form(None),
    feature_2_img: UploadFile = File(None),
    feature_3_title: str = Form(None),
    feature_3_desc: str = Form(None),
    feature_3_img: UploadFile = File(None),
    feature_4_title: str = Form(None),
    feature_4_desc: str = Form(None),
    feature_4_img: UploadFile = File(None),
    explore_hero_title: str = Form(None),
    explore_hero_desc: str = Form(None),
    explore_student_title: str = Form(None),
    explore_student_desc: str = Form(None),
    explore_student_1_title: str = Form(None),
    explore_student_1_desc: str = Form(None),
    explore_student_1_img: UploadFile = File(None),
    explore_student_2_title: str = Form(None),
    explore_student_2_desc: str = Form(None),
    explore_student_2_img: UploadFile = File(None),
    explore_student_3_title: str = Form(None),
    explore_student_3_desc: str = Form(None),
    explore_student_3_img: UploadFile = File(None),
    explore_admin_title: str = Form(None),
    explore_admin_desc: str = Form(None),
    explore_admin_1_title: str = Form(None),
    explore_admin_1_desc: str = Form(None),
    explore_admin_1_img: UploadFile = File(None),
    explore_admin_2_title: str = Form(None),
    explore_admin_2_desc: str = Form(None),
    explore_admin_2_img: UploadFile = File(None),
    explore_admin_3_title: str = Form(None),
    explore_admin_3_desc: str = Form(None),
    explore_admin_3_img: UploadFile = File(None),
    explore_cta_title: str = Form(None),
    explore_cta_desc: str = Form(None),
    about_hero_title: str = Form(None),
    about_hero_desc: str = Form(None),
    about_benefits_title: str = Form(None),
    about_benefits_desc: str = Form(None),
    about_benefit_1_title: str = Form(None),
    about_benefit_1_desc: str = Form(None),
    about_benefit_1_img: UploadFile = File(None),
    about_benefit_2_title: str = Form(None),
    about_benefit_2_desc: str = Form(None),
    about_benefit_2_img: UploadFile = File(None),
    about_benefit_3_title: str = Form(None),
    about_benefit_3_desc: str = Form(None),
    about_benefit_3_img: UploadFile = File(None),
    about_clip_title: str = Form(None),
    about_clip_desc: str = Form(None),
    about_clip_1_title: str = Form(None),
    about_clip_1_desc: str = Form(None),
    about_clip_1_img: UploadFile = File(None),
    about_clip_2_title: str = Form(None),
    about_clip_2_desc: str = Form(None),
    about_clip_2_img: UploadFile = File(None),
    about_clip_3_title: str = Form(None),
    about_clip_3_desc: str = Form(None),
    about_clip_3_img: UploadFile = File(None),
    about_system_title: str = Form(None),
    about_system_desc: str = Form(None),
    about_system_1_title: str = Form(None),
    about_system_1_desc: str = Form(None),
    about_system_1_img: UploadFile = File(None),
    about_system_2_title: str = Form(None),
    about_system_2_desc: str = Form(None),
    about_system_2_img: UploadFile = File(None),
    about_system_3_title: str = Form(None),
    about_system_3_desc: str = Form(None),
    about_system_3_img: UploadFile = File(None),
    about_system_graphic: UploadFile = File(None),
    about_cta_title: str = Form(None),
    about_cta_desc: str = Form(None),
    about_cta_img: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    try:
        async def upsert_landing_section(section_key: str, title: str = None, description: str = None, image: UploadFile = None):
            section = db.query(models.LandingContent).filter(models.LandingContent.section_key == section_key).first()
            if not section:
                section = models.LandingContent(section_key=section_key)
                db.add(section)

            section.title = title
            section.description = description

            if image and image.filename:
                if section.image_path:
                    old_physical_path = os.path.join(BASE_DIR, section.image_path.replace("/", os.sep))
                    if os.path.exists(old_physical_path):
                        os.remove(old_physical_path)

                ext = image.filename.split(".")[-1]
                new_filename = f"{uuid4()}.{ext}"
                new_physical_path = os.path.join(UPLOAD_FOLDER, new_filename)

                with open(new_physical_path, "wb") as buffer:
                    buffer.write(await image.read())

                section.image_path = f"static/uploads/{new_filename}"

            return section

        # --- 1. HANDLE HERO SECTION ---
        await upsert_landing_section("hero", hero_title, hero_desc)
        await upsert_landing_section(
            "app_download",
            app_eyebrow,
            f"{app_button_label or ''}|||{app_notice or ''}|||{app_apk_url or ''}",
        )
        await upsert_landing_section("faq", faq_title, faq_desc)

        # --- 2. HANDLE WHY CHOOSE US SECTION ---
        await upsert_landing_section("why_choose_us", why_title, f"{why_desc_1}|||{why_desc_2}", why_img)

        # --- 4. HANDLE CTA FEATURE SECTION ---
        await upsert_landing_section("cta-feature", cta_title, cta_desc, cta_img)
        await upsert_landing_section("reunite", reunite_title, reunite_desc)
        await upsert_landing_section("how_it_works", how_it_works_title, how_it_works_desc)
        await upsert_landing_section("features_main", features_main_title, features_main_sub)
        await upsert_landing_section("feature_1", feature_1_title, feature_1_desc, feature_1_img)
        await upsert_landing_section("feature_2", feature_2_title, feature_2_desc, feature_2_img)
        await upsert_landing_section("feature_3", feature_3_title, feature_3_desc, feature_3_img)
        await upsert_landing_section("feature_4", feature_4_title, feature_4_desc, feature_4_img)
        await upsert_landing_section("explore_hero", explore_hero_title, explore_hero_desc)
        await upsert_landing_section("explore_student_section", explore_student_title, explore_student_desc)
        await upsert_landing_section("explore_student_1", explore_student_1_title, explore_student_1_desc, explore_student_1_img)
        await upsert_landing_section("explore_student_2", explore_student_2_title, explore_student_2_desc, explore_student_2_img)
        await upsert_landing_section("explore_student_3", explore_student_3_title, explore_student_3_desc, explore_student_3_img)
        await upsert_landing_section("explore_admin_section", explore_admin_title, explore_admin_desc)
        await upsert_landing_section("explore_admin_1", explore_admin_1_title, explore_admin_1_desc, explore_admin_1_img)
        await upsert_landing_section("explore_admin_2", explore_admin_2_title, explore_admin_2_desc, explore_admin_2_img)
        await upsert_landing_section("explore_admin_3", explore_admin_3_title, explore_admin_3_desc, explore_admin_3_img)
        await upsert_landing_section("explore_cta", explore_cta_title, explore_cta_desc)
        await upsert_landing_section("about_hero", about_hero_title, about_hero_desc)
        await upsert_landing_section("about_benefits", about_benefits_title, about_benefits_desc)
        await upsert_landing_section("about_benefit_1", about_benefit_1_title, about_benefit_1_desc, about_benefit_1_img)
        await upsert_landing_section("about_benefit_2", about_benefit_2_title, about_benefit_2_desc, about_benefit_2_img)
        await upsert_landing_section("about_benefit_3", about_benefit_3_title, about_benefit_3_desc, about_benefit_3_img)
        await upsert_landing_section("about_clip", about_clip_title, about_clip_desc)
        await upsert_landing_section("about_clip_1", about_clip_1_title, about_clip_1_desc, about_clip_1_img)
        await upsert_landing_section("about_clip_2", about_clip_2_title, about_clip_2_desc, about_clip_2_img)
        await upsert_landing_section("about_clip_3", about_clip_3_title, about_clip_3_desc, about_clip_3_img)
        await upsert_landing_section("about_system", about_system_title, about_system_desc)
        await upsert_landing_section("about_system_1", about_system_1_title, about_system_1_desc, about_system_1_img)
        await upsert_landing_section("about_system_2", about_system_2_title, about_system_2_desc, about_system_2_img)
        await upsert_landing_section("about_system_3", about_system_3_title, about_system_3_desc, about_system_3_img)
        await upsert_landing_section("about_system_graphic", None, None, about_system_graphic)
        await upsert_landing_section("about_cta", about_cta_title, about_cta_desc, about_cta_img)
        
        
        db.commit()
        return {"status": "success", "message": "Content and Files updated!"}
    
       

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
# Make sure this is flush with the left margin (or aligned with your other routes)
@app.get("/api/content/landing")
async def get_landing_content(db: Session = Depends(get_db)):
    content_by_key = {
        content.section_key: content
        for content in db.query(models.LandingContent).all()
    }

    hero_data = content_by_key.get("hero")
    app_download_data = content_by_key.get("app_download")
    faq_data = content_by_key.get("faq")
    why_data = content_by_key.get("why_choose_us")
    cta_data = content_by_key.get("cta-feature")
    reunite_data = content_by_key.get("reunite")
    how_it_works_data = content_by_key.get("how_it_works")
    features_main_data = content_by_key.get("features_main")
    feature_1_data = content_by_key.get("feature_1")
    feature_2_data = content_by_key.get("feature_2")
    feature_3_data = content_by_key.get("feature_3")
    feature_4_data = content_by_key.get("feature_4")
    explore_hero_data = content_by_key.get("explore_hero")
    explore_student_section_data = content_by_key.get("explore_student_section")
    explore_student_1_data = content_by_key.get("explore_student_1")
    explore_student_2_data = content_by_key.get("explore_student_2")
    explore_student_3_data = content_by_key.get("explore_student_3")
    explore_admin_section_data = content_by_key.get("explore_admin_section")
    explore_admin_1_data = content_by_key.get("explore_admin_1")
    explore_admin_2_data = content_by_key.get("explore_admin_2")
    explore_admin_3_data = content_by_key.get("explore_admin_3")
    explore_cta_data = content_by_key.get("explore_cta")
    about_hero_data = content_by_key.get("about_hero")
    about_benefits_data = content_by_key.get("about_benefits")
    about_benefit_1_data = content_by_key.get("about_benefit_1")
    about_benefit_2_data = content_by_key.get("about_benefit_2")
    about_benefit_3_data = content_by_key.get("about_benefit_3")
    about_clip_data = content_by_key.get("about_clip")
    about_clip_1_data = content_by_key.get("about_clip_1")
    about_clip_2_data = content_by_key.get("about_clip_2")
    about_clip_3_data = content_by_key.get("about_clip_3")
    about_system_data = content_by_key.get("about_system")
    about_system_1_data = content_by_key.get("about_system_1")
    about_system_2_data = content_by_key.get("about_system_2")
    about_system_3_data = content_by_key.get("about_system_3")
    about_system_graphic_data = content_by_key.get("about_system_graphic")
    about_cta_data = content_by_key.get("about_cta")

    # Prepare the response dictionary
    response = {}

    # --- Process Hero Section ---
    if hero_data:
        response["hero"] = {
            "title": hero_data.title,
            "description": hero_data.description,
            "image_path": public_file_url(hero_data.image_path)  # Added this!
        }
    else:
        # Default Fallback
        response["hero"] = {
            "title": "Lost Something?<br><span>Found Something?</span>",
            "description": "Connect instantly with your student community. Report found items or locate your missing belongings in seconds so you can get back to class.",
            "image_path": None
        }
    response["app_download"] = {
        "eyebrow": app_download_data.title if app_download_data and app_download_data.title else "LookFor on Android",
        "description": app_download_data.description if app_download_data and app_download_data.description else "Download Android App (APK)|||Installing the APK? Android may ask you to allow installation from your browser or file manager. Only install apps from sources you trust.|||/download/lookfor-app.apk",
    }
    response["faq"] = {
        "title": faq_data.title if faq_data and faq_data.title else "Frequently asked questions",
        "description": faq_data.description if faq_data and faq_data.description else (
            "Where is the Admin Office Located?|||You can find the admin at 3rd floor of the STI College Novaliches Building.|||"
            "How long do you keep unclaimed items?|||Items are kept for the entire semester. After this period the unclaimed items are disposed according to school policy.|||"
            "What proof do I need to claim an item?|||You need to present your School ID and describe the unique features of the item."
        ),
    }

    # --- Process Why Choose Us Section ---
    if why_data:
        response["why_choose_us"] = {
            "title": why_data.title,
            "description": why_data.description,
            "image_path": public_file_url(why_data.image_path)  # Added this!
        }
    else:
        # Default Fallback
        response["why_choose_us"] = {
            "title": "Why Choose LookFor?",
            "description": "Helping STIers find what they lost.|||Fast and reliable community support.",
            "image_path": None
        }
    if cta_data:
        response["cta_feature"] = {
            "title": cta_data.title,
            "description": cta_data.description,
            "image_path": public_file_url(cta_data.image_path)  # Added this!
        }

    if reunite_data:
        response["reunite"] = {
            "title": reunite_data.title,
            "description": reunite_data.description,
        }
    if how_it_works_data:
        response["how_it_works"] = {
            "title": how_it_works_data.title,
            "description": how_it_works_data.description,
        }
    else:
        response["how_it_works"] = {
            "title": "How Lookfor Works",
            "description": "Report|||Lost something? Submit a report with descriptions and photos to alert our team.|||Match|||Our system cross-references your report with items surrendered...|||Recover|||Receive a notification, verify your ownership via chat, and claim your item!",
        }

    if features_main_data:
        response["features_main"] = {
            "title": features_main_data.title,
            "description": features_main_data.description,
        }
    else:
        response["features_main"] = {
            "title": "Everything you need to reunite <br><span>with your lost item</span>",
            "description": "From AI image-text matching to progress tracking, and community engagement, LookFor makes lost items find faster and easier",
        }

    response["feature_cards"] = [
        {
            "title": feature_1_data.title if feature_1_data else "AI Image-Text Matching",
            "description": feature_1_data.description if feature_1_data else "Get image-text matching to quickly match the lost and found item",
            "image_path": public_file_url(feature_1_data.image_path, "/static/images/stilogo.png") if feature_1_data else "/static/images/stilogo.png",
        },
        {
            "title": feature_2_data.title if feature_2_data else "Lost and Found Report",
            "description": feature_2_data.description if feature_2_data else "Report lost and found item to easily reunite the item with its owner",
            "image_path": public_file_url(feature_2_data.image_path, "/static/images/stilogo.png") if feature_2_data else "/static/images/stilogo.png",
        },
        {
            "title": feature_3_data.title if feature_3_data else "Conversation Chatbox",
            "description": feature_3_data.description if feature_3_data else "Connect with administrator to further discuss the surrendering and retrieving...",
            "image_path": public_file_url(feature_3_data.image_path, "/static/images/stilogo.png") if feature_3_data else "/static/images/stilogo.png",
        },
        {
            "title": feature_4_data.title if feature_4_data else "Instant Notification",
            "description": feature_4_data.description if feature_4_data else "Receive notifications and alerts real-time to monitor the changes of item status",
            "image_path": public_file_url(feature_4_data.image_path, "/static/images/stilogo.png") if feature_4_data else "/static/images/stilogo.png",
        },
    ]
    response["explore_hero"] = {
        "title": explore_hero_data.title if explore_hero_data and explore_hero_data.title else "Explore <span>Features</span>",
        "description": explore_hero_data.description if explore_hero_data and explore_hero_data.description else "Discover how LookFor innovates the lost and found process of STI College Novaliches with AI-powered image-text matching that is efficient, reliable, and secure.",
    }
    response["explore_student_section"] = {
        "title": explore_student_section_data.title if explore_student_section_data and explore_student_section_data.title else "Student-focused <span>Features</span>",
        "description": explore_student_section_data.description if explore_student_section_data and explore_student_section_data.description else "Find what is yours with AI-powered image-text matching and a user-friendly interface for successful lost and found processes.",
    }
    response["explore_student_cards"] = [
        {
            "title": explore_student_1_data.title if explore_student_1_data and explore_student_1_data.title else "Report Lost Items",
            "description": explore_student_1_data.description if explore_student_1_data and explore_student_1_data.description else "Submit lost item reports with clear details and photos so the community can help you faster.",
            "image_path": public_file_url(explore_student_1_data.image_path, "/static/images/stilogo.png") if explore_student_1_data else "/static/images/stilogo.png",
        },
        {
            "title": explore_student_2_data.title if explore_student_2_data and explore_student_2_data.title else "Track Match Progress",
            "description": explore_student_2_data.description if explore_student_2_data and explore_student_2_data.description else "Monitor possible matches and claim updates in one organized place.",
            "image_path": public_file_url(explore_student_2_data.image_path, "/static/images/stilogo.png") if explore_student_2_data else "/static/images/stilogo.png",
        },
        {
            "title": explore_student_3_data.title if explore_student_3_data and explore_student_3_data.title else "Chat With Admin",
            "description": explore_student_3_data.description if explore_student_3_data and explore_student_3_data.description else "Coordinate with the admin office when you need verification or claim assistance.",
            "image_path": public_file_url(explore_student_3_data.image_path, "/static/images/stilogo.png") if explore_student_3_data else "/static/images/stilogo.png",
        },
    ]
    response["explore_admin_section"] = {
        "title": explore_admin_section_data.title if explore_admin_section_data and explore_admin_section_data.title else "Admin-focused <span>Features</span>",
        "description": explore_admin_section_data.description if explore_admin_section_data and explore_admin_section_data.description else "Give administrators the tools to review reports, monitor activity, and keep the lost and found process organized.",
    }
    response["explore_admin_cards"] = [
        {
            "title": explore_admin_1_data.title if explore_admin_1_data and explore_admin_1_data.title else "Monitor Activities",
            "description": explore_admin_1_data.description if explore_admin_1_data and explore_admin_1_data.description else "Review user and system activity while enforcing school policies inside the platform.",
            "image_path": public_file_url(explore_admin_1_data.image_path, "/static/images/stilogo.png") if explore_admin_1_data else "/static/images/stilogo.png",
        },
        {
            "title": explore_admin_2_data.title if explore_admin_2_data and explore_admin_2_data.title else "Manage Reports",
            "description": explore_admin_2_data.description if explore_admin_2_data and explore_admin_2_data.description else "Handle lost and found submissions efficiently from a centralized dashboard.",
            "image_path": public_file_url(explore_admin_2_data.image_path, "/static/images/stilogo.png") if explore_admin_2_data else "/static/images/stilogo.png",
        },
        {
            "title": explore_admin_3_data.title if explore_admin_3_data and explore_admin_3_data.title else "Generate Summaries",
            "description": explore_admin_3_data.description if explore_admin_3_data and explore_admin_3_data.description else "Generate summaries and semester reports for better oversight and decision-making.",
            "image_path": public_file_url(explore_admin_3_data.image_path, "/static/images/stilogo.png") if explore_admin_3_data else "/static/images/stilogo.png",
        },
    ]
    response["explore_cta"] = {
        "title": explore_cta_data.title if explore_cta_data and explore_cta_data.title else "Improve the process<br>with <span>Look<span>for</span></span>",
        "description": explore_cta_data.description if explore_cta_data and explore_cta_data.description else "Join the community to enhance the lost and found system of STI College Novaliches from reporting and surrendering found items to finding and retrieving lost ones.",
    }
    response["about_hero"] = {
        "title": about_hero_data.title if about_hero_data and about_hero_data.title else "Learn more About",
        "description": about_hero_data.description if about_hero_data and about_hero_data.description else "Find hope with LookFor, an AI-powered lost and found image-text matching system that helps reunite lost items with their owners quickly and efficiently.",
    }
    response["about_benefits"] = {
        "title": about_benefits_data.title if about_benefits_data and about_benefits_data.title else "Why Choose <span class=\"biglogo\">Look<span>for</span></span> ?",
        "description": about_benefits_data.description if about_benefits_data and about_benefits_data.description else "We utilize AI matching with human verification to make sure the methods of matching lost and found items are accurate.",
    }
    response["about_benefit_cards"] = [
        {
            "title": about_benefit_1_data.title if about_benefit_1_data and about_benefit_1_data.title else "AI Matching",
            "description": about_benefit_1_data.description if about_benefit_1_data and about_benefit_1_data.description else "Our intelligent AI system analyzes photos and text descriptions to find potential matches for lost items, saving time and effort.",
            "image_path": public_file_url(about_benefit_1_data.image_path, "/static/images/stilogo.png") if about_benefit_1_data else "/static/images/stilogo.png",
        },
        {
            "title": about_benefit_2_data.title if about_benefit_2_data and about_benefit_2_data.title else "Effortless Reporting",
            "description": about_benefit_2_data.description if about_benefit_2_data and about_benefit_2_data.description else "Easily report lost and found items through the system, accessible from anywhere and anytime.",
            "image_path": public_file_url(about_benefit_2_data.image_path, "/static/images/stilogo.png") if about_benefit_2_data else "/static/images/stilogo.png",
        },
        {
            "title": about_benefit_3_data.title if about_benefit_3_data and about_benefit_3_data.title else "Secured & Centralized",
            "description": about_benefit_3_data.description if about_benefit_3_data and about_benefit_3_data.description else "All information is stored in a central database with management and authority handled by school staff.",
            "image_path": public_file_url(about_benefit_3_data.image_path, "/static/images/stilogo.png") if about_benefit_3_data else "/static/images/stilogo.png",
        },
    ]
    response["about_clip"] = {
        "title": about_clip_data.title if about_clip_data and about_clip_data.title else "Powered by <span>CLIP</span>",
        "description": about_clip_data.description if about_clip_data and about_clip_data.description else "Experience the efficiency of our advanced AI-powered platform designed to reunite you with your lost items.",
    }
    response["about_clip_cards"] = [
        {
            "title": about_clip_1_data.title if about_clip_1_data and about_clip_1_data.title else "Reporting",
            "description": about_clip_1_data.description if about_clip_1_data and about_clip_1_data.description else "Effortless and simple processing of lost and found cases.",
            "image_path": public_file_url(about_clip_1_data.image_path, "/static/images/stilogo.png") if about_clip_1_data else "/static/images/stilogo.png",
        },
        {
            "title": about_clip_2_data.title if about_clip_2_data and about_clip_2_data.title else "AI",
            "description": about_clip_2_data.description if about_clip_2_data and about_clip_2_data.description else "AI-powered image-text matching for quick recovery of items.",
            "image_path": public_file_url(about_clip_2_data.image_path, "/static/images/stilogo.png") if about_clip_2_data else "/static/images/stilogo.png",
        },
        {
            "title": about_clip_3_data.title if about_clip_3_data and about_clip_3_data.title else "Notifications",
            "description": about_clip_3_data.description if about_clip_3_data and about_clip_3_data.description else "Real-time notifications for updates regarding report status.",
            "image_path": public_file_url(about_clip_3_data.image_path, "/static/images/stilogo.png") if about_clip_3_data else "/static/images/stilogo.png",
        },
    ]
    response["about_system"] = {
        "title": about_system_data.title if about_system_data and about_system_data.title else "Improved <span>Lost and Found System</span>",
        "description": about_system_data.description if about_system_data and about_system_data.description else "Your complete solution for reuniting lost items with their owners.",
    }
    response["about_system_cards"] = [
        {
            "title": about_system_1_data.title if about_system_1_data and about_system_1_data.title else "AI Matching & Search",
            "description": about_system_1_data.description if about_system_1_data and about_system_1_data.description else "AI analyzes details and images to find potential matches quickly.",
            "image_path": public_file_url(about_system_1_data.image_path, "/static/images/stilogo.png") if about_system_1_data else "/static/images/stilogo.png",
        },
        {
            "title": about_system_2_data.title if about_system_2_data and about_system_2_data.title else "Uploads",
            "description": about_system_2_data.description if about_system_2_data and about_system_2_data.description else "Report lost or found items through a simple online form with photo uploads and text descriptions.",
            "image_path": public_file_url(about_system_2_data.image_path, "/static/images/stilogo.png") if about_system_2_data else "/static/images/stilogo.png",
        },
        {
            "title": about_system_3_data.title if about_system_3_data and about_system_3_data.title else "Alerts & Notifications",
            "description": about_system_3_data.description if about_system_3_data and about_system_3_data.description else "Receive instant alerts and notifications when report progress changes.",
            "image_path": public_file_url(about_system_3_data.image_path, "/static/images/stilogo.png") if about_system_3_data else "/static/images/stilogo.png",
        },
    ]
    response["about_system_graphic"] = {
        "image_path": public_file_url(about_system_graphic_data.image_path, "/static/images/background.jpg") if about_system_graphic_data else "/static/images/background.jpg",
    }
    response["about_cta"] = {
        "title": about_cta_data.title if about_cta_data and about_cta_data.title else "Ready to reunite<br>with your item?",
        "description": about_cta_data.description if about_cta_data and about_cta_data.description else "Join our school community and reunite with your lost items with LookFor.",
        "image_path": public_file_url(about_cta_data.image_path, "/static/images/stilogo.png") if about_cta_data else "/static/images/stilogo.png",
    }
    return response

if __name__ == "__main__":
    # 2. I-run gamit ang 0.0.0.0 para ma-access sa network
    uvicorn.run(app, host="0.0.0.0", port=8000)
