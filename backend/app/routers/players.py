"""Player database: CRUD, advanced search, statistics, analytics and export."""
from __future__ import annotations

import csv
import io
import operator
import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..analytics import METRICS, aggregate, analyse_player, compute_all_metrics, select_rows
from ..database import get_db
from ..models import (
    STAT_FIELDS,
    Club,
    DataSource,
    League,
    PipelineEntry,
    Player,
    PlayerSeasonStats,
    User,
)
from ..schemas import PlayerCreate, PlayerUpdate, StatsIn
from ..security import Ctx, has_permission, require
from ..assessments import get_assessment, get_assessments, upsert_assessment
from ..models import ASSESSMENT_FIELDS, FINANCIAL_FIELDS, PlayerAssessment
from ..serializers import player_out, stats_out

router = APIRouter(prefix="/api/players", tags=["players"])

_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "=": operator.eq}
_STAT_FILTER_RE = re.compile(r"^\s*([a-z0-9_]+)\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*$")


def _load_options():
    return (
        selectinload(Player.club).selectinload(Club.league),
        selectinload(Player.data_source),
        selectinload(Player.stats).selectinload(PlayerSeasonStats.league),
    )


def _get_player(db: Session, player_id: int) -> Player:
    p = db.scalar(select(Player).where(Player.id == player_id).options(*_load_options()))
    if p is None:
        raise HTTPException(404, "Player not found")
    return p


def _years_ago(years: int) -> date:
    t = date.today()
    try:
        return t.replace(year=t.year - years)
    except ValueError:  # 29 Feb
        return t.replace(year=t.year - years, day=28)


def parse_stat_filters(raw: str | None) -> list[tuple[str, str, float]]:
    if not raw:
        return []
    filters = []
    for part in raw.split(","):
        if not part.strip():
            continue
        m = _STAT_FILTER_RE.match(part)
        if not m or m.group(1) not in METRICS:
            raise HTTPException(422, f"Invalid statistical filter '{part}'. Use e.g. prog_passes_p90>=4")
        filters.append((m.group(1), m.group(2), float(m.group(3))))
    return filters


@router.get("", summary="Advanced player search")
def search_players(
    q: str | None = Query(None, description="Name search"),
    position: str | None = Query(None, description="Comma-separated position codes (primary or secondary)"),
    primary_only: bool = False,
    tactical_role: str | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    nationality: str | None = None,
    league_id: int | None = None,
    league_country: str | None = None,
    club_id: int | None = None,
    height_min: int | None = None,
    height_max: int | None = None,
    foot: str | None = None,
    contract_expiry_before: date | None = None,
    fee_min: int | None = None,
    fee_max: int | None = None,
    salary_max: int | None = None,
    availability: str | None = Query(None, description="Comma-separated availability values"),
    pipeline_stage: str | None = Query(None, description="Comma-separated stages, or 'none' for not in pipeline"),
    include_fictional: bool = True,
    scope: str | None = Query(None, description="'shared' (platform reference) or 'private' (this organization's own records)"),
    min_minutes: int | None = Query(None, description="Minimum minutes in the latest season"),
    stat_filters: str | None = Query(None, description="Latest-season metric filters, e.g. 'prog_passes_p90>=4,pass_pct>=80'"),
    sort: str = Query("full_name", description="full_name | age | fee | contract_expiry | last_updated | height | metric:<key>"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    user: Ctx = Depends(require("players:read")),
    db: Session = Depends(get_db),
):
    can_fin = has_permission(user, "financials:read")
    if not can_fin and any(v is not None for v in (fee_min, fee_max, salary_max)) or (not can_fin and sort == "fee"):
        raise HTTPException(403, "Your role cannot filter or sort on financial information")

    org_id = user.organization_id
    # Explicit organization conditions in the ON clauses (in addition to the global tenant
    # filter) so that another club's pipeline/assessment can never influence results.
    stmt = select(Player).outerjoin(Club, Player.current_club_id == Club.id).outerjoin(
        League, Club.league_id == League.id
    ).outerjoin(PipelineEntry, and_(PipelineEntry.player_id == Player.id, PipelineEntry.organization_id == org_id)
    ).outerjoin(PlayerAssessment, and_(PlayerAssessment.player_id == Player.id,
                                       PlayerAssessment.organization_id == org_id))

    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Player.full_name).like(like), func.lower(Player.known_as).like(like)))
    if tactical_role:
        stmt = stmt.where(func.lower(PlayerAssessment.tactical_role).like(f"%{tactical_role.lower()}%"))
    if age_min is not None:
        stmt = stmt.where(Player.date_of_birth <= _years_ago(age_min))
    if age_max is not None:
        stmt = stmt.where(Player.date_of_birth > _years_ago(age_max + 1))
    if nationality:
        nats = [n.strip().lower() for n in nationality.split(",") if n.strip()]
        stmt = stmt.where(or_(func.lower(Player.nationality).in_(nats), func.lower(Player.second_nationality).in_(nats)))
    if league_id:
        stmt = stmt.where(Club.league_id == league_id)
    if league_country:
        stmt = stmt.where(func.lower(League.country) == league_country.lower())
    if club_id:
        stmt = stmt.where(Player.current_club_id == club_id)
    if height_min is not None:
        stmt = stmt.where(Player.height_cm >= height_min)
    if height_max is not None:
        stmt = stmt.where(Player.height_cm <= height_max)
    if foot:
        stmt = stmt.where(Player.preferred_foot == foot)
    if contract_expiry_before:
        stmt = stmt.where(Player.contract_expiry <= contract_expiry_before)
    if fee_min is not None:
        stmt = stmt.where(PlayerAssessment.estimated_fee >= fee_min)
    if fee_max is not None:
        stmt = stmt.where(PlayerAssessment.estimated_fee <= fee_max)
    if salary_max is not None:
        stmt = stmt.where(PlayerAssessment.salary_expectation <= salary_max)
    if availability:
        stmt = stmt.where(func.coalesce(PlayerAssessment.availability, "unknown").in_(
            [a.strip() for a in availability.split(",")]))
    if scope in ("shared", "private"):
        stmt = stmt.where(Player.organization_id.is_(None) if scope == "shared" else Player.organization_id == org_id)
    if pipeline_stage:
        stages = [s.strip() for s in pipeline_stage.split(",")]
        if "none" in stages:
            stmt = stmt.where(PipelineEntry.id.is_(None))
        else:
            stmt = stmt.where(PipelineEntry.stage.in_(stages))
    if not include_fictional:
        stmt = stmt.where(Player.is_fictional.is_(False))

    players = db.scalars(stmt.options(*_load_options())).unique().all()
    stage_by_player = dict(db.execute(select(PipelineEntry.player_id, PipelineEntry.stage)).all())
    assess = get_assessments(db)

    # Position filter in Python: secondary_positions is a JSON list (portable across DBs).
    if position:
        wanted = {p.strip().upper() for p in position.split(",")}
        players = [
            p for p in players
            if p.primary_position in wanted or (not primary_only and wanted & set(p.secondary_positions or []))
        ]

    filters = parse_stat_filters(stat_filters)
    metric_sort = sort.startswith("metric:")
    metrics_cache: dict[int, dict] = {}
    if filters or metric_sort or min_minutes:
        kept = []
        for p in players:
            rows = select_rows(p, None)
            totals = aggregate(rows) if rows else None
            m = compute_all_metrics(totals) if totals else {}
            metrics_cache[p.id] = m
            if min_minutes and (not totals or (totals.get("minutes") or 0) < min_minutes):
                continue
            ok = all(m.get(k) is not None and _OPS[op](m[k], val) for k, op, val in filters)
            if ok:
                kept.append(p)
        players = kept

    reverse = order == "desc"
    if metric_sort:
        key = sort.split(":", 1)[1]
        if key not in METRICS:
            raise HTTPException(422, "Unknown metric for sorting")
        with_val = [p for p in players if metrics_cache.get(p.id, {}).get(key) is not None]
        without = [p for p in players if metrics_cache.get(p.id, {}).get(key) is None]
        players = sorted(with_val, key=lambda p: metrics_cache[p.id][key], reverse=reverse) + without
    else:
        sort_keys = {
            "full_name": lambda p: p.full_name.lower(),
            "age": lambda p: (p.date_of_birth is None, -(p.date_of_birth.toordinal()) if p.date_of_birth else 0),
            "fee": lambda p: (_fee(assess, p.id) is None, _fee(assess, p.id) or 0),
            "contract_expiry": lambda p: (p.contract_expiry is None, p.contract_expiry or date.max),
            "last_updated": lambda p: p.last_updated,
            "height": lambda p: (p.height_cm is None, p.height_cm or 0),
        }
        if sort not in sort_keys:
            raise HTTPException(422, "Unknown sort key")
        players = sorted(players, key=sort_keys[sort], reverse=reverse)

    total = len(players)
    start = (page - 1) * page_size
    page_items = players[start:start + page_size]
    items = []
    for p in page_items:
        item = player_out(p, user, assess.get(p.id), stage_by_player.get(p.id))
        if p.id in metrics_cache and (filters or metric_sort):
            keys = [k for k, _, _ in filters] + ([sort.split(":", 1)[1]] if metric_sort else [])
            item["matched_metrics"] = {k: metrics_cache[p.id].get(k) for k in dict.fromkeys(keys)}
        items.append(item)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/export.csv", summary="Export the (filtered) player database as CSV")
def export_csv(request: Request, include_fictional: bool = True, user: Ctx = Depends(require("players:read")),
               db: Session = Depends(get_db)):
    stmt = select(Player).options(*_load_options()).order_by(Player.full_name)
    if not include_fictional:
        stmt = stmt.where(Player.is_fictional.is_(False))
    players = db.scalars(stmt).all()
    assess = get_assessments(db)
    cols = ["id", "scope", "full_name", "date_of_birth", "age", "nationality", "second_nationality", "club_name",
            "league_name", "primary_position", "secondary_positions", "tactical_role", "height_cm", "weight_kg",
            "preferred_foot", "contract_expiry", "availability", "estimated_fee", "salary_expectation", "currency",
            "latest_season", "latest_minutes", "data_source", "is_fictional", "last_updated"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for p in players:
        d = player_out(p, user, assess.get(p.id))
        d["secondary_positions"] = "|".join(d["secondary_positions"])
        w.writerow([d.get(c) if d.get(c) is not None else "" for c in cols])
    audit.log(db, user, "player.export_csv", "player", None, {"count": len(players)}, request)
    db.commit()
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=players.csv"})


@router.post("", status_code=201)
def create_player(body: PlayerCreate, request: Request, user: Ctx = Depends(require("players:write")),
                  db: Session = Depends(get_db)):
    data = body.model_dump()
    if not has_permission(user, "financials:read"):
        for f in FINANCIAL_FIELDS:
            data.pop(f, None)
    private = {k: data.pop(k) for k in list(data) if k in ASSESSMENT_FIELDS}
    if data.get("data_source_id"):
        src = db.get(DataSource, data["data_source_id"])
        if src is None:
            raise HTTPException(422, "Unknown data source")
        data["is_fictional"] = src.is_fictional
    if data.get("current_club_id") and db.get(Club, data["current_club_id"]) is None:
        raise HTTPException(422, "Unknown club")
    player = Player(**data, created_by_id=user.id)  # private to this organization (tenant guard)
    db.add(player)
    db.flush()
    upsert_assessment(db, player.id, private, user.id)
    audit.log(db, user, "player.create", "player", player.id, {"full_name": player.full_name}, request)
    db.commit()
    return player_out(_get_player(db, player.id), user, get_assessment(db, player.id), detail=True)


@router.get("/{player_id}")
def get_player(player_id: int, user: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    p = _get_player(db, player_id)
    stage = db.scalar(select(PipelineEntry.stage).where(PipelineEntry.player_id == p.id))
    out = player_out(p, user, get_assessment(db, p.id), stage, detail=True)
    out["stats"] = [stats_out(s) for s in p.stats]
    return out


@router.patch("/{player_id}")
def update_player(player_id: int, body: PlayerUpdate, request: Request, user: Ctx = Depends(require("players:write")),
                  db: Session = Depends(get_db)):
    p = _get_player(db, player_id)
    changes = body.model_dump(exclude_unset=True)
    if not has_permission(user, "financials:read") and any(f in changes for f in FINANCIAL_FIELDS):
        raise HTTPException(403, "Your role cannot edit financial information")
    private = {k: changes.pop(k) for k in list(changes) if k in ASSESSMENT_FIELDS}
    if changes and p.organization_id is None:
        raise HTTPException(403, "This is a shared reference player: identity fields are maintained by the "
                                 "platform. You can edit your organization's private assessment fields.")
    before = {k: (str(getattr(p, k)) if getattr(p, k) is not None else None) for k in changes}
    for k, v in changes.items():
        setattr(p, k, v)
    if private:
        upsert_assessment(db, p.id, private, user.id)
        changes.update(private)
    audit.log(db, user, "player.update", "player", p.id,
              {"before": before, "after": {k: (str(v) if v is not None else None) for k, v in changes.items()}}, request)
    db.commit()
    return player_out(_get_player(db, p.id), user, get_assessment(db, p.id), detail=True)


@router.delete("/{player_id}", status_code=204)
def delete_player(player_id: int, request: Request, user: Ctx = Depends(require("players:delete")),
                  db: Session = Depends(get_db)):
    p = _get_player(db, player_id)
    if p.organization_id != user.organization_id:
        raise HTTPException(403, "Shared reference players cannot be deleted by an organization")
    audit.log(db, user, "player.delete", "player", p.id, {"full_name": p.full_name}, request)
    db.delete(p)
    db.commit()


# --------------------------------------------------------------------------- statistics
@router.get("/{player_id}/stats")
def list_stats(player_id: int, _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    return [stats_out(s) for s in _get_player(db, player_id).stats]


def upsert_stats(db: Session, player: Player, body: StatsIn, org_id: int) -> tuple[PlayerSeasonStats, bool]:
    src = db.get(DataSource, body.data_source_id)
    if src is None:
        raise HTTPException(422, "Unknown data source — every statistic must reference its source")
    if src.organization_id != org_id:
        raise HTTPException(422, "Statistics must be recorded under one of your organization's own data sources")
    if body.league_id and db.get(League, body.league_id) is None:
        raise HTTPException(422, "Unknown league")
    existing = db.scalar(select(PlayerSeasonStats).where(
        PlayerSeasonStats.player_id == player.id, PlayerSeasonStats.season == body.season,
        PlayerSeasonStats.league_id == body.league_id, PlayerSeasonStats.data_source_id == body.data_source_id,
        PlayerSeasonStats.organization_id == org_id))
    created = existing is None
    row = existing or PlayerSeasonStats(player_id=player.id)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    row.is_fictional = src.is_fictional
    if created:
        db.add(row)
    db.flush()
    return row, created


@router.post("/{player_id}/stats", status_code=201, summary="Add or replace a season stat line (idempotent per player/season/league/source)")
def add_stats(player_id: int, body: StatsIn, request: Request, user: Ctx = Depends(require("stats:write")),
              db: Session = Depends(get_db)):
    p = _get_player(db, player_id)
    row, created = upsert_stats(db, p, body, user.organization_id)
    if p.organization_id == user.organization_id:  # never touch shared reference rows
        p.last_updated = row.last_updated
    audit.log(db, user, "stats.create" if created else "stats.update", "player_season_stats", row.id,
              {"player_id": p.id, "season": body.season, "data_source_id": body.data_source_id}, request)
    db.commit()
    db.refresh(row)
    return stats_out(row)


@router.delete("/{player_id}/stats/{stats_id}", status_code=204)
def delete_stats(player_id: int, stats_id: int, request: Request, user: Ctx = Depends(require("stats:write")),
                 db: Session = Depends(get_db)):
    row = db.get(PlayerSeasonStats, stats_id)
    if row is None or row.player_id != player_id:
        raise HTTPException(404, "Stat line not found")
    if row.organization_id != user.organization_id:
        raise HTTPException(403, "Shared reference statistics cannot be deleted by an organization")
    audit.log(db, user, "stats.delete", "player_season_stats", row.id, {"player_id": player_id, "season": row.season}, request)
    db.delete(row)
    db.commit()


@router.get("/{player_id}/analytics", summary="Per-90, percentile, consistency and role-fit analysis")
def player_analytics(player_id: int, season: str | None = Query(None, description="Season, 'all', or omit for latest"),
                     _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    return analyse_player(db, _get_player(db, player_id), season)


__all__ = ["router", "upsert_stats", "STAT_FIELDS"]


def _fee(assess: dict, player_id: int):
    a = assess.get(player_id)
    return a.estimated_fee if a else None
