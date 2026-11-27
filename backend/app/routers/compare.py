"""Side-by-side comparison of 2–5 players in the same position group."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..analytics import POSITION_PROFILES, TACTICAL_ROLES, age_on, analyse_player, role_fit, strengths_weaknesses
from ..assessments import get_assessments
from ..database import get_db
from ..models import Club, MatchReport, PipelineEntry, Player, PlayerSeasonStats, ScoutingReport, User
from ..security import Ctx, has_permission, require

router = APIRouter(prefix="/api/compare", tags=["comparison"])


class CompareIn(BaseModel):
    player_ids: list[int] = Field(min_length=2, max_length=5)
    season: str | None = None
    tactical_role: str | None = None
    allow_mixed_positions: bool = False


def _months_until(d: date | None) -> int | None:
    if d is None:
        return None
    t = date.today()
    return (d.year - t.year) * 12 + (d.month - t.month)


@router.post("", summary="Compare 2–5 players")
def compare(body: CompareIn, user: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    if len(set(body.player_ids)) != len(body.player_ids):
        raise HTTPException(422, "Duplicate players in comparison")
    players = db.scalars(select(Player).where(Player.id.in_(body.player_ids)).options(
        selectinload(Player.club).selectinload(Club.league),
        selectinload(Player.stats).selectinload(PlayerSeasonStats.league),
        selectinload(Player.stats).selectinload(PlayerSeasonStats.data_source),
    )).all()
    if len(players) != len(body.player_ids):
        raise HTTPException(404, "One or more players not found")
    players.sort(key=lambda p: body.player_ids.index(p.id))

    positions = {p.primary_position for p in players}
    if len(positions) > 1 and not body.allow_mixed_positions:
        raise HTTPException(422, "Players must share the same primary position. "
                                 "Set allow_mixed_positions=true to compare anyway (metrics use the first player's profile).")
    position = players[0].primary_position
    profile = POSITION_PROFILES[position]

    if body.tactical_role and body.tactical_role not in TACTICAL_ROLES:
        raise HTTPException(422, "Unknown tactical role")
    role_key = body.tactical_role or next((k for k, r in TACTICAL_ROLES.items() if r["position"] == position), None)

    can_fin = has_permission(user, "financials:read")
    assess = get_assessments(db, [p.id for p in players])
    results = []
    for p in players:
        a_ = assess.get(p.id)
        a = analyse_player(db, p, body.season)
        pm = {m["key"]: m for m in a.get("profile_metrics", [])}
        pcts = {k: {"percentile": m.get("percentile")} for k, m in pm.items()}
        # For mixed comparisons use the reference profile's metrics from all_metrics.
        metrics = []
        for k in profile:
            m = pm.get(k)
            metrics.append({
                "key": k,
                "value": m["value"] if m else (a.get("all_metrics") or {}).get(k),
                "league_adjusted": m.get("league_adjusted") if m else None,
                "percentile": m.get("percentile") if m else None,
            })
        strengths, weaknesses = strengths_weaknesses(a.get("profile_metrics", []))
        mrs = db.scalars(select(MatchReport).where(MatchReport.player_id == p.id)).all()
        ratings = [r.overall_rating for r in mrs if r.overall_rating is not None]
        latest_report = db.scalar(select(ScoutingReport).where(ScoutingReport.player_id == p.id)
                                  .order_by(ScoutingReport.created_at.desc()))
        stage = db.scalar(select(PipelineEntry.stage).where(PipelineEntry.player_id == p.id))
        results.append({
            "player": {
                "id": p.id, "full_name": p.full_name, "age": age_on(p.date_of_birth), "nationality": p.nationality,
                "club": p.club.name if p.club else None,
                "league": p.club.league.name if p.club and p.club.league else None,
                "position": p.primary_position, "height_cm": p.height_cm, "preferred_foot": p.preferred_foot,
                "is_fictional": p.is_fictional, "pipeline_stage": stage,
            },
            "season": a.get("season"),
            "minutes": a.get("minutes"),
            "sample_reliable": a.get("sample_reliable", False),
            "metrics": metrics,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "strengths_weaknesses_basis": "data-derived: ≥70th / ≤30th percentile vs. database position pool",
            "tactical_suitability": role_fit(pcts, role_key) if role_key else None,
            "financial": {
                "estimated_fee": (a_.estimated_fee if a_ else None) if can_fin else None,
                "salary_expectation": (a_.salary_expectation if a_ else None) if can_fin else None,
                "currency": user.organization.currency,
                "contract_expiry": p.contract_expiry,
                "months_remaining": _months_until(p.contract_expiry),
                "availability": a_.availability if a_ else "unknown",
                "redacted": not can_fin,
            },
            "scouting": {
                "evidence_type": "scout_opinion",
                "match_reports": len(mrs),
                "full_match_or_live_reports": sum(1 for r in mrs if r.observation_type != "video_highlights"),
                "highlights_only_reports": sum(1 for r in mrs if r.observation_type == "video_highlights"),
                "avg_overall_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
                "latest_recommendation": latest_report.recommendation if latest_report else None,
                "latest_report_id": latest_report.id if latest_report else None,
            },
            "provenance": a.get("provenance"),
            "caveats": a.get("caveats", []),
        })
    return {
        "position": position,
        "profile": profile,
        "tactical_role": role_key,
        "tactical_role_label": TACTICAL_ROLES[role_key]["label"] if role_key else None,
        "players": results,
        "notes": [
            "Radar values are database percentiles within the position pool (0–100); they are relative, not absolute quality.",
            "Compare players only with sufficient minutes; small samples are flagged.",
            "Scouting figures are opinions of named scouts; highlights-only reports are counted separately.",
        ],
    }

