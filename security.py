import os
import re
from datetime import datetime, timedelta
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status, Header, Depends, Request
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import models
from database import get_db

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def normalize_login_identifier(value: str) -> str:
    identifier = (value or "").strip().lower()
    if identifier.endswith("@novaliches.sti.edu"):
        return f"{identifier}.ph"
    return identifier


def get_login_email_candidates(value: str) -> list[str]:
    normalized = normalize_login_identifier(value)
    candidates = {normalized}

    if normalized.endswith("@novaliches.sti.edu.ph"):
        candidates.add(normalized[:-3])
    elif normalized.endswith("@novaliches.sti.edu"):
        candidates.add(f"{normalized}.ph")

    return [candidate for candidate in candidates if candidate]


def sanitize_email_name_part(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())
    return cleaned

# Create Token
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# Student or Admin
# In your auth/security file
def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
    if not authorization:
        raise credentials_exception
    try:
        token = authorization.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id = payload.get("id")
        login_candidates = get_login_email_candidates(email)
        
        user = None
        if user_id is not None:
            user = db.query(models.User).filter(models.User.id == user_id).first()

        if user is None and login_candidates:
            user = db.query(models.User).filter(models.User.email.in_(login_candidates)).first()

        if user is None:
            raise credentials_exception
        if bool(getattr(user, "is_archived", False)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This account is archived and disabled.",
            )
        return user # Now returns the object with .id, .email, etc.
    except (JWTError, IndexError):
        raise credentials_exception


# Admin Only
async def get_current_admin(
    authorization: str = Header(None), 
    db: Session = Depends(get_db)
):
    token = None

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No session found. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Decode the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        is_admin: bool = payload.get("is_admin")

        if email is None or not is_admin:
            raise HTTPException(status_code=403, detail="Faculty access only")
        
        # Fetch actual DB record to check permissions later
        admin = db.query(models.User).filter(models.User.email == email).first()
        if not admin:
            raise HTTPException(status_code=401, detail="User not found")
        if bool(getattr(admin, "is_archived", False)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This account is archived and disabled.",
            )
            
        return admin 

    except JWTError:
        # This triggers if the token is expired or tampered with
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Session expired. Please log in again."
        )
    
def verify_password(plain_password, hashed_password):
        """
    Checks if the plain text password from the login form 
    matches the hashed version stored in SSMS.
        """
        return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
        """
        Used when registering new students or admins.
        """
        return pwd_context.hash(password)
