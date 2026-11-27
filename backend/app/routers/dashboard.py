"""Executive dashboard and recruitment budget."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..database import get_db
from ..models import (
    PIPELINE_STAGES,
    Club,
    MatchReport,
    MatchVideo,
    PipelineEntry,
    PipelineEvent,
    Player,
    RecruitmentBudget,
    ScoutingReport,
    User,
    VideoObservation,
)
from ..schemas import BudgetIn
from ..security import Ctx, has_permission, require
from ..assessments import get_assessments
from .pipeline import entry_out

router = APIRouter(prefix="/api", tags=["dashboard"])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/dashboard", summary="Executive dashboard summary")
def dashboard(user: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    players = db.scalars(select(Player).options(selectinload(Player.club).selectinload(Club.league))).all()
    entries = db.scalars(select(PipelineEntry).options(
        selectinload(PipelineEntry.player).selectinload(Player.club).selectinload(Club.league),
        selectinload(PipelineEntry.assigned_scout))).all()

    by_stage = Counter(e.stage for e in entries)
    active = [e for e in entries if e.stage not in ("signed", "rejected")]
    prio_rank = {"high": 0, "medium": 1, "low": 2}

    # --- activity
    since90 = now - timedelta(days=90)
    since30 = now - timedelta(days=30)
    mrs = db.scalars(select(MatchReport).options(selectinload(MatchReport.scout))).all()
    obs = db.scalars(select(VideoObservation).options(selectinload(VideoObservation.scout))).all()
    vids = db.scalars(select(MatchVideo)).all()
    reps = db.scalars(select(ScoutingReport)).all()
    events = db.scalars(select(PipelineEvent)).all()

    per_scout: dict[str, dict] = defaultdict(lambda: {"match_reports": 0, "live_reports": 0, "video_observations": 0,
                                                      "reports_30d": 0, "players_covered": set()})
    for r in mrs:
        name = r.scout.full_name if r.scout else "Unknown"
        s = per_scout[name]
        s["match_reports"] += 1
        s["live_reports"] += r.observation_type == "live"
        s["players_covered"].add(r.player_id)
        if _aware(r.created_at) >= since30:
            s["reports_30d"] += 1
    for o in obs:
        per_scout[o.scout.full_name if o.scout else "Unknown"]["video_observations"] += 1
    scouts = sorted(({"scout": k, **{kk: (len(vv) if isinstance(vv, set) else vv) for kk, vv in v.items()}}
                     for k, v in per_scout.items()), key=lambda x: -(x["match_reports"] + x["video_observations"]))

    weeks = []
    for i in range(11, -1, -1):
        start = now - timedelta(weeks=i + 1)
        end = now - timedelta(weeks=i)
        weeks.append({
            "week_start": start.date().isoformat(),
            "match_reports": sum(1 for r in mrs if start <= _aware(r.created_at) < end),
            "video_observations": sum(1 for o in obs if start <= _aware(o.created_at) < end),
            "pipeline_moves": sum(1 for e in events if start <= _aware(e.created_at) < end),
        })

    stale_cutoff = now - timedelta(days=180)
    out = {
        "players": {
            "total": len(players),
            "own": sum(p.organization_id is not None for p in players),
            "shared": sum(p.organization_id is None for p in players),
            "fictional": sum(p.is_fictional for p in players),
            "real": sum(not p.is_fictional for p in players),
            "stale_records": sum(1 for p in players if _aware(p.last_updated) < stale_cutoff),
            "by_position": dict(Counter(p.primary_position for p in players)),
            "by_nationality": dict(Counter(p.nationality for p in players).most_common(20)),
            "by_league_country": dict(Counter((p.club.league.country if p.club and p.club.league else "Unknown")
                                              for p in players).most_common(20)),
        },
        "pipeline": {
            "by_stage": {s: by_stage.get(s, 0) for s in PIPELINE_STAGES},
            "active": len(active),
            "priority_targets": [entry_out(e, user) for e in sorted(
                [e for e in active if e.priority == "high"], key=lambda e: ORDER_IDX.get(e.stage, 0), reverse=True)][:12],
            "under_observation": [entry_out(e, user) for e in sorted(
                [e for e in entries if e.stage == "under_observation"], key=lambda e: prio_rank[e.priority])][:12],
            "shortlisted": [entry_out(e, user) for e in sorted(
                [e for e in entries if e.stage == "shortlisted"], key=lambda e: prio_rank[e.priority])][:12],
        },
        "activity": {
            "match_reports_total": len(mrs),
            "match_reports_90d": sum(1 for r in mrs if _aware(r.created_at) >= since90),
            "live_reports_total": sum(1 for r in mrs if r.observation_type == "live"),
            "highlights_only_reports": sum(1 for r in mrs if r.observation_type == "video_highlights"),
            "videos_linked": len(vids),
            "full_match_videos": sum(v.is_full_match for v in vids),
            "video_observations": len(obs),
            "scouting_reports": len(reps),
            "final_reports": sum(r.status == "final" for r in reps),
            "pipeline_decisions_30d": sum(1 for e in events if _aware(e.created_at) >= since30),
            "per_scout": scouts,
            "weekly": weeks,
        },
        "budget": None,
    }
    if has_permission(user, "financials:read"):
        budget = db.scalar(select(RecruitmentBudget).order_by(RecruitmentBudget.season.desc()))
        assess = get_assessments(db)
        fee = lambda e: (assess[e.player_id].estimated_fee or 0) if e.player_id in assess else 0  # noqa: E731
        signed = sum(fee(e) for e in entries if e.stage == "signed")
        pending = sum(fee(e) for e in entries if e.stage in ("approved", "negotiation"))
        shortlisted_val = sum(fee(e) for e in entries if e.stage in ("shortlisted", "live_scouting"))
        out["budget"] = {
            "season": budget.season if budget else None,
            "currency": user.organization.currency,
            "transfer_budget": budget.transfer_budget if budget else None,
            "wage_budget": budget.wage_budget if budget else None,
            "committed": signed,
            "pending": pending,
            "shortlist_value": shortlisted_val,
            "remaining": (budget.transfer_budget - signed - pending) if budget else None,
            "note": "Committed/pending use estimated fees on player records — estimates, not agreed prices.",
        }
    return out


ORDER_IDX = {s: i for i, s in enumerate(PIPELINE_STAGES)}


@router.get("/budgets")
def list_budgets(ctx: Ctx = Depends(require("financials:read")), db: Session = Depends(get_db)):
    return [{"id": b.id, "season": b.season, "transfer_budget": b.transfer_budget, "currency": ctx.organization.currency,
             "wage_budget": b.wage_budget, "notes": b.notes, "updated_at": b.updated_at}
            for b in db.scalars(select(RecruitmentBudget).order_by(RecruitmentBudget.season.desc())).all()]


@router.put("/budgets", summary="Create or update the budget for a season")
def upsert_budget(body: BudgetIn, request: Request, user: Ctx = Depends(require("budget:manage")),
                  db: Session = Depends(get_db)):
    b = db.scalar(select(RecruitmentBudget).where(RecruitmentBudget.season == body.season))
    if b is None:
        b = RecruitmentBudget(**body.model_dump())
        db.add(b)
    else:
        for k, v in body.model_dump().items():
            setattr(b, k, v)
    db.flush()
    audit.log(db, user, "budget.upsert", "recruitment_budget", b.id, body.model_dump(), request)
    db.commit()
    return {"id": b.id, **body.model_dump()}

