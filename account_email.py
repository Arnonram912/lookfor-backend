import html
import os
import queue
import smtplib
import threading
from email.message import EmailMessage

from dotenv import load_dotenv


load_dotenv()

_EMAIL_QUEUE: queue.Queue[dict] = queue.Queue(
    maxsize=max(1, int(os.getenv("ACCOUNT_EMAIL_QUEUE_SIZE", "500")))
)
_EMAIL_WORKER_LOCK = threading.Lock()
_EMAIL_WORKER: threading.Thread | None = None


def send_account_access_email(
    recipient_email: str,
    full_name: str,
    temporary_password: str,
    *,
    account_type: str = "user",
) -> None:
    """Send the credentials and first-login instructions for a new account."""
    sender_email = os.getenv("GMAIL_SENDER_EMAIL", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    login_url = os.getenv("LOOKFOR_LOGIN_URL", "http://127.0.0.1:8000/login").strip()

    if not sender_email or not app_password:
        raise RuntimeError("Gmail SMTP credentials are not configured")

    display_name = (full_name or "there").strip()
    role_label = (account_type or "user").strip().title()

    message = EmailMessage()
    message["Subject"] = "Your LookFor account is ready"
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(
        f"""Hello {display_name},

Your LookFor {role_label.lower()} account has been created.

How to access your account:
1. Open {login_url}
2. Sign in using your email: {recipient_email}
3. Enter your temporary password: {temporary_password}
4. Change your temporary password when prompted.
5. A verification code will be sent to your email during sign-in.

For your security, do not share your temporary password or verification code.

- LookFor Team"""
    )

    message.add_alternative(
        f"""
        <html>
            <body>
                <p>Hello {html.escape(display_name)},</p>
                <p>Your LookFor {html.escape(role_label.lower())} account has been created.</p>
                <h3>How to access your account</h3>
                <ol>
                    <li>Open <a href="{html.escape(login_url, quote=True)}">the LookFor login page</a>.</li>
                    <li>Sign in using <strong>{html.escape(recipient_email)}</strong>.</li>
                    <li>Enter your temporary password: <strong>{html.escape(temporary_password)}</strong>.</li>
                    <li>Change your temporary password when prompted.</li>
                    <li>A verification code will be sent to your email during sign-in.</li>
                </ol>
                <p>For your security, do not share your temporary password or verification code.</p>
                <p>- LookFor Team</p>
            </body>
        </html>
        """,
        subtype="html",
    )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender_email, app_password)
        smtp.send_message(message)


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


def queue_account_access_email(
    recipient_email: str,
    full_name: str,
    temporary_password: str,
    *,
    account_type: str = "user",
) -> bool:
    """Queue an account email without holding up the request or bulk job."""
    _ensure_account_email_worker()
    try:
        _EMAIL_QUEUE.put_nowait({
            "recipient_email": recipient_email,
            "full_name": full_name,
            "temporary_password": temporary_password,
            "account_type": account_type,
        })
        return True
    except queue.Full:
        print(f"Account email queue is full; email not queued for {recipient_email}")
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
