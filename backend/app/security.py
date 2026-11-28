"""Authentication (bcrypt + JWT) and role-based access control."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import LoginAttempt, Membership, Organization, User
from .tenancy import NOT_SET, SYSTEM, set_tenant

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
    "users:manage",        # manage members of the organization
    "org:manage",          # organization identity & settings
    "audit:read",
    "backup:run",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "administrator": set(ALL_PERMISSIONS),  # organization administrator
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
    "administrator": "Organization Administrator",
    "sporting_director": "Sporting Director",
    "head_of_scouting": "Head of Scouting",
    "data_analyst": "Data Analyst",
    "video_scout": "Video Scout",
    "regional_scout": "Regional Scout",
}


def permissions_for(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def has_permission(subject, perm: str) -> bool:
    role = subject if isinstance(subject, str) else subject.role
    return perm in permissions_for(role)


# --------------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds=12)).decode()


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check when the account does not exist (no user enumeration by timing)."""
    verify_password(password, _DUMMY_HASH)


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
    if len(password.encode("utf-8")) > 72:  # bcrypt limit; longer values would be silently truncated / error
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Password must be at most 72 bytes")
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Password must contain " + ", ".join(problems))


# --------------------------------------------------------------------------- login throttle
# Stored in the database (table login_attempts) so limits hold across workers/instances and
# survive restarts. Two independent limits: per account and per client IP.
def _recent(db: Session, key: str) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.login_lockout_seconds)
    return db.scalar(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.key == key, LoginAttempt.created_at >= cutoff)) or 0


def check_login_allowed(db: Session, email: str, ip: str | None) -> None:
    if _recent(db, f"account:{email}") >= settings.max_login_attempts or (
            ip and _recent(db, f"ip:{ip}") >= settings.max_login_attempts_per_ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed login attempts. Try again later.")


def record_failed_login(db: Session, email: str, ip: str | None) -> None:
    db.add(LoginAttempt(key=f"account:{email}"))
    if ip:
        db.add(LoginAttempt(key=f"ip:{ip}"))
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(settings.login_lockout_seconds, 3600))
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))  # housekeeping


def clear_failed_logins(db: Session, email: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.key == f"account:{email}"))


# --------------------------------------------------------------------------- tokens
def create_access_token(user: User, organization_id: int | None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes)
    payload = {"sub": str(user.id), "org": organization_id, "ver": user.token_version, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired credentials",
                         headers={"WWW-Authenticate": "Bearer"})


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        int(payload["sub"])
        return payload
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise _unauthorized()


def _load_user(db: Session, payload: dict) -> User:
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or payload.get("ver") != user.token_version:
        raise _unauthorized()
    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """Authenticated user, *without* a tenant context (auth / platform endpoints only)."""
    user = _load_user(db, decode_token(token))
    set_tenant(db, NOT_SET)
    return user


@dataclass
class Ctx:
    """Request context for tenant endpoints: who, in which organization, with which role."""

    user: User
    membership: Membership
    organization: Organization

    # Convenience pass-throughs so routers can treat the context like a user.
    @property
    def id(self) -> int:
        return self.user.id

    @property
    def email(self) -> str:
        return self.user.email

    @property
    def full_name(self) -> str:
        return self.user.full_name

    @property
    def role(self) -> str:
        return self.membership.role

    @property
    def organization_id(self) -> int:
        return self.organization.id

    @property
    def permissions(self) -> set[str]:
        return permissions_for(self.role)


def get_ctx(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Ctx:
    payload = decode_token(token)
    user = _load_user(db, payload)
    org_id = payload.get("org")
    if not isinstance(org_id, int):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No organization selected for this session")
    membership = db.scalar(select(Membership).where(
        Membership.user_id == user.id, Membership.organization_id == org_id, Membership.is_active.is_(True)))
    org = db.get(Organization, org_id)
    if membership is None or org is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this organization")
    if org.status == "pending_deletion":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This organization is scheduled for deletion")
    from .subscriptions import assert_writable
    assert_writable(db, org, request.method)  # expired/suspended subscription => read-only (402 on writes)
    set_tenant(db, org.id)  # from here on every ORM query is scoped to this organization
    return Ctx(user=user, membership=membership, organization=org)


def require(*perms: str):
    """Dependency factory: tenant context whose role holds *all* listed permissions."""

    def dependency(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        missing = [p for p in perms if p not in ctx.permissions]
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {', '.join(missing)}")
        return ctx

    return dependency


def require_platform_admin(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform administrator access required")
    set_tenant(db, SYSTEM)  # platform endpoints only touch organization-level metadata
    return user
