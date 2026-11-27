"""Authentication (bcrypt + JWT) and role-based access control."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# --------------------------------------------------------------------------- permissions
ALL_PERMISSIONS = {
    "players:read",
    "players:write",
    "players:delete",
    "financials:read",     # transfer fees, salaries, agent
    "stats:write",
    "import:run",
    "video:write",
    "match_reports:write",
    "reports:write",
    "reports:finalize",
    "pipeline:read",
    "pipeline:move",       # move between scouting stages
    "pipeline:approve",    # move into / out of 'approved'
    "pipeline:negotiate",  # move into 'negotiation' / 'signed'
    "budget:manage",
    "users:manage",
    "audit:read",
    "backup:run",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "administrator": set(ALL_PERMISSIONS),
    "sporting_director": {
        "players:read", "players:write", "financials:read", "reports:write", "reports:finalize",
        "pipeline:read", "pipeline:move", "pipeline:approve", "pipeline:negotiate",
        "budget:manage", "audit:read", "backup:run", "match_reports:write",
    },
    "head_of_scouting": {
        "players:read", "players:write", "players:delete", "financials:read", "stats:write",
        "import:run", "video:write", "match_reports:write", "reports:write", "reports:finalize",
        "pipeline:read", "pipeline:move", "audit:read",
    },
    "data_analyst": {
        "players:read", "players:write", "stats:write", "import:run", "reports:write",
        "pipeline:read", "pipeline:move",
    },
    "video_scout": {
        "players:read", "video:write", "match_reports:write", "reports:write",
        "pipeline:read", "pipeline:move",
    },
    "regional_scout": {
        "players:read", "players:write", "match_reports:write", "reports:write",
        "pipeline:read", "pipeline:move",
    },
}

ROLE_LABELS = {
    "administrator": "Administrator",
    "sporting_director": "Sporting Director",
    "head_of_scouting": "Head of Scouting",
    "data_analyst": "Data Analyst",
    "video_scout": "Video Scout",
    "regional_scout": "Regional Scout",
}


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(user: User, perm: str) -> bool:
    return perm in permissions_for(user.role)


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if not any(c.isdigit() for c in password):
        problems.append("a digit")
    if not any(c.isalpha() for c in password):
        problems.append("a letter")
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Password must contain " + ", ".join(problems))


# --------------------------------------------------------------------------- login throttle
_failed_logins: dict[str, list[float]] = defaultdict(list)


def check_login_allowed(key: str) -> None:
    now = time.time()
    window = settings.login_lockout_seconds
    attempts = [t for t in _failed_logins[key] if now - t < window]
    _failed_logins[key] = attempts
    if len(attempts) >= settings.max_login_attempts:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed login attempts. Try again later.")


def record_failed_login(key: str) -> None:
    _failed_logins[key].append(time.time())


def clear_failed_logins(key: str) -> None:
    _failed_logins.pop(key, None)


# --------------------------------------------------------------------------- tokens
def create_access_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes)
    payload = {"sub": str(user.id), "role": user.role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Invalid or expired credentials", headers={"WWW-Authenticate": "Bearer"}
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require(*perms: str):
    """Dependency factory: the current user must hold *all* listed permissions."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        missing = [p for p in perms if not has_permission(user, p)]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {', '.join(missing)}")
        return user

    return dependency
