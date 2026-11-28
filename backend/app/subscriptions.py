"""SaaS subscription plans, status and limit enforcement.

Prices are intentionally NOT defined in code: the founder sets commercial terms (see
docs/saas/06_BILLING_OPTIONS.md). Limits and features are what the software enforces.

Access policy (enforced in the backend, ``security.get_ctx`` and the limit helpers below):

* demo organizations: unlimited, no subscription needed (demo deployments only);
* effective status ``trialing`` / ``active`` / ``past_due`` within the grace period: full access;
* anything else (``expired``, ``suspended``, ``canceled``, past_due beyond grace, or no
  subscription at all): **read-only** — data stays visible and exportable, writes get 402.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Invitation, Membership, Organization, Player, Subscription

GRACE_DAYS = 14          # after a missed renewal, before the organization becomes read-only
TRIAL_DAYS = 30
STATUSES = ("trialing", "active", "past_due", "suspended", "canceled", "expired")
WRITABLE = ("trialing", "active", "past_due")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    seats: int | None              # active members + pending invitations; None = unlimited
    private_players: int | None    # players owned by the organization; None = unlimited
    features: frozenset
    description: str


PLANS: dict[str, Plan] = {p.code: p for p in [
    Plan("scout", "Scout", seats=3, private_players=300,
         features=frozenset({"video", "reports", "pipeline", "comparison", "csv_import", "export"}),
         description="Small clubs, academies and independent scouting cells."),
    Plan("club_pro", "Club Pro", seats=15, private_players=5000,
         features=frozenset({"video", "reports", "pipeline", "comparison", "csv_import", "export", "api_import"}),
         description="Professional clubs with a full recruitment department."),
    Plan("enterprise", "Enterprise", seats=None, private_players=None,
         features=frozenset({"video", "reports", "pipeline", "comparison", "csv_import", "export", "api_import",
                             "priority_support"}),
         description="Federations, multi-club groups and large clubs; custom terms."),
]}
DEFAULT_TRIAL_PLAN = "club_pro"


def _aware(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def now() -> datetime:
    return datetime.now(timezone.utc)


def get_subscription(db: Session, org_id: int) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.organization_id == org_id))


def new_trial(org_id: int, plan: str = DEFAULT_TRIAL_PLAN, days: int = TRIAL_DAYS) -> Subscription:
    return Subscription(organization_id=org_id, plan=plan, status="trialing", billing_provider="manual",
                        trial_ends_at=now() + timedelta(days=days))


def effective_status(sub: Subscription | None) -> str:
    if sub is None:
        return "none"
    t = now()
    if sub.status == "trialing" and sub.trial_ends_at and _aware(sub.trial_ends_at) < t:
        return "expired"
    if sub.status in ("active", "past_due") and sub.current_period_end:
        end = _aware(sub.current_period_end)
        if t > end + timedelta(days=GRACE_DAYS):
            return "expired"
        if t > end:
            return "past_due"
    return sub.status


def is_writable(org: Organization, sub: Subscription | None) -> bool:
    return org.is_demo or effective_status(sub) in WRITABLE


def plan_for(org: Organization, sub: Subscription | None) -> Plan | None:
    if org.is_demo:
        return None  # demo: unlimited
    return PLANS.get(sub.plan) if sub else None


def limits(org: Organization, sub: Subscription | None) -> dict:
    if org.is_demo:
        return {"seats": None, "private_players": None, "features": sorted(PLANS["enterprise"].features)}
    plan = plan_for(org, sub)
    seats = sub.seats_override if sub and sub.seats_override is not None else (plan.seats if plan else 0)
    players = (sub.players_override if sub and sub.players_override is not None
               else (plan.private_players if plan else 0))
    return {"seats": seats, "private_players": players, "features": sorted(plan.features) if plan else []}


def usage(db: Session, org_id: int) -> dict:
    members = db.scalar(select(func.count()).select_from(Membership).where(
        Membership.organization_id == org_id, Membership.is_active.is_(True))) or 0
    pending = db.scalar(select(func.count()).select_from(Invitation).where(
        Invitation.organization_id == org_id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
        Invitation.expires_at > now())) or 0
    players = db.scalar(select(func.count()).select_from(Player).where(Player.organization_id == org_id)) or 0
    return {"active_members": members, "pending_invitations": pending, "seats_used": members + pending,
            "private_players": players}


def summary(db: Session, org: Organization) -> dict:
    sub = get_subscription(db, org.id)
    eff = "demo" if org.is_demo else effective_status(sub)
    plan = plan_for(org, sub)
    out = {
        "plan": "demo" if org.is_demo else (sub.plan if sub else None),
        "plan_name": "Demo (unlimited)" if org.is_demo else (plan.name if plan else None),
        "status": sub.status if sub else None,
        "effective_status": eff,
        "writable": is_writable(org, sub),
        "trial_ends_at": sub.trial_ends_at if sub else None,
        "current_period_end": sub.current_period_end if sub else None,
        "grace_days": GRACE_DAYS,
        "billing_provider": sub.billing_provider if sub else None,
        "limits": limits(org, sub),
        "usage": usage(db, org.id),
    }
    if sub and eff == "trialing" and sub.trial_ends_at:
        out["trial_days_left"] = max(0, (_aware(sub.trial_ends_at) - now()).days)
    return out


# --------------------------------------------------------------------------- enforcement
def _payment_required(msg: str) -> HTTPException:
    return HTTPException(402, msg)


def assert_writable(db: Session, org: Organization, method: str) -> None:
    if method in SAFE_METHODS or org.is_demo:
        return
    sub = get_subscription(db, org.id)
    if not is_writable(org, sub):
        status = effective_status(sub)
        raise _payment_required(
            f"Your organization's subscription is {status if status != 'none' else 'not set up'}: the workspace is "
            "read-only. Your data remains available and exportable. Contact your account manager to renew.")


def enforce_seat_limit(db: Session, org: Organization, adding: int = 1) -> None:
    if org.is_demo:
        return
    cap = limits(org, get_subscription(db, org.id))["seats"]
    if cap is not None and usage(db, org.id)["seats_used"] + adding > cap:
        raise _payment_required(f"User seat limit reached ({cap} on your plan, including pending invitations). "
                                "Deactivate a member, revoke an invitation or upgrade your plan.")


def enforce_player_limit(db: Session, org: Organization, adding: int = 1) -> None:
    if org.is_demo:
        return
    cap = limits(org, get_subscription(db, org.id))["private_players"]
    if cap is not None and usage(db, org.id)["private_players"] + adding > cap:
        raise _payment_required(f"Private player limit reached ({cap} on your plan). Upgrade to add more players.")


def require_feature(db: Session, org: Organization, feature: str) -> None:
    if org.is_demo:
        return
    if feature not in limits(org, get_subscription(db, org.id))["features"]:
        raise _payment_required(f"'{feature.replace('_', ' ')}' is not included in your plan.")
