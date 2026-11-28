"""Organization (tenant) lifecycle: export and deletion.

Deletion is two-step so it can never happen by accident:

1. ``schedule_deletion`` — status ``pending_deletion``: every member loses access
   immediately (tokens are refused), data is retained so it can still be exported or the
   request cancelled.
2. ``purge_organization`` — only for an organization already scheduled, and only with the
   organization's slug typed as confirmation. Deletes the organization row; every tenant
   table references it with ``ON DELETE CASCADE``, so all private rows go with it. Shared
   reference data is untouched. Accounts that belong to no other organization (and are not
   platform operators) are deleted too. A platform-level audit record (organization_id NULL)
   is kept with row counts, without personal data.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .database import Base
from .models import AuditLog, Membership, Organization, User
from .tenancy import SYSTEM, TenantPrivate, SharedOrPrivate, get_tenant


def _require_system(db: Session) -> None:
    if get_tenant(db) is not SYSTEM:
        raise RuntimeError("Organization lifecycle operations require the SYSTEM context")


def schedule_deletion(db: Session, org: Organization, actor_email: str | None = None) -> None:
    _require_system(db)
    if org.status == "pending_deletion":
        return
    org.status = "pending_deletion"
    db.add(AuditLog(organization_id=None, user_email=actor_email, action="organization.deletion_scheduled",
                    entity_type="organization", entity_id=org.id, details={"slug": org.slug}))


def cancel_deletion(db: Session, org: Organization, actor_email: str | None = None) -> None:
    _require_system(db)
    org.status = "active"
    db.add(AuditLog(organization_id=None, user_email=actor_email, action="organization.deletion_cancelled",
                    entity_type="organization", entity_id=org.id, details={"slug": org.slug}))


def tenant_row_counts(db: Session, org_id: int) -> dict[str, int]:
    out = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if issubclass(cls, (TenantPrivate, SharedOrPrivate)):
            out[cls.__tablename__] = db.scalar(select(func.count()).select_from(cls)
                                               .where(cls.organization_id == org_id)) or 0
    return out


def purge_organization(db: Session, org: Organization, confirm_slug: str, actor_email: str | None = None) -> dict:
    _require_system(db)
    if org.status != "pending_deletion":
        raise ValueError("Schedule the deletion first (organization must be in 'pending_deletion')")
    if confirm_slug != org.slug:
        raise ValueError("Confirmation does not match the organization slug")
    org_id, slug = org.id, org.slug
    counts = tenant_row_counts(db, org_id)
    member_ids = list(db.scalars(select(Membership.user_id).where(Membership.organization_id == org_id)).all())
    db.execute(delete(Organization).where(Organization.id == org_id))  # cascades to all tenant tables
    db.expunge_all()
    removed_users = 0
    for uid in member_ids:
        user = db.get(User, uid)
        if user is None or user.is_platform_admin:
            continue
        others = db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == uid))
        if not others:
            db.delete(user)
            removed_users += 1
    db.add(AuditLog(organization_id=None, user_email=actor_email, action="organization.purged",
                    entity_type="organization", entity_id=org_id,
                    details={"slug": slug, "rows_deleted": counts, "accounts_deleted": removed_users}))
    db.flush()
    return {"organization_id": org_id, "slug": slug, "rows_deleted": counts, "accounts_deleted": removed_users}
