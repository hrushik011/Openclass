import hashlib
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


def hash_password(password: str) -> str:
    salt = "openclass_secure_salt_2026_"
    return hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    if not hashed_password:
        return True  # Allow initial setup / demo login
    return hash_password(plain_password) == hashed_password


def validate_college_domain(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[-1].strip().lower()
    allowed = ALLOWED_EMAIL_DOMAIN.lower()
    # Permit college.edu or common university subdomains
    return domain == allowed or domain.endswith("." + allowed) or domain in ("college.edu", "university.edu", "openclass.edu")


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
    email = payload.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
        )

    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user:
            from .services.roster import apply_ingested_student_profile
            return apply_ingested_student_profile(db, dict(user))

        # Fallback to students or faculty
        student = db.execute("SELECT * FROM students WHERE email = ?", (email,)).fetchone()
        if student:
            return {
                "id": student["id"],
                "email": student["email"],
                "name": student["name"],
                "role": "STUDENT",
                "batch_id": student["batch_id"],
                "phone": student["phone"] or "",
            }
        faculty = db.execute("SELECT * FROM faculty WHERE email = ?", (email,)).fetchone()
        if faculty:
            return {
                "id": faculty["id"],
                "email": faculty["email"],
                "name": faculty["full_name"],
                "role": "FACULTY",
                "batch_id": None,
                "phone": faculty["phone"] or "",
            }

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found in registry",
        )


def get_optional_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[dict]:
    if not credentials:
        return None
    try:
        return get_current_user(credentials)
    except Exception:
        return None


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


def authenticate_user(email: str, password: str, expected_role: Optional[str] = None) -> dict:
    email = email.strip().lower()
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
        if not user:
            # Check student or faculty records
            student = db.execute("SELECT * FROM students WHERE LOWER(email) = ?", (email,)).fetchone()
            if student:
                user_role = "STUDENT"
                user_name = student["name"]
                batch = student["batch_id"]
                phone = student["phone"] or ""
            else:
                faculty = db.execute("SELECT * FROM faculty WHERE LOWER(email) = ?", (email,)).fetchone()
                if faculty:
                    user_role = "FACULTY"
                    user_name = faculty["full_name"]
                    batch = None
                    phone = faculty["phone"] or ""
                else:
                    from .services.roster import find_ingested_student
                    user_name = email.split("@")[0].replace(".", " ").title()
                    user_role = (expected_role or "STUDENT").upper()
                    roster_student = find_ingested_student(db, email=email, name=user_name)
                    if roster_student:
                        user_name = roster_student.get("name") or user_name
                        batch = roster_student.get("batch_id") if user_role == "STUDENT" else None
                    else:
                        batch = None
                    phone = ""

            stamp = now()
            hashed = hash_password(password)
            cur = db.execute(
                """INSERT INTO users (email, name, role, password_hash, phone, batch_id, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash""",
                (email, user_name, user_role, hashed, phone, batch, stamp, stamp)
            )
            user = db.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()

        user_dict = dict(user)
        from .services.roster import apply_ingested_student_profile
        user_dict = apply_ingested_student_profile(db, user_dict)

        # Enforce role matching tab if specified
        if expected_role and user_dict["role"].upper() != expected_role.upper():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This account is registered as {user_dict['role'].title()}. Please switch to the {user_dict['role'].title()} tab to sign in.",
            )

        # Check password hash
        if user_dict.get("password_hash"):
            if not verify_password(password, user_dict["password_hash"]):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid password. Please check your credentials.",
                )
        else:
            # Set password on first successful login
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_dict["id"]))

    token_payload = {
        "sub": str(user_dict["id"]),
        "user_id": user_dict["id"],
        "email": user_dict["email"],
        "name": user_dict["name"],
        "role": user_dict["role"],
        "batch_id": user_dict.get("batch_id"),
    }
    access_token = create_access_token(token_payload)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_dict,
    }


def verify_and_provision_ms_user(
    email: str,
    name: str,
    role: str = "STUDENT",
    batch_id: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict:
    email = email.strip().lower()
    role = role.upper()
    if role not in {"FACULTY", "STUDENT"}:
        role = "STUDENT"

    stamp = now()
    with connect() as db:
        from .services.roster import find_ingested_student
        roster_student = find_ingested_student(db, email=email, name=name) if role == "STUDENT" else None
        if roster_student:
            name = roster_student.get("name") or name
            batch_id = batch_id or roster_student.get("batch_id")
        existing = db.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email,)).fetchone()
        if existing:
            db.execute(
                "UPDATE users SET name = ?, role = ?, batch_id = COALESCE(?, batch_id), phone = COALESCE(?, phone), updated_at = ? WHERE id = ?",
                (name, role, batch_id, phone, stamp, existing["id"]),
            )
            user_id = existing["id"]
        else:
            cursor = db.execute(
                "INSERT INTO users (email, name, role, batch_id, phone, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (email, name, role, batch_id, phone, stamp, stamp),
            )
            user_id = cursor.lastrowid

        # Also sync to students or faculty tables
        if role == "STUDENT":
            existing_std = db.execute("SELECT id FROM students WHERE LOWER(email) = ?", (email,)).fetchone()
            if existing_std:
                db.execute(
                    "UPDATE students SET name = ?, batch_id = COALESCE(?, batch_id), phone = COALESCE(?, phone), updated_at = ? WHERE id = ?",
                    (name, batch_id, phone, stamp, existing_std["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO students (id, name, email, phone, batch_id, active, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                    (str(user_id), name, email, phone, batch_id, stamp),
                )
        elif role == "FACULTY":
            existing_fac = db.execute("SELECT id FROM faculty WHERE LOWER(email) = ?", (email,)).fetchone()
            if existing_fac:
                db.execute(
                    "UPDATE faculty SET full_name = ?, phone = COALESCE(?, phone), updated_at = ? WHERE id = ?",
                    (name, phone, stamp, existing_fac["id"]),
                )
            else:
                db.execute(
                    """INSERT INTO faculty (full_name, email, phone, active, updated_at)
                       VALUES (?, ?, ?, 1, ?)
                       ON CONFLICT(full_name) DO UPDATE SET email=excluded.email, phone=COALESCE(excluded.phone, faculty.phone), updated_at=excluded.updated_at""",
                    (name, email, phone, stamp),
                )

        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        user_dict = dict(row)
        from .services.roster import apply_ingested_student_profile
        user_dict = apply_ingested_student_profile(db, user_dict)

    token_payload = {
        "sub": str(user_dict["id"]),
        "user_id": user_dict["id"],
        "email": user_dict["email"],
        "name": user_dict["name"],
        "role": user_dict["role"],
        "batch_id": user_dict.get("batch_id"),
    }
    access_token = create_access_token(token_payload)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_dict,
    }
