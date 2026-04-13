from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from datetime import datetime
from security import get_current_user

templates = Jinja2Templates(directory="templates")

router = APIRouter(prefix="/admin", tags=["Admin Messages"])


# =====================================================
# 1️⃣ GET ALL CONVERSATIONS (LEFT SIDEBAR)
# =====================================================

@router.get("/Messages")
def admin_messages(request: Request, db: Session = Depends(get_db)):
    # 1. Fetch all students
    raw_students = db.query(models.User).filter(models.User.is_admin == False).all()

    # 2. Attach the "unread" status to each student
    students_with_status = []
    for s in raw_students:
        # Check if there's any message from this student where status is "unread"
        has_unread = db.query(models.Message).filter(
            models.Message.sender_id == s.id,
            models.Message.status == "unread"
        ).first() is not None
        
        # Create a dictionary that matches the keys you used in your Jinja template
        students_with_status.append({
            "id": s.id,
            "email": s.email,
            "has_unread": has_unread
        })

    return templates.TemplateResponse(
        "Admin Pages/Admin_Message.html", 
        {
            "request": request, 
            "students": students_with_status # This now contains the boolean 'has_unread'
        }
    )
# =====================================================
# 2️⃣ GET THREAD MESSAGES
# =====================================================

@router.get("/thread/{thread_id}")
def get_thread(thread_id: int, db: Session = Depends(get_db)):

    messages = (
        db.query(models.Message)
        .filter(models.Message.thread_id == thread_id)
        .order_by(models.Message.created_at.asc())
        .all()
    )

    return [
        {
            "id": msg.id,
            "content": msg.content,
            "sender_role": "admin" if msg.sender.is_admin else "student",
            "email": msg.sender.email,
            "created_at": msg.created_at
        }
        for msg in messages
    ]


# =====================================================
# 3️⃣ SEND NEW MESSAGE (CREATES THREAD)
# =====================================================

@router.post("/send-message")
def send_message(data: schemas.SendMessageSchema, db: Session = Depends(get_db)):

    # 1️⃣ Create thread first
    new_thread = models.Thread(
        subject=data.subject
    )

    db.add(new_thread)
    db.commit()
    db.refresh(new_thread)

    # 2️⃣ Create first message in that thread
    message = models.Message(
        sender_id=1,  # replace with logged-in admin ID later
        recipient_id=data.recipient_id,
        subject=data.subject,
        content=data.content,
        thread_id=new_thread.id
    )

    db.add(message)
    db.commit()

    return {"success": True}

# =====================================================
# 4️⃣ REPLY TO THREAD
# =====================================================

@router.post("/send-reply")
def send_reply(data: schemas.ReplySchema, db: Session = Depends(get_db)):

    thread = db.query(models.Thread).filter(
        models.Thread.id == data.thread_id
    ).first()

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Find original sender (first message in thread)
    first_message = thread.messages[0]

    reply = models.Message(
        sender_id=1,  # admin
        recipient_id=first_message.sender_id,
        subject=thread.subject,
        content=data.content,
        thread_id=thread.id
    )

    db.add(reply)
    db.commit()

    return {"success": True}


@router.post("/send-bulk-message")
def send_bulk_message(
    data: schemas.BulkSendMessageSchema,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can send bulk messages.")

    recipient_ids = list(dict.fromkeys(data.recipient_ids or []))
    content = (data.content or "").strip()

    if not recipient_ids:
        raise HTTPException(status_code=400, detail="Please select at least one student.")
    if not content:
        raise HTTPException(status_code=400, detail="Message content is required.")

    recipients = db.query(models.User).filter(
        models.User.id.in_(recipient_ids),
        models.User.is_admin == False
    ).all()

    if not recipients:
        raise HTTPException(status_code=404, detail="No valid student recipients found.")

    sent_count = 0
    admin_name = current_user.full_name or current_user.email or "LookFor Admin"
    for recipient in recipients:
        db.add(models.Message(
            sender_id=current_user.id,
            recipient_id=recipient.id,
            content=content,
            status="unread",
            created_at=datetime.utcnow()
        ))
        db.add(models.Notification(
            message=f"{admin_name} sent you a message.",
            type="chat",
            related_id=recipient.id,
            target_url="/student/Messages",
            is_read=False,
            created_at=datetime.utcnow()
        ))
        sent_count += 1

    db.commit()
    return {"success": True, "sent_count": sent_count}


# =====================================================
# 5️⃣ MARK AS READ
# =====================================================

@router.put("/message/read-all/{student_id}")
def mark_all_as_read(student_id: int, db: Session = Depends(get_db)):
    # Find all unread messages where this student is the sender
    # and the status is "unread"
    unread_messages = db.query(models.Message).filter(
        models.Message.sender_id == student_id,
        models.Message.status == "unread"
    ).all()

    for msg in unread_messages:
        msg.status = "read"
    
    db.commit()
    return {"success": True, "count": len(unread_messages)}


# =====================================================
# 6️⃣ MARK AS UNREAD
# =====================================================
@router.get("/api/messages/unread-count")
def get_unread_count(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    # This ignores: 'Unread', 'UNREAD', and 'unread    ' (with spaces)
    count = db.query(models.Message).filter(
        models.Message.recipient_id == current_user.id,
        func.trim(func.lower(models.Message.status)) == "unread"
    ).count()
    
    # Add this print to see the truth in your terminal/command prompt
    print(f"DEBUG: User {current_user.id} has {count} unread messages.")
    
    return {"unread_count": count}

@router.put("/message/unread/{message_id}")
def mark_unread(message_id: int, db: Session = Depends(get_db)):

    msg = db.query(models.Message).filter(
        models.Message.id == message_id
    ).first()

    msg.status = "unread"
    db.commit()

    return {"success": True}


# =====================================================
# 7️⃣ ARCHIVE MESSAGE
# =========================== ==========================

@router.put("/message/archive/{message_id}")
def archive_message(message_id: int, db: Session = Depends(get_db)):

    msg = db.query(models.Message).filter(
        models.Message.id == message_id
    ).first()

    msg.status = "archived"
    db.commit()

    return {"success": True}


# =====================================================
# 8️⃣ DELETE MESSAGE
# =====================================================

@router.delete("/message/{message_id}")
def delete_message(message_id: int, db: Session = Depends(get_db)):

    msg = db.query(models.Message).filter(
        models.Message.id == message_id
    ).first()

    if not msg:
        raise HTTPException(status_code=404, detail="Not found")

    db.delete(msg)
    db.commit()

    return {"success": True}


# =====================================================
# 9️⃣ SEARCH CONVERSATIONS
# =====================================================

@router.get("/search")
def search_conversations(query: str,
                         db: Session = Depends(get_db)):

    threads = db.query(models.Thread).filter(
        models.Thread.subject.ilike(f"%{query}%")
    ).all()

    return threads
