"""Subscription status as seen by an organization's members (read-only)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import Ctx, get_ctx
from ..subscriptions import PLANS, summary

router = APIRouter(prefix="/api/subscription", tags=["subscription"])


@router.get("", summary="Plan, status, limits and usage of the current organization")
def my_subscription(ctx: Ctx = Depends(get_ctx), db: Session = Depends(get_db)):
    out = summary(db, ctx.organization)
    out["available_plans"] = [{"code": p.code, "name": p.name, "seats": p.seats, "private_players": p.private_players,
                               "features": sorted(p.features), "description": p.description} for p in PLANS.values()]
    return out
