"""Convert ORM objects into API dicts, applying role-based field redaction."""
from __future__ import annotations

from .analytics import age_on
from .models import MatchReport, Player, PlayerSeasonStats, STAT_FIELDS, ScoutingReport, User
from .security import has_permission, permissions_for

FINANCIAL_FIELDS = ("estimated_fee_eur", "fee_estimate_source", "salary_expectation_eur", "agent_name")


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "region": user.region,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "permissions": sorted(permissions_for(user.role)),
    }


def player_out(p: Player, viewer: User, pipeline_stage: str | None = None, detail: bool = False) -> dict:
    club = p.club
    league = club.league if club else None
    latest = p.stats[0] if p.stats else None
    out = {
        "id": p.id,
        "full_name": p.full_name,
        "known_as": p.known_as,
        "date_of_birth": p.date_of_birth,
        "age": age_on(p.date_of_birth),
        "nationality": p.nationality,
        "second_nationality": p.second_nationality,
        "current_club_id": p.current_club_id,
        "club_name": club.name if club else None,
        "league_id": league.id if league else None,
        "league_name": league.name if league else None,
        "league_country": league.country if league else None,
        "primary_position": p.primary_position,
        "secondary_positions": p.secondary_positions or [],
        "tactical_role": p.tactical_role,
        "height_cm": p.height_cm,
        "weight_kg": p.weight_kg,
        "preferred_foot": p.preferred_foot,
        "physical_profile": p.physical_profile,
        "contract_expiry": p.contract_expiry,
        "availability": p.availability,
        "estimated_fee_eur": p.estimated_fee_eur,
        "fee_estimate_source": p.fee_estimate_source,
        "salary_expectation_eur": p.salary_expectation_eur,
        "agent_name": p.agent_name,
        "notes": p.notes if detail else None,
        "data_source": p.data_source.name if p.data_source else None,
        "data_source_id": p.data_source_id,
        "source_reference": p.source_reference,
        "is_fictional": p.is_fictional,
        "last_updated": p.last_updated,
        "created_at": p.created_at,
        "latest_season": latest.season if latest else None,
        "latest_minutes": latest.minutes if latest else None,
        "pipeline_stage": pipeline_stage,
    }
    if not has_permission(viewer, "financials:read"):
        for f in FINANCIAL_FIELDS:
            out[f] = None
        out["financials_redacted"] = True
    else:
        out["financials_redacted"] = False
    return out


def stats_out(s: PlayerSeasonStats) -> dict:
    out = {
        "id": s.id,
        "player_id": s.player_id,
        "season": s.season,
        "league_id": s.league_id,
        "league_name": s.league.name if s.league else None,
        "club_name": s.club_name,
        "data_source_id": s.data_source_id,
        "data_source": s.data_source.name if s.data_source else None,
        "is_fictional": s.is_fictional,
        "last_updated": s.last_updated,
    }
    for f in STAT_FIELDS:
        out[f] = getattr(s, f)
    return out


def match_report_out(r: MatchReport) -> dict:
    data = {c.name: getattr(r, c.name) for c in MatchReport.__table__.columns}
    data["scout_name"] = r.scout.full_name if r.scout else None
    data["is_complete_match_analysis"] = r.observation_type in ("video_full_match", "live")
    if r.observation_type == "video_highlights":
        data["evidence_warning"] = "Based on highlights only — not equivalent to complete match analysis."
    return data


def report_out(r: ScoutingReport) -> dict:
    data = {c.name: getattr(r, c.name) for c in ScoutingReport.__table__.columns}
    data["author_name"] = r.author.full_name if r.author else None
    data["player_name"] = r.player.full_name if r.player else None
    return data
