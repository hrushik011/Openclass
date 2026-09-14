from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALLOWED_EMAIL_DOMAIN,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
)
from .db import connect, now

security = HTTPBearer(auto_error=False)

def validate_college_domain(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].strip().lower()
    return domain == ALLOWED_EMAIL_DOMAIN.lower()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("sub") or payload.get("user_id")
    email = payload.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
        )
    
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            # Check students or faculty
            student = db.execute("SELECT * FROM students WHERE email = ?", (email,)).fetchone()
            if student:
                return {
                    "id": student["id"],
                    "email": student["email"],
                    "name": student["name"],
                    "role": "STUDENT",
                    "batch_id": student["batch_id"],
                    "phone": student.get("phone", "")
                }
            faculty = db.execute("SELECT * FROM faculty WHERE email = ?", (email,)).fetchone()
            if faculty:
                return {
                    "id": faculty["id"],
                    "email": faculty["email"],
                    "name": faculty["full_name"],
                    "role": "FACULTY",
                    "batch_id": None,
                    "phone": faculty.get("phone", "")
                }
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found in registry",
            )
        return dict(user)

def require_faculty(current_user: dict = Depends(get_current_user)) -> dict:
    role = str(current_user.get("role", "")).upper()
    if role != "FACULTY":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Faculty role required for this action",
        )
    return current_user

def require_student(current_user: dict = Depends(get_current_user)) -> dict:
    role = str(current_user.get("role", "")).upper()
    if role != "STUDENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student role required for this action",
        )
    return current_user

def verify_and_provision_ms_user(email: str, name: str, role: str = "STUDENT", batch_id: Optional[str] = None, phone: Optional[str] = None) -> dict:
    if not validate_college_domain(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Only @{ALLOWED_EMAIL_DOMAIN} accounts are permitted to sign in.",
        )
    
    role = role.upper()
    if role not in {"FACULTY", "STUDENT"}:
        role = "STUDENT"
        
    stamp = now()
    with connect() as db:
        existing = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            db.execute(
                "UPDATE users SET name = ?, role = ?, batch_id = COALESCE(?, batch_id), phone = COALESCE(?, phone), updated_at = ? WHERE email = ?",
                (name, role, batch_id, phone, stamp, email)
            )
            user_id = existing["id"]
        else:
            cursor = db.execute(
                "INSERT INTO users (email, name, role, batch_id, phone, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (email, name, role, batch_id, phone, stamp, stamp)
            )
            user_id = cursor.lastrowid
            
        # Also sync to students or faculty tables
        if role == "STUDENT":
            db.execute(
                """INSERT INTO students (id, name, email, phone, batch_id, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, email=excluded.email, batch_id=COALESCE(excluded.batch_id, students.batch_id), updated_at=excluded.updated_at""",
                (str(user_id), name, email, phone, batch_id, stamp)
            )
        elif role == "FACULTY":
            db.execute(
                """INSERT INTO faculty (full_name, email, phone, active, updated_at)
                   VALUES (?, ?, ?, 1, ?)
                   ON CONFLICT(full_name) DO UPDATE SET email=excluded.email, phone=COALESCE(excluded.phone, faculty.phone), updated_at=excluded.updated_at""",
                (name, email, phone, stamp)
            )
            
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        user_dict = dict(row)
        
    token_payload = {
        "sub": str(user_dict["id"]),
        "user_id": user_dict["id"],
        "email": user_dict["email"],
        "name": user_dict["name"],
        "role": user_dict["role"],
        "batch_id": user_dict["batch_id"]
    }
    access_token = create_access_token(token_payload)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_dict
    }
