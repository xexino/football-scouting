"""Audit log access and full data export (logical backup)."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import Base, get_db
from ..models import AuditLog, User
from ..security import require

router = APIRouter(prefix="/api/admin", tags=["administration"])


@router.get("/audit-logs")
def audit_logs(action: str | None = None, entity_type: str | None = None, user_id: int | None = None,
               limit: int = Query(100, le=1000), offset: int = 0,
               _: User = Depends(require("audit:read")), db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if user_id:
        q = q.where(AuditLog.user_id == user_id)
    return [{"id": a.id, "user_id": a.user_id, "user_email": a.user_email, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "details": a.details,
             "ip_address": a.ip_address, "created_at": a.created_at}
            for a in db.scalars(q.offset(offset).limit(limit)).all()]


def _default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(type(o))


@router.get("/export", summary="Full logical backup as JSON (password hashes excluded)")
def export_all(request: Request, user: User = Depends(require("backup:run")), db: Session = Depends(get_db)):
    dump: dict = {"exported_at": datetime.now(timezone.utc).isoformat(), "format": "raja-scout-export-v1", "tables": {}}
    for table in Base.metadata.sorted_tables:
        rows = [dict(r._mapping) for r in db.execute(table.select()).all()]
        if table.name == "users":
            for r in rows:
                r.pop("hashed_password", None)
        dump["tables"][table.name] = rows
    audit.log(db, user, "admin.export", None, None, {"tables": len(dump["tables"])}, request)
    db.commit()
    body = json.dumps(dump, default=_default, ensure_ascii=False, indent=1)
    return Response(body, media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=raja_scout_export_{date.today().isoformat()}.json"})
