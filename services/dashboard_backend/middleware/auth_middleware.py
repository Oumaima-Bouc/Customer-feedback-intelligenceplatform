from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from config.environment import settings
security = HTTPBearer(auto_error=False)
def hash_password(password: str) -> str: return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def verify_password(plain: str, hashed: str) -> bool: return bcrypt.checkpw(plain.encode(), hashed.encode())
def create_token(user_id: int, username: str, role: str, is_active: bool) -> str:
    payload = {"sub": str(user_id), "username": username, "role": role, "is_active": is_active, "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
def decode_token(token: str) -> Optional[dict]:
    try: return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception: return None
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not credentials: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if payload is None: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload
def require_admin(user: dict) -> None:
    if user.get("role") != "admin": raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
def require_editor(user: dict) -> None:
    if user.get("role") not in ("admin", "user") or not user.get("is_active", True): raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions or account inactive")
