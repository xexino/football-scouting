"""Organization (tenant) data export.

Runs inside the organization's tenant context, so every query is automatically limited
to that organization's private rows plus the shared reference rows it can see."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AuditLog,
    Club,
    DataSource,
    League,
    MatchReport,
    MatchVideo,
    Membership,
    Organization,
    PipelineEntry,
    PipelineEvent,
    Player,
    PlayerAssessment,
    PlayerSeasonStats,
    RecruitmentBudget,
    ScoutingReport,
    VideoObservation,
)
from .serializers import organization_out
from .tenancy import get_tenant

EXPORT_MODELS = [DataSource, League, Club, Player, PlayerAssessment, PlayerSeasonStats, MatchVideo,
                 VideoObservation, MatchReport, ScoutingReport, PipelineEntry, PipelineEvent,
                 RecruitmentBudget, AuditLog]


def _row(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in obj.__mapper__.column_attrs}


def export_organization(db: Session, org: Organization) -> dict:
    if get_tenant(db) != org.id:
        raise RuntimeError("Export must run in the organization's own tenant context")
    tables = {}
    for model in EXPORT_MODELS:
        # Only rows OWNED by the organization. Shared reference rows (organization_id NULL) are
        # platform-licensed data and must not be bulk-exported; exported rows still carry the
        # ids of the shared records they reference.
        q = select(model).where(model.organization_id == org.id).order_by(model.id)
        tables[model.__tablename__] = [_row(o) for o in db.scalars(q).all()]
    members = db.scalars(select(Membership).where(Membership.organization_id == org.id)).all()
    tables["members"] = [{"user_id": m.user_id, "email": m.user.email, "full_name": m.user.full_name,
                          "role": m.role, "region": m.region, "is_active": m.is_active} for m in members]
    return {
        "format": "raja-scout-intelligence-org-export-v2",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "organization": organization_out(org),
        "note": "Contains only rows owned by this organization. References to shared reference data "
                "(players, leagues, clubs, sources with organization_id = null) are kept as ids.",
        "tables": tables,
    }
