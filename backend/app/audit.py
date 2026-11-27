"""Audit logging helper. Every state-changing action should call ``log``."""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User


def log(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
    request: Request | None = None,
) -> None:
    ip = None
    if request is not None and request.client is not None:
        ip = request.headers.get("x-forwarded-for", request.client.host)
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip,
        )
    )
