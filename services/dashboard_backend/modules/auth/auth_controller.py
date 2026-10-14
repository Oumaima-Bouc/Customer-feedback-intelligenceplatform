from __future__ import annotations
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from config.database import get_conn
from middleware.auth_middleware import create_token, hash_password, verify_password, get_current_user
from modules.settings.dto.update_password_dto import UpdatePasswordDTO
from shared.utils.date_helper import to_iso

router = APIRouter(tags=["Auth"])

# Brute-force protection: lock an account for LOCKOUT_MINUTES after
# MAX_LOGIN_ATTEMPTS consecutive failures (uses users.login_attempts /
# users.locked_until from migration 008).
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(req: LoginRequest):
    now = datetime.now(timezone.utc)
    # Do all DB work inside the transaction, then raise/return AFTER it commits.
    # (get_conn() rolls back if an exception escapes the block, which would
    # otherwise discard the failed-attempt counter increment.)
    outcome: tuple = ("invalid",)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role, is_active, "
            "login_attempts, locked_until, password_change_required "
            "FROM users WHERE username = %s",
            (req.username,),
        )
        row = cur.fetchone()
        if row:
            uid, uname, phash, role, is_active, attempts, locked_until, pcr = row
            if locked_until is not None and locked_until > now:
                outcome = ("locked",)
            elif not verify_password(req.password, phash):
                attempts = (attempts or 0) + 1
                if attempts >= MAX_LOGIN_ATTEMPTS:
                    cur.execute(
                        "UPDATE users SET login_attempts = 0, locked_until = %s WHERE id = %s",
                        (now + timedelta(minutes=LOCKOUT_MINUTES), uid),
                    )
                    outcome = ("locked",)
                else:
                    cur.execute(
                        "UPDATE users SET login_attempts = %s WHERE id = %s",
                        (attempts, uid),
                    )
                    outcome = ("invalid",)
            elif not is_active:
                outcome = ("inactive",)
            else:
                cur.execute(
                    "UPDATE users SET login_attempts = 0, locked_until = NULL, last_login_at = %s WHERE id = %s",
                    (now, uid),
                )
                token = create_token(uid, uname, role, is_active)
                outcome = ("ok", token, role, is_active, bool(pcr))

    kind = outcome[0]
    if kind == "locked":
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account temporarily locked after {MAX_LOGIN_ATTEMPTS} failed attempts. "
                   f"Try again in {LOCKOUT_MINUTES} minutes.",
        )
    if kind == "inactive":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    if kind != "ok":
        # Generic message — do not reveal whether the username exists.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    _, token, role, is_active, pcr = outcome
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": role,
        "is_active": is_active,
        "password_change_required": pcr,
    }


@router.post("/auth/logout")
async def logout(user: dict = Depends(get_current_user)):
    return {"status": "logged_out"}


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, email, role, is_active, last_login_at, created_at, "
            "password_change_required FROM users WHERE id = %s",
            (int(user["sub"]),),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "role": row[3],
        "is_active": row[4],
        "last_login_at": to_iso(row[5]),
        "created_at": to_iso(row[6]),
        "password_change_required": bool(row[7]),
        "permissions": {
            "can_edit_settings": row[3] in ("admin", "user") and row[4],
            "can_manage_sources": row[3] in ("admin", "user") and row[4],
            "can_manage_users": row[3] == "admin",
        },
    }


@router.put("/me/password")
async def change_password(req: UpdatePasswordDTO, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (int(user["sub"]),))
        row = cur.fetchone()
        if not row or not verify_password(req.old_password, row[0]):
            raise HTTPException(status_code=401, detail="Current password is incorrect")
        # Clear the forced-change flag and any lockout state on a successful change.
        cur.execute(
            "UPDATE users SET password_hash = %s, password_change_required = FALSE, "
            "login_attempts = 0, locked_until = NULL WHERE id = %s",
            (hash_password(req.new_password), int(user["sub"])),
        )
    return {"status": "updated"}
