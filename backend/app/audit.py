"""Audit logging helper. Every state-changing action should call ``log``."""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog


def log(
    db: Session,
    user,  # security.Ctx (tenant action), models.User (platform action) or None
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    details: dict | None = None,
    request: Request | None = None,
    organization_id: int | None = None,
) -> None:
    from .netutil import client_ip
    ip = client_ip(request) if request is not None else None
    org_id = organization_id if organization_id is not None else getattr(user, "organization_id", None)
    db.add(
        AuditLog(
            organization_id=org_id,
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip,
        )
    )
