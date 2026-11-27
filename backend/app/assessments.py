"""Helpers for the organization-private player assessment (valuation & opinion).

All queries run inside the request's tenant context, so they only ever see the current
organization's assessments."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ASSESSMENT_FIELDS, PlayerAssessment


def get_assessment(db: Session, player_id: int) -> PlayerAssessment | None:
    return db.scalar(select(PlayerAssessment).where(PlayerAssessment.player_id == player_id))


def get_assessments(db: Session, player_ids=None) -> dict[int, PlayerAssessment]:
    q = select(PlayerAssessment)
    if player_ids is not None:
        ids = list(player_ids)
        if not ids:
            return {}
        q = q.where(PlayerAssessment.player_id.in_(ids))
    return {a.player_id: a for a in db.scalars(q).all()}


def upsert_assessment(db: Session, player_id: int, data: dict, user_id: int | None) -> PlayerAssessment | None:
    values = {k: v for k, v in data.items() if k in ASSESSMENT_FIELDS}
    a = get_assessment(db, player_id)
    if a is None:
        if not any(v is not None for v in values.values()):
            return None
        a = PlayerAssessment(player_id=player_id)
        db.add(a)
    for k, v in values.items():
        setattr(a, k, v if not (k == "availability" and v is None) else "unknown")
    a.updated_by_id = user_id
    return a
