"""Platform operator console (the SaaS company). Organization and subscription management only.

Platform administrators have NO access to tenant scouting data: these endpoints expose
organization metadata, subscription state and usage counts, never players, reports, notes,
valuations or videos. Every action is recorded as a platform-level audit event
(organization_id NULL), invisible to tenants.
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..accounts import expiry, invitation_link, new_token, send_link
from ..billing import get_provider
from ..config import settings
from ..database import get_db
from ..lifecycle import cancel_deletion, purge_organization, schedule_deletion
from ..models import AuditLog, Invitation, Organization, User
from ..routers.organization import CURRENCIES
from ..security import require_platform_admin
from ..serializers import organization_out
from ..subscriptions import PLANS, STATUSES, TRIAL_DAYS, get_subscription, new_trial, summary

router = APIRouter(prefix="/api/platform", tags=["platform (SaaS operator)"])


def _org(db: Session, org_id: int) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "Organization not found")
    return org


def _org_row(db: Session, org: Organization) -> dict:
    return {**organization_out(org), "logo_data_url": None, "created_at": org.created_at,
            "subscription": summary(db, org)}


@router.get("/organizations", summary="All organizations with subscription state and usage counts")
def list_orgs(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return [_org_row(db, o) for o in db.scalars(select(Organization).order_by(Organization.name)).all()]


@router.get("/plans")
def plans(_: User = Depends(require_platform_admin)):
    return [{"code": p.code, "name": p.name, "seats": p.seats, "private_players": p.private_players,
             "features": sorted(p.features), "description": p.description} for p in PLANS.values()]


class OrgCreate(BaseModel):
    slug: str = Field(min_length=3, max_length=60)
    name: str = Field(min_length=2, max_length=200)
    country: str | None = None
    currency: str = "EUR"
    primary_language: str = "en"
    plan: str = "club_pro"
    trial_days: int = Field(default=TRIAL_DAYS, ge=0, le=90)
    admin_email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @field_validator("slug")
    @classmethod
    def _slug(cls, v):
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", v):
            raise ValueError("slug: lowercase letters, digits and hyphens")
        return v

    @field_validator("plan")
    @classmethod
    def _plan(cls, v):
        if v not in PLANS:
            raise ValueError(f"plan must be one of {', '.join(PLANS)}")
        return v

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        if v.upper() not in CURRENCIES:
            raise ValueError("unsupported currency")
        return v.upper()


@router.post("/organizations", status_code=201,
             summary="Create an organization with a trial and an invitation for its first administrator")
def create_org(body: OrgCreate, request: Request, user: User = Depends(require_platform_admin),
               db: Session = Depends(get_db)):
    if db.scalar(select(Organization).where(Organization.slug == body.slug)):
        raise HTTPException(409, "Slug already in use")
    org = Organization(slug=body.slug, name=body.name, country=body.country, currency=body.currency,
                       primary_language=body.primary_language, settings={},
                       is_demo=settings.deployment_mode == "demo")  # never mix demo and customer data
    db.add(org)
    db.flush()
    db.add(new_trial(org.id, body.plan, body.trial_days))
    raw, digest = new_token()
    email = body.admin_email.strip().lower()
    db.add(Invitation(organization_id=org.id, email=email, role="administrator", token_hash=digest,
                      expires_at=expiry(settings.invitation_ttl_hours), created_by_id=user.id))
    link = invitation_link(request, raw)
    emailed = send_link(email, f"Your {body.name} workspace", link)
    audit.log(db, user, "platform.organization_create", "organization", org.id,
              {"slug": body.slug, "plan": body.plan, "trial_days": body.trial_days, "admin_email": email}, request)
    db.commit()
    return {**_org_row(db, org), "admin_invite_url": link, "emailed": emailed}


class SubscriptionUpdate(BaseModel):
    plan: str | None = None
    status: str | None = None
    trial_ends_at: datetime | None = None
    current_period_end: datetime | None = None
    seats_override: int | None = Field(default=None, ge=0)
    players_override: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("plan")
    @classmethod
    def _plan(cls, v):
        if v is not None and v not in PLANS:
            raise ValueError(f"plan must be one of {', '.join(PLANS)}")
        return v

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        return v


@router.patch("/organizations/{org_id}/subscription",
              summary="Change plan, status, period, trial or limit overrides (manual billing)")
def update_subscription(org_id: int, body: SubscriptionUpdate, request: Request,
                        user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    org = _org(db, org_id)
    if org.is_demo:
        raise HTTPException(422, "Demo organizations have no subscription")
    sub = get_subscription(db, org.id)
    if sub is None:
        sub = new_trial(org.id)
        db.add(sub)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(sub, k, v)
    audit.log(db, user, "platform.subscription_update", "organization", org.id,
              {k: str(v) if v is not None else None for k, v in changes.items()}, request)
    db.commit()
    return _org_row(db, org)


@router.post("/organizations/{org_id}/suspend", summary="Suspend (read-only access, data kept)")
def suspend(org_id: int, request: Request, user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return update_subscription(org_id, SubscriptionUpdate(status="suspended"), request, user, db)


@router.post("/organizations/{org_id}/reactivate", summary="Reactivate a suspended or expired subscription")
def reactivate(org_id: int, request: Request, user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return update_subscription(org_id, SubscriptionUpdate(status="active"), request, user, db)


@router.post("/organizations/{org_id}/schedule-deletion", summary="Step 1: block all access, keep data")
def schedule_delete(org_id: int, request: Request, user: User = Depends(require_platform_admin),
                    db: Session = Depends(get_db)):
    org = _org(db, org_id)
    schedule_deletion(db, org, user.email)
    db.commit()
    return _org_row(db, org)


@router.post("/organizations/{org_id}/cancel-deletion")
def cancel_delete(org_id: int, request: Request, user: User = Depends(require_platform_admin),
                  db: Session = Depends(get_db)):
    org = _org(db, org_id)
    cancel_deletion(db, org, user.email)
    db.commit()
    return _org_row(db, org)


class PurgeIn(BaseModel):
    confirm_slug: str


@router.post("/organizations/{org_id}/purge", summary="Step 2: permanently delete all organization data")
def purge(org_id: int, body: PurgeIn, user: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    org = _org(db, org_id)
    try:
        result = purge_organization(db, org, body.confirm_slug, user.email)
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return result


@router.get("/audit-logs", summary="Platform-level audit events (never tenant events)")
def platform_audit(limit: int = 200, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).where(AuditLog.organization_id.is_(None))
                      .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(min(limit, 1000))).all()
    return [{"id": a.id, "user_email": a.user_email, "action": a.action, "entity_type": a.entity_type,
             "entity_id": a.entity_id, "details": a.details, "created_at": a.created_at} for a in rows]


# --------------------------------------------------------------------------- billing webhooks
billing_router = APIRouter(prefix="/api/billing", tags=["billing"])


@billing_router.post("/webhook/{provider}", summary="Billing provider webhook (disabled for the manual provider)")
async def webhook(provider: str, request: Request):
    try:
        p = get_provider(provider)
    except RuntimeError:
        raise HTTPException(404, "Unknown billing provider")
    if not p.supports_webhooks:
        raise HTTPException(404, "This billing provider does not use webhooks")
    raise HTTPException(501, "Webhook handling not implemented for this provider")  # pragma: no cover
