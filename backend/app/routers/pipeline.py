"""Recruitment pipeline.

Identified → Under Observation → Data Analysis → Video Analysis → Shortlisted →
Live Scouting → Approved → Negotiation → Signed / Rejected

Rules (see docs/USER_GUIDE.md):
* Forward moves go one stage at a time. Users with ``pipeline:approve`` may skip
  stages; the skip is recorded in the history.
* Moving backwards to an earlier stage is always allowed with a rationale.
* Entering or leaving *Approved* requires ``pipeline:approve`` (Sporting Director).
* Entering *Negotiation* or *Signed* requires ``pipeline:negotiate``.
* *Signed* is only reachable from *Negotiation* and is final.
* Evidence gates: *Shortlisted* needs ≥1 match report; *Approved* needs a finalised
  scouting report.
* Every move requires a note and creates an immutable PipelineEvent + audit entry.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session, selectinload

from ..assessments import get_assessment

from .. import audit
from ..analytics import age_on
from ..database import get_db
from ..models import (
    PIPELINE_STAGES,
    Club,
    MatchReport,
    Membership,
    PipelineEntry,
    PipelineEvent,
    Player,
    ScoutingReport,
    User,
)
from ..schemas import PipelineCreate, PipelineMove, PipelineUpdate
from ..security import Ctx, has_permission, require

router = APIRouter(prefix="/api/pipeline", tags=["recruitment pipeline"])

ORDER = [s for s in PIPELINE_STAGES if s != "rejected"]  # linear part
SCOUTING_STAGES = ORDER[:6]  # identified .. live_scouting


def _entry(db: Session, entry_id: int) -> PipelineEntry:
    e = db.scalar(select(PipelineEntry).where(PipelineEntry.id == entry_id).options(
        selectinload(PipelineEntry.player).selectinload(Player.club).selectinload(Club.league),
        selectinload(PipelineEntry.events).selectinload(PipelineEvent.user),
        selectinload(PipelineEntry.assigned_scout)).execution_options(populate_existing=True))
    if e is None:
        raise HTTPException(404, "Pipeline entry not found")
    return e


def entry_out(e: PipelineEntry, viewer: User, with_history: bool = False) -> dict:
    p = e.player
    can_fin = has_permission(viewer, "financials:read")
    assessment = get_assessment(object_session(e), p.id)
    out = {
        "id": e.id,
        "player_id": p.id,
        "player_name": p.full_name,
        "age": age_on(p.date_of_birth),
        "nationality": p.nationality,
        "position": p.primary_position,
        "club": p.club.name if p.club else None,
        "league": p.club.league.name if p.club and p.club.league else None,
        "is_fictional": p.is_fictional,
        "estimated_fee": (assessment.estimated_fee if assessment else None) if can_fin else None,
        "currency": viewer.organization.currency,
        "contract_expiry": p.contract_expiry,
        "stage": e.stage,
        "priority": e.priority,
        "target_position": e.target_position,
        "assigned_scout_id": e.assigned_scout_id,
        "assigned_scout_name": e.assigned_scout.full_name if e.assigned_scout else None,
        "rejection_reason": e.rejection_reason,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }
    if with_history:
        out["history"] = [{
            "id": ev.id, "from_stage": ev.from_stage, "to_stage": ev.to_stage, "note": ev.note,
            "user_id": ev.user_id, "user_name": ev.user.full_name if ev.user else None, "created_at": ev.created_at,
        } for ev in e.events]
    return out


def _require_member(db: Session, ctx, user_id: int) -> None:
    """Assignments may only point at active members of the same organization."""
    ok = db.scalar(select(Membership.id).where(Membership.user_id == user_id, Membership.is_active.is_(True),
                                               Membership.organization_id == ctx.organization_id))
    if ok is None:
        raise HTTPException(422, "The assigned scout must be an active member of your organization")


def check_transition(db: Session, user: User, e: PipelineEntry, to: str) -> list[str]:
    """Raise if the move is not allowed. Returns notes to append (e.g. skip warnings)."""
    frm = e.stage
    notes: list[str] = []
    if to == frm:
        raise HTTPException(422, "Player is already in this stage")
    if frm == "signed":
        raise HTTPException(409, "Signed is a final stage")
    if frm == "rejected":
        if to not in SCOUTING_STAGES:
            raise HTTPException(422, "A rejected player can only be re-opened into a scouting stage")
        return ["Re-opened after rejection"]
    if to == "rejected":
        if frm in ("approved", "negotiation") and not has_permission(user, "pipeline:approve"):
            raise HTTPException(403, "Only the Sporting Director can reject an approved target")
        return notes
    if "approved" in (frm, to) and not has_permission(user, "pipeline:approve"):
        raise HTTPException(403, "Only users with approval rights (Sporting Director) can move players into or out of Approved")
    if to in ("negotiation", "signed") and not has_permission(user, "pipeline:negotiate"):
        raise HTTPException(403, "Only the Sporting Director can open negotiations or confirm signings")
    if to == "signed" and frm != "negotiation":
        raise HTTPException(422, "A player can only be signed from Negotiation")
    if frm == "negotiation" and to in SCOUTING_STAGES and not has_permission(user, "pipeline:negotiate"):
        raise HTTPException(403, "Only the Sporting Director can move a player out of Negotiation")

    fi, ti = ORDER.index(frm), ORDER.index(to)
    if ti > fi + 1:
        if not has_permission(user, "pipeline:approve"):
            raise HTTPException(422, f"Stages must be completed in order: next stage is '{ORDER[fi + 1]}'")
        notes.append(f"Skipped stage(s): {', '.join(ORDER[fi + 1:ti])}")

    if ti > fi:  # evidence gates on forward moves
        if ti >= ORDER.index("shortlisted"):
            n = db.scalar(select(func.count()).select_from(MatchReport).where(MatchReport.player_id == e.player_id))
            if not n:
                raise HTTPException(422, "Evidence gate: at least one match report is required before shortlisting")
        if ti >= ORDER.index("approved"):
            n = db.scalar(select(func.count()).select_from(ScoutingReport).where(
                ScoutingReport.player_id == e.player_id, ScoutingReport.status == "final"))
            if not n:
                raise HTTPException(422, "Evidence gate: a finalised scouting report is required before approval")
    return notes


@router.get("", summary="Pipeline board grouped by stage")
def board(priority: str | None = None, position: str | None = None, assigned_to_me: bool = False,
          user: Ctx = Depends(require("pipeline:read")), db: Session = Depends(get_db)):
    q = select(PipelineEntry).options(
        selectinload(PipelineEntry.player).selectinload(Player.club).selectinload(Club.league),
        selectinload(PipelineEntry.assigned_scout))
    if priority:
        q = q.where(PipelineEntry.priority == priority)
    if assigned_to_me:
        q = q.where(PipelineEntry.assigned_scout_id == user.id)
    entries = db.scalars(q).all()
    if position:
        entries = [e for e in entries if e.player.primary_position == position or e.target_position == position]
    prio_rank = {"high": 0, "medium": 1, "low": 2}
    columns = {s: [] for s in PIPELINE_STAGES}
    for e in sorted(entries, key=lambda e: (prio_rank.get(e.priority, 3), e.updated_at), reverse=False):
        columns[e.stage].append(entry_out(e, user))
    return {"stages": list(PIPELINE_STAGES), "columns": columns, "total": len(entries)}


@router.post("", status_code=201, summary="Add a player to the pipeline (stage: Identified)")
def add(body: PipelineCreate, request: Request, user: Ctx = Depends(require("pipeline:move")),
        db: Session = Depends(get_db)):
    p = db.get(Player, body.player_id)
    if p is None:
        raise HTTPException(404, "Player not found")
    if db.scalar(select(PipelineEntry).where(PipelineEntry.player_id == p.id)):
        raise HTTPException(409, "Player is already in the pipeline")
    if body.assigned_scout_id:
        _require_member(db, user, body.assigned_scout_id)
    e = PipelineEntry(player_id=p.id, stage="identified", priority=body.priority,
                      target_position=body.target_position or p.primary_position,
                      assigned_scout_id=body.assigned_scout_id, created_by_id=user.id)
    db.add(e)
    db.flush()
    db.add(PipelineEvent(entry_id=e.id, from_stage=None, to_stage="identified",
                         note=body.note or "Added to recruitment pipeline", user_id=user.id))
    audit.log(db, user, "pipeline.add", "pipeline_entry", e.id, {"player_id": p.id}, request)
    db.commit()
    return entry_out(_entry(db, e.id), user, with_history=True)


@router.get("/events", summary="Recent decisions across the pipeline")
def recent_events(limit: int = 50, user: Ctx = Depends(require("pipeline:read")), db: Session = Depends(get_db)):
    evs = db.scalars(select(PipelineEvent).options(
        selectinload(PipelineEvent.user), selectinload(PipelineEvent.entry).selectinload(PipelineEntry.player))
        .order_by(PipelineEvent.created_at.desc(), PipelineEvent.id.desc()).limit(min(limit, 500))).all()
    return [{"id": ev.id, "entry_id": ev.entry_id, "player_id": ev.entry.player_id,
             "player_name": ev.entry.player.full_name, "from_stage": ev.from_stage, "to_stage": ev.to_stage,
             "note": ev.note, "user_name": ev.user.full_name if ev.user else None, "created_at": ev.created_at}
            for ev in evs]


@router.get("/player/{player_id}")
def by_player(player_id: int, user: Ctx = Depends(require("pipeline:read")), db: Session = Depends(get_db)):
    e = db.scalar(select(PipelineEntry).where(PipelineEntry.player_id == player_id))
    if e is None:
        return None
    return entry_out(_entry(db, e.id), user, with_history=True)


@router.get("/{entry_id}")
def get_entry(entry_id: int, user: Ctx = Depends(require("pipeline:read")), db: Session = Depends(get_db)):
    return entry_out(_entry(db, entry_id), user, with_history=True)


@router.post("/{entry_id}/move", summary="Move a player to another stage (rationale required)")
def move(entry_id: int, body: PipelineMove, request: Request, user: Ctx = Depends(require("pipeline:move")),
         db: Session = Depends(get_db)):
    e = _entry(db, entry_id)
    extra = check_transition(db, user, e, body.to_stage)
    note = body.note + (f" [{'; '.join(extra)}]" if extra else "")
    frm = e.stage
    e.stage = body.to_stage
    e.rejection_reason = body.note if body.to_stage == "rejected" else None
    e.events.append(PipelineEvent(from_stage=frm, to_stage=body.to_stage, note=note, user_id=user.id))
    audit.log(db, user, "pipeline.move", "pipeline_entry", e.id,
              {"player_id": e.player_id, "from": frm, "to": body.to_stage}, request)
    db.commit()
    return entry_out(_entry(db, e.id), user, with_history=True)


@router.patch("/{entry_id}")
def update(entry_id: int, body: PipelineUpdate, request: Request, user: Ctx = Depends(require("pipeline:move")),
           db: Session = Depends(get_db)):
    e = _entry(db, entry_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("assigned_scout_id"):
        _require_member(db, user, changes["assigned_scout_id"])
    for k, v in changes.items():
        setattr(e, k, v)
    audit.log(db, user, "pipeline.update", "pipeline_entry", e.id, changes, request)
    db.commit()
    return entry_out(_entry(db, e.id), user, with_history=True)
