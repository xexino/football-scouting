"""Individual account provisioning: invitations and password-reset links.

* Tokens: 256-bit random, shown once, stored as SHA-256 hashes, single use, expiring.
* No e-mail provider is configured yet: the API returns the link to the administrator, who
  sends it through the club's own channel. Plug a real sender into ``send_link`` later.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from .config import settings

logger = logging.getLogger("raja_scout.accounts")


def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def expiry(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def is_expired(ts: datetime) -> bool:
    if ts.tzinfo is None:  # SQLite returns naive UTC
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < datetime.now(timezone.utc)


def base_url(request: Request) -> str:
    return settings.public_base_url or str(request.base_url).rstrip("/")


def invitation_link(request: Request, raw: str) -> str:
    return f"{base_url(request)}/#/invite/{raw}"


def reset_link(request: Request, raw: str) -> str:
    return f"{base_url(request)}/#/reset/{raw}"


def send_link(email: str, subject: str, link: str) -> bool:
    """E-mail delivery hook. Returns False while no provider is configured (link is shown to
    the administrator instead). Never log the raw link in production."""
    logger.info("Account link generated for %s (%s); no e-mail provider configured", email, subject)
    return False


def ensure_usable(token_row, kind: str) -> None:
    if token_row is None:
        raise HTTPException(404, f"Invalid {kind} link")
    if getattr(token_row, "revoked_at", None) is not None:
        raise HTTPException(410, f"This {kind} has been revoked")
    if getattr(token_row, "accepted_at", None) is not None or getattr(token_row, "used_at", None) is not None:
        raise HTTPException(410, f"This {kind} link has already been used")
    if is_expired(token_row.expires_at):
        raise HTTPException(410, f"This {kind} link has expired")
