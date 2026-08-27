import html
import os
import queue
import smtplib
import threading
import time
from datetime import datetime, timedelta
from email.message import EmailMessage

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from sqlalchemy import or_

from database import SessionLocal
import models

load_dotenv()

_EMAIL_QUEUE: queue.Queue[dict] = queue.Queue(
    maxsize=max(1, int(os.getenv("ACCOUNT_EMAIL_QUEUE_SIZE", "500")))
)
_EMAIL_WORKER_LOCK = threading.Lock()
_EMAIL_WORKER: threading.Thread | None = None
_OUTBOX_WORKER_LOCK = threading.Lock()
_OUTBOX_WORKER: threading.Thread | None = None
_OUTBOX_SEND_INTERVAL_SECONDS = max(0.0, float(os.getenv("ACCOUNT_EMAIL_SEND_INTERVAL_SECONDS", "2")))
_PASSWORD_EMAIL_DELAY_MINUTES = max(0.0, float(os.getenv("ACCOUNT_PASSWORD_EMAIL_DELAY_MINUTES", "2")))


def send_account_access_email(
    recipient_email: str,
    full_name: str,
    temporary_password: str,
    *,
    account_type: str = "user",
) -> None:
    """Send account access details and the temporary password separately."""
    sender_email = os.getenv("GMAIL_SENDER_EMAIL", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    login_url = os.getenv("LOOKFOR_LOGIN_URL", "http://127.0.0.1:8000/login").strip()

    if not sender_email or not app_password:
        raise RuntimeError("Gmail SMTP credentials are not configured")

    username_message, password_message = build_account_access_messages(
        recipient_email,
        full_name,
        temporary_password,
        sender_email=sender_email,
        login_url=login_url,
        account_type=account_type,
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(username_message)
        smtp.send_message(password_message)


def send_account_access_email_stage(
    recipient_email: str,
    full_name: str,
    temporary_password: str,
    *,
    stage: str,
    account_type: str = "user",
) -> None:
    """Send one credential message so the password can be delayed durably."""
    sender_email = os.getenv("GMAIL_SENDER_EMAIL", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    login_url = os.getenv("LOOKFOR_LOGIN_URL", "http://127.0.0.1:8000/login").strip()
    if not sender_email or not app_password:
        raise RuntimeError("Gmail SMTP credentials are not configured")
    if stage not in {"username", "password"}:
        raise ValueError("Unsupported account email stage")

    messages = build_account_access_messages(
        recipient_email,
        full_name,
        temporary_password,
        sender_email=sender_email,
        login_url=login_url,
        account_type=account_type,
    )
    message = messages[0] if stage == "username" else messages[1]
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(message)


def build_account_access_messages(
    recipient_email: str,
    full_name: str,
    temporary_password: str,
    *,
    sender_email: str,
    login_url: str,
    account_type: str = "user",
) -> tuple[EmailMessage, EmailMessage]:
    """Build separate username and temporary-password account emails."""
    display_name = (full_name or "there").strip()
    username = (recipient_email or "").strip()
    # Retain the argument for compatibility with queued jobs. The requested
    # copy applies uniformly to every LookFor account type.
    _ = account_type

    username_message = EmailMessage()
    username_message["Subject"] = "Your LookFor Account Has Been Created"
    username_message["From"] = sender_email
    username_message["To"] = recipient_email
    username_message.set_content(
        f"""Hello {display_name},

Welcome to LookFor!

Your LookFor account has been successfully created. LookFor is a web and mobile application designed to help students, faculty, and staff easily find and manage lost and found items within the campus.

Your Account Details

- Username: {username}

How to Access Your Account

1. Open {login_url}
2. Sign in using your username.
3. Enter the temporary password provided in the separate email.
4. Change your temporary password when prompted.
5. A verification code will be sent to your email during sign-in.

For your security, please do not share your account credentials or verification code with anyone.

Thank you for using LookFor!

- LookFor Team"""
    )

    username_message.add_alternative(
        f"""
        <html>
            <body>
                <p>Hello {html.escape(display_name)},</p>
                <p>Welcome to LookFor!</p>
                <p>Your LookFor account has been successfully created. LookFor is a web and mobile application designed to help students, faculty, and staff easily find and manage lost and found items within the campus.</p>
                <h3>Your Account Details</h3>
                <p><strong>Username:</strong> {html.escape(username)}</p>
                <h3>How to Access Your Account</h3>
                <ol>
                    <li>Open <a href="{html.escape(login_url, quote=True)}">the LookFor login page</a>.</li>
                    <li>Sign in using your username.</li>
                    <li>Enter the temporary password provided in the separate email.</li>
                    <li>Change your temporary password when prompted.</li>
                    <li>A verification code will be sent to your email during sign-in.</li>
                </ol>
                <p>For your security, please do not share your account credentials or verification code with anyone.</p>
                <p>Thank you for using LookFor!</p>
                <p>- LookFor Team</p>
            </body>
        </html>
        """,
        subtype="html",
    )

    password_message = EmailMessage()
    password_message["Subject"] = "Your LookFor Temporary Password"
    password_message["From"] = sender_email
    password_message["To"] = recipient_email
    password_message.set_content(
        f"""Hello {display_name},

Your LookFor account has been successfully created. Below is your temporary password:

Temporary Password: {temporary_password}

Please use this password when signing in to your LookFor account. You will be prompted to change it after your first login.

For your security, please do not share your temporary password or verification code with anyone.

- LookFor Team"""
    )
    password_message.add_alternative(
        f"""
        <html>
            <body>
                <p>Hello {html.escape(display_name)},</p>
                <p>Your LookFor account has been successfully created. Below is your temporary password:</p>
                <p><strong>Temporary Password:</strong> {html.escape(temporary_password)}</p>
                <p>Please use this password when signing in to your LookFor account. You will be prompted to change it after your first login.</p>
                <p>For your security, please do not share your temporary password or verification code with anyone.</p>
                <p>- LookFor Team</p>
            </body>
        </html>
        """,
        subtype="html",
    )

    return username_message, password_message


def send_item_event_email(
    recipient_email: str,
    full_name: str,
    *,
    subject: str,
    message_text: str,
    action_url: str | None = None,
) -> None:
    """Send a report or match notification email."""
    sender_email = os.getenv("GMAIL_SENDER_EMAIL", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not sender_email or not app_password:
        raise RuntimeError("Gmail SMTP credentials are not configured")

    display_name = (full_name or "there").strip()
    safe_text = (message_text or "").strip()
    if action_url and action_url.startswith("/"):
        base_url = os.getenv("LOOKFOR_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        action_url = f"{base_url}{action_url}"
    link_text = f"\n\nView it in LookFor: {action_url}" if action_url else ""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(
        f"Hello {display_name},\n\n{safe_text}{link_text}\n\n- LookFor Team"
    )

    action_html = (
        f'<p><a href="{html.escape(action_url, quote=True)}">View it in LookFor</a></p>'
        if action_url else ""
    )
    message.add_alternative(
        f"""<html><body>
        <p>Hello {html.escape(display_name)},</p>
        <p>{html.escape(safe_text)}</p>
        {action_html}
        <p>- LookFor Team</p>
        </body></html>""",
        subtype="html",
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(message)


def _account_email_worker() -> None:
    while True:
        payload = _EMAIL_QUEUE.get()
        try:
            email_kind = payload.pop("_email_kind", "account")
            if email_kind == "item_event":
                send_item_event_email(**payload)
            else:
                send_account_access_email(**payload)
        except Exception as exc:
            print(f"Account access email failed for {payload.get('recipient_email')}: {exc}")
        finally:
            _EMAIL_QUEUE.task_done()


def _ensure_account_email_worker() -> None:
    global _EMAIL_WORKER
    if _EMAIL_WORKER and _EMAIL_WORKER.is_alive():
        return

    with _EMAIL_WORKER_LOCK:
        if _EMAIL_WORKER and _EMAIL_WORKER.is_alive():
            return
        _EMAIL_WORKER = threading.Thread(
            target=_account_email_worker,
            name="lookfor-account-email-worker",
            daemon=True,
        )
        _EMAIL_WORKER.start()


def _outbox_cipher() -> Fernet:
    key = os.getenv("ACCOUNT_EMAIL_ENCRYPTION_KEY", "").strip().encode("utf-8")
    if not key:
        raise RuntimeError("ACCOUNT_EMAIL_ENCRYPTION_KEY is not configured")
    return Fernet(key)


def _claim_next_account_email():
    """Claim one job before SMTP delivery so a restart cannot lose the batch."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        job = (
            db.query(models.AccountEmailOutbox)
            .filter(
                or_(
                    (models.AccountEmailOutbox.status == "pending")
                    & (models.AccountEmailOutbox.available_at <= now),
                    (models.AccountEmailOutbox.status == "password_pending")
                    & (models.AccountEmailOutbox.available_at <= now),
                    (models.AccountEmailOutbox.status == "sending")
                    & (models.AccountEmailOutbox.available_at <= now),
                    (models.AccountEmailOutbox.status == "sending_username")
                    & (models.AccountEmailOutbox.available_at <= now),
                    (models.AccountEmailOutbox.status == "sending_password")
                    & (models.AccountEmailOutbox.available_at <= now),
                )
            )
            .order_by(models.AccountEmailOutbox.id.asc())
            .first()
        )
        if not job:
            return None
        stage = (
            "password"
            if job.status in {"password_pending", "sending_password"}
            else "username"
        )
        job.status = f"sending_{stage}"
        job.attempt_count += 1
        # A worker that stops mid-send becomes eligible again after ten minutes.
        job.available_at = now + timedelta(minutes=10)
        db.commit()
        return {
            "id": job.id,
            "recipient_email": job.recipient_email,
            "full_name": job.full_name,
            "encrypted_temporary_password": job.encrypted_temporary_password,
            "account_type": job.account_type,
            "attempt_count": job.attempt_count,
            "stage": stage,
        }
    finally:
        db.close()


def _finish_account_email(
    job_id: int,
    *,
    stage: str = "password",
    error: Exception | None = None,
) -> None:
    db = SessionLocal()
    try:
        job = db.query(models.AccountEmailOutbox).filter(models.AccountEmailOutbox.id == job_id).first()
        if not job:
            return
        if error is None:
            if stage == "username":
                job.status = "password_pending"
                job.attempt_count = 0
                job.available_at = datetime.utcnow() + timedelta(minutes=_PASSWORD_EMAIL_DELAY_MINUTES)
            else:
                job.status = "sent"
                job.sent_at = datetime.utcnow()
            job.last_error = None
        elif job.attempt_count >= 5:
            failed_status = f"failed_{stage}"
            was_failed = job.status == failed_status
            job.status = failed_status
            job.last_error = str(error)[:1000]
            if not was_failed:
                db.add(models.Notification(
                    message=(
                        f"The {stage} credential email failed for {job.recipient_email} "
                        f"after {job.attempt_count} attempts."
                    ),
                    type="account_email_failed",
                    related_id=job.id,
                    target_url="/admin/User-Management",
                    is_read=False,
                    created_at=datetime.utcnow(),
                ))
        else:
            job.status = "password_pending" if stage == "password" else "pending"
            job.last_error = str(error)[:1000]
            job.available_at = datetime.utcnow() + timedelta(minutes=min(30, 2 ** job.attempt_count))
        db.commit()
    finally:
        db.close()


def _account_email_outbox_worker() -> None:
    while True:
        job = None
        try:
            job = _claim_next_account_email()
            if not job:
                time.sleep(2)
                continue
            password = _outbox_cipher().decrypt(job["encrypted_temporary_password"].encode("utf-8")).decode("utf-8")
            send_account_access_email_stage(
                job["recipient_email"],
                job["full_name"],
                password,
                stage=job["stage"],
                account_type=job["account_type"],
            )
            _finish_account_email(job["id"], stage=job["stage"])
            # Prevent a large upload from overwhelming the SMTP provider.
            if _OUTBOX_SEND_INTERVAL_SECONDS:
                time.sleep(_OUTBOX_SEND_INTERVAL_SECONDS)
        except Exception as exc:
            if "job" in locals() and job:
                _finish_account_email(job["id"], stage=job.get("stage", "username"), error=exc)
            else:
                print(f"Account email outbox worker error: {exc}")
            time.sleep(2)


def ensure_account_email_outbox_worker() -> None:
    global _OUTBOX_WORKER
    if _OUTBOX_WORKER and _OUTBOX_WORKER.is_alive():
        return
    with _OUTBOX_WORKER_LOCK:
        if _OUTBOX_WORKER and _OUTBOX_WORKER.is_alive():
            return
        _OUTBOX_WORKER = threading.Thread(
            target=_account_email_outbox_worker,
            name="lookfor-account-email-outbox-worker",
            daemon=True,
        )
        _OUTBOX_WORKER.start()


def queue_account_access_email(
    recipient_email: str,
    full_name: str,
    temporary_password: str,
    *,
    account_type: str = "user",
) -> bool:
    """Persist an account email before delivery so bulk imports survive restarts."""
    if not recipient_email or not temporary_password:
        return False
    try:
        encrypted_password = _outbox_cipher().encrypt(temporary_password.encode("utf-8")).decode("utf-8")
        db = SessionLocal()
        db.add(models.AccountEmailOutbox(
            recipient_email=recipient_email,
            full_name=full_name,
            encrypted_temporary_password=encrypted_password,
            account_type=account_type,
            status="pending",
            available_at=datetime.utcnow(),
        ))
        db.commit()
        db.close()
        ensure_account_email_outbox_worker()
        return True
    except Exception as exc:
        try:
            db.rollback()
            db.close()
        except Exception:
            pass
        print(f"Account email was not persisted for {recipient_email}: {exc}")
        return False


def queue_item_event_email(
    recipient_email: str,
    full_name: str,
    *,
    subject: str,
    message_text: str,
    action_url: str | None = None,
) -> bool:
    """Queue a report or match email without delaying the API response."""
    if not recipient_email:
        return False
    _ensure_account_email_worker()
    try:
        _EMAIL_QUEUE.put_nowait({
            "_email_kind": "item_event",
            "recipient_email": recipient_email,
            "full_name": full_name,
            "subject": subject,
            "message_text": message_text,
            "action_url": action_url,
        })
        return True
    except queue.Full:
        print(f"Account email queue is full; event email not queued for {recipient_email}")
        return False
