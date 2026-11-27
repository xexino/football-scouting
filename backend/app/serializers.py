"""Convert ORM objects into API dicts, applying role-based field redaction."""
from __future__ import annotations

from .analytics import age_on
from .models import (
    ASSESSMENT_FIELDS,
    FINANCIAL_FIELDS,
    MatchReport,
    Membership,
    Organization,
    Player,
    PlayerAssessment,
    PlayerSeasonStats,
    STAT_FIELDS,
    ScoutingReport,
    User,
)
from .security import has_permission, permissions_for


def organization_out(o: Organization) -> dict:
    return {"id": o.id, "slug": o.slug, "name": o.name, "short_name": o.short_name, "country": o.country,
            "primary_language": o.primary_language, "currency": o.currency, "timezone": o.timezone,
            "logo_data_url": o.logo_data_url, "settings": o.settings or {}, "is_demo": o.is_demo,
            "status": o.status}


def member_out(m: Membership) -> dict:
    u = m.user
    return {
        "id": u.id, "membership_id": m.id, "email": u.email, "full_name": u.full_name, "role": m.role,
        "region": m.region, "is_active": m.is_active and u.is_active, "created_at": m.created_at,
        "last_login_at": u.last_login_at, "permissions": sorted(permissions_for(m.role)),
    }


def me_out(user: User, ctx=None) -> dict:
    out = {
        "id": user.id, "email": user.email, "full_name": user.full_name, "is_platform_admin": user.is_platform_admin,
        "created_at": user.created_at, "last_login_at": user.last_login_at,
        "organizations": [
            {"id": m.organization.id, "name": m.organization.name, "role": m.role, "is_demo": m.organization.is_demo}
            for m in user.memberships if m.is_active and m.organization.status != "pending_deletion"
        ],
        "organization": None, "role": None, "region": None, "permissions": [],
    }
    if ctx is not None:
        out.update(organization=organization_out(ctx.organization), role=ctx.role, region=ctx.membership.region,
                   permissions=sorted(ctx.permissions))
    return out


def player_out(p: Player, viewer, assessment: PlayerAssessment | None = None, pipeline_stage: str | None = None,
               detail: bool = False) -> dict:
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
        "height_cm": p.height_cm,
        "weight_kg": p.weight_kg,
        "preferred_foot": p.preferred_foot,
        "contract_expiry": p.contract_expiry,
        # ownership: shared platform reference vs. this organization's private record
        "scope": "shared" if p.organization_id is None else "private",
        "editable_identity": p.organization_id is not None,
        "currency": viewer.organization.currency,
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
    for f in ASSESSMENT_FIELDS:  # this organization's private view (never another club's)
        out[f] = getattr(assessment, f) if assessment is not None else None
    if out["availability"] is None:
        out["availability"] = "unknown"
    if not detail:
        out["notes"] = None
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
