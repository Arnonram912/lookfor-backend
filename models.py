# models.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Date, ForeignKey, func, Computed
from datetime import datetime
from database import Base
from sqlalchemy.orm import relationship
from pydantic import BaseModel

class SettingsUpdate(BaseModel):
    two_factor: bool
    notifications: bool
    theme: str
    font_size: int


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    message = Column(String, nullable=False)
    type = Column(String)
    related_id = Column(Integer)
    created_by_admin_id = Column(Integer, nullable=True)
    target_url = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, Computed("id"))
    item_code = Column(String(20), Computed(
        "CASE "
        "WHEN status = 'lost' THEN 'LOST-' + RIGHT('000000' + CONVERT(VARCHAR(20), id), 6) "
        "WHEN status = 'found' THEN 'FOUND-' + RIGHT('000000' + CONVERT(VARCHAR(20), id), 6) "
        "ELSE 'ITEM-' + RIGHT('000000' + CONVERT(VARCHAR(20), id), 6) "
        "END"
    ))
    status = Column(String(50))
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_relationship = relationship("Category", back_populates="items")
    category = Column(String(100))
    department = Column(String)
    description = Column(Text)
    image_path = Column(String(500))
    image_embedding = Column(Text)
    possible_matches = Column(Text, nullable=True)
    is_matched = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_surrendered = Column(Boolean, default=False)

    brand = Column(String(100), nullable=True) 
    color = Column(String(50), nullable=True)

    approved_at = Column(DateTime, nullable=True)
    archived = Column(Boolean, default=False)
    location = Column(String)     # NEW
    date = Column(Date) 
    time_found = Column(String, nullable=True)  

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    owner = relationship("User", back_populates="items")


class ReferenceItem(Base):
    __tablename__ = "reference_items"

    id = Column(Integer, primary_key=True, index=True)
    source_item_id = Column(Integer, nullable=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    status = Column(String(50))
    category = Column(String(100))
    department = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    image_path = Column(String(500), nullable=True)
    image_embedding = Column(Text, nullable=True)
    brand = Column(String(100), nullable=True)
    color = Column(String(50), nullable=True)
    location = Column(String, nullable=True)
    date = Column(Date, nullable=True)
    time_found = Column(String, nullable=True)
    user_id = Column(Integer, nullable=True)
    archived = Column(Boolean, default=False)
    is_surrendered = Column(Boolean, default=False)
    deleted_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=True)
    middle_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    full_name = Column(String(255), nullable=True) 

    student_no = Column(String(50), unique=True, nullable=True)
    course = Column(String(100), nullable=True)     # This is 'Program' (e.g., STEM, BSIT)
    department = Column(String(100), nullable=True) # For Admin Offices
    section = Column(String(100), nullable=True) 
    level = Column(String(50), nullable=True)       # NEW: For 'Level' (e.g., G11, G12)
    batch_id = Column(String(100), nullable=True, index=True) # Index makes deleting FAST
    profile_pic = Column(String(500), nullable=True, default="static/photos/default-student-avatar.jpg")
    email = Column(String(255), unique=True, index=True)
    hashed_password = Column(String(255))
    is_admin = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    must_change_password = Column(Boolean, default=True)
    permissions = Column(String, default="[]")
    last_login = Column(DateTime, nullable=True)
    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    push_notifications = Column(Boolean, default=True, nullable=False)
    theme_mode = Column(String(20), default="light", nullable=False)
    font_size = Column(Integer, default=16, nullable=False)

    items = relationship("Item", back_populates="owner")
    pending_items = relationship("PendingItem", back_populates="submitter")

class PendingItem(Base):
    __tablename__ = "pending_items"
    
    id = Column(Integer, primary_key=True, index=True)
    item_name = Column(String(255), nullable=True)
    category = Column(String)
    description = Column(String)
    location = Column(String)
    date = Column(Date)
    image_path = Column(String)

    brand = Column(String(100), nullable=True)
    color = Column(String(50), nullable=True)
    image_embedding = Column(String) # Matches the NVARCHAR(MAX) above
    matched_item_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    archived = Column(Boolean, default=False)
    time_found = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitter = relationship("User", back_populates="pending_items")


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False) # e.g., "Library", "CS Dept"

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)

    sender_id = Column(Integer, ForeignKey("users.id"))
    recipient_id = Column(Integer, ForeignKey("users.id"))
    thread_id = Column(Integer, ForeignKey("threads.id"))
    subject = Column(String)
    content = Column(Text)
    status = Column(String, default="unread")
    created_at = Column(DateTime, default=datetime.utcnow)
    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])
    thread = relationship("Thread", back_populates="messages")
class Thread(Base):
    __tablename__ = "threads"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("Message", back_populates="thread")

class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, index=True)
    
    # Links the Lost Item and the Found Item being matched
    lost_item_id = Column(Integer, ForeignKey("items.id"))
    found_item_id = Column(Integer, ForeignKey("items.id"))
    
    # Links to the User claiming the item
    claimant_id = Column(Integer, ForeignKey("users.id"))
    
    # Stores the AI similarity (e.g., 0.85 for 85%)
    similarity_score = Column(String(50)) 
    
    # Claim Status: 'pending', 'approved', 'rejected', 'completed'
    status = Column(String(50), default="pending")
    
    # Admin details
    admin_decision_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships for easier access in your queries
    lost_item = relationship("Item", foreign_keys=[lost_item_id])
    found_item = relationship("Item", foreign_keys=[found_item_id])
    claimant = relationship("User")
    proof = relationship("ClaimProof", back_populates="claim", uselist=False)


class ClaimProof(Base):
    __tablename__ = "claim_proofs"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), unique=True, nullable=False, index=True)
    claimant_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    claimant_student_no = Column(String(50), nullable=True)
    id_image_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    claim = relationship("Claim", back_populates="proof")
    claimant_user = relationship("User", foreign_keys=[claimant_user_id])


class ClaimDecisionReport(Base):
    __tablename__ = "claim_decision_reports"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), unique=True, nullable=False, index=True)
    decision_status = Column(String(50), nullable=False)
    report_image_path = Column(String(500), nullable=True)
    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    claim = relationship("Claim", foreign_keys=[claim_id])
    created_by_admin = relationship("User", foreign_keys=[created_by_admin_id])

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    items = relationship("Item", back_populates="category_relationship")

class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False)
    image_url = Column(String, default="/static/photos/default_news.jpg")
    created_at = Column(DateTime, default=datetime.utcnow)

class ConfiscatedItem(Base):
    __tablename__ = "confiscated_items"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String)
    brand = Column(String)
    description = Column(String)
    color = Column(String)
    date_confiscated = Column(Date)
    location = Column(String)
    estimated_time = Column(String)
    reason = Column(String)
    image_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())

class LandingContent(Base):
    __tablename__ = "landing_content"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # FIX: Add a specific length (e.g., 100) so SQL Server can index it
    section_key = Column(String(100), unique=True, index=True, nullable=False) 
    
    # These can stay as they are (SQL Server will use VARCHAR(MAX) for these)
    title = Column(String(255), nullable=True) 
    description = Column(Text, nullable=True)
    image_path = Column(Text, nullable=True)
