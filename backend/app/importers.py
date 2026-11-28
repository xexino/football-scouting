"""CSV / JSON import logic shared by the import API and provider adapters.

Rules:
* Every import must reference a registered DataSource (provenance is mandatory).
* Empty cells become NULL — never zero.
* Rows are validated individually; a row error never corrupts other rows.
* ``dry_run`` validates everything and rolls back.

Tenancy: the importer works in the session's tenant context. Inside an organization it
creates *private* rows and only updates that organization's own records — a matched shared
reference player gets the organization's private assessment updated, never its identity.
In the SYSTEM context (platform operators) it maintains shared reference data.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .assessments import upsert_assessment
from .models import (
    ASSESSMENT_FIELDS,
    FINANCIAL_FIELDS,
    FLOAT_STAT_FIELDS,
    STAT_FIELDS,
    Club,
    DataSource,
    League,
    Player,
    PlayerSeasonStats,
    utcnow,
)
from .schemas import PlayerCreate, StatsIn
from .tenancy import get_tenant


def owner_id(db: Session) -> int | None:
    """Organization id of the current tenant, or None (shared) in SYSTEM context."""
    t = get_tenant(db)
    return t if isinstance(t, int) else None

PLAYER_COLUMNS = [
    "full_name", "known_as", "date_of_birth", "nationality", "second_nationality", "club", "club_country",
    "league", "league_country", "primary_position", "secondary_positions", "tactical_role", "height_cm",
    "weight_kg", "preferred_foot", "physical_profile", "contract_expiry", "estimated_fee",
    "fee_estimate_source", "salary_expectation", "availability", "agent_name", "source_reference",
]
STATS_COLUMNS = ["player_id", "full_name", "date_of_birth", "season", "league", "league_country", "club_name",
                 *STAT_FIELDS]

PLAYER_EXAMPLE = {
    "full_name": "Example Player", "date_of_birth": "2001-05-14", "nationality": "Senegal",
    "club": "Example FC", "club_country": "Senegal", "league": "Example League", "league_country": "Senegal",
    "primary_position": "CM", "secondary_positions": "DM|AM", "height_cm": "181", "preferred_foot": "right",
    "contract_expiry": "2027-06-30", "availability": "unknown", "source_reference": "provider-id-123",
}


def template_csv(kind: str) -> str:
    cols = PLAYER_COLUMNS if kind == "players" else STATS_COLUMNS
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    if kind == "players":
        w.writerow([PLAYER_EXAMPLE.get(c, "") for c in cols])
    return buf.getvalue()


def _clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def get_or_create_league(db: Session, name: str | None, country: str | None, fictional: bool) -> League | None:
    if not name:
        return None
    country = country or "Unknown"
    lg = db.scalar(select(League).where(func.lower(League.name) == name.lower(), func.lower(League.country) == country.lower()))
    if lg is None:
        lg = League(name=name, country=country, is_fictional=fictional)
        db.add(lg)
        db.flush()
    return lg


def get_or_create_club(db: Session, name: str | None, country: str | None, league: League | None, fictional: bool) -> Club | None:
    if not name:
        return None
    country = country or (league.country if league else "Unknown")
    club = db.scalar(select(Club).where(func.lower(Club.name) == name.lower(), func.lower(Club.country) == country.lower()))
    if club is None:
        club = Club(name=name, country=country, league_id=league.id if league else None, is_fictional=fictional)
        db.add(club)
        db.flush()
    elif league and club.league_id != league.id and club.organization_id == owner_id(db):
        club.league_id = league.id  # club changed division (only for records we own)
    return club


def find_player(db: Session, full_name: str | None, dob: str | date | None, player_id=None) -> Player | None:
    if player_id:
        return db.get(Player, int(player_id))
    if not full_name:
        return None
    q = select(Player).where(func.lower(Player.full_name) == full_name.lower())
    if dob:
        q = q.where(Player.date_of_birth == (date.fromisoformat(dob) if isinstance(dob, str) else dob))
    matches = db.scalars(q).all()
    own = [m for m in matches if m.organization_id == owner_id(db)]
    if len(matches) > 1 and len(own) == 1:
        return own[0]  # prefer the organization's own record over a shared homonym
    if len(matches) > 1:
        raise ValueError(f"Ambiguous player '{full_name}' — provide date_of_birth or player_id")
    return matches[0] if matches else None


def import_player(db: Session, raw: dict, source: DataSource, user_id: int | None, allow_financials: bool) -> tuple[Player, bool]:
    row = {k: _clean(v) for k, v in raw.items()}
    league = get_or_create_league(db, row.get("league"), row.get("league_country"), source.is_fictional)
    club = get_or_create_club(db, row.get("club"), row.get("club_country"), league, source.is_fictional)
    sec = row.get("secondary_positions")
    if isinstance(sec, str):
        sec = [s.strip().upper() for s in sec.replace(",", "|").split("|") if s.strip()]
    payload = {
        k: row.get(k) for k in PLAYER_COLUMNS
        if k not in ("club", "club_country", "league", "league_country", "secondary_positions")
    }
    payload["secondary_positions"] = sec or []
    payload["current_club_id"] = club.id if club else None
    payload["data_source_id"] = source.id
    if payload.get("primary_position"):
        payload["primary_position"] = str(payload["primary_position"]).upper()
    if payload.get("preferred_foot"):
        payload["preferred_foot"] = str(payload["preferred_foot"]).lower()
    validated = PlayerCreate.model_validate({k: v for k, v in payload.items() if v is not None or k == "secondary_positions"})
    data = validated.model_dump(exclude_unset=True)
    if not allow_financials:
        for f in FINANCIAL_FIELDS:
            data.pop(f, None)
    private = {k: data.pop(k) for k in list(data) if k in ASSESSMENT_FIELDS}
    owner = owner_id(db)
    existing = find_player(db, data["full_name"], data.get("date_of_birth"))
    if existing:
        if existing.organization_id == owner:  # our own record (or shared, in SYSTEM context)
            for k, v in data.items():
                if v is not None and v != []:
                    setattr(existing, k, v)
            existing.is_fictional = source.is_fictional
            existing.last_updated = utcnow()
        if owner is not None:
            upsert_assessment(db, existing.id, private, user_id)
        db.flush()
        return existing, False
    if owner is not None:
        from .models import Organization
        from .subscriptions import enforce_player_limit
        enforce_player_limit(db, db.get(Organization, owner))  # row error once the plan limit is reached
    p = Player(**data, is_fictional=source.is_fictional, created_by_id=user_id)
    db.add(p)
    db.flush()
    if owner is not None:
        upsert_assessment(db, p.id, private, user_id)
        db.flush()
    return p, True


def import_stats(db: Session, raw: dict, source: DataSource) -> tuple[PlayerSeasonStats, bool]:
    row = {k: _clean(v) for k, v in raw.items()}
    player = find_player(db, row.get("full_name"), row.get("date_of_birth"), row.get("player_id"))
    if player is None:
        raise ValueError("Player not found — import the player profile first")
    league = get_or_create_league(db, row.get("league"), row.get("league_country"), source.is_fictional)
    payload: dict = {"season": row.get("season"), "league_id": league.id if league else None,
                     "club_name": row.get("club_name"), "data_source_id": source.id}
    for f in STAT_FIELDS:
        v = row.get(f)
        if v is None:
            payload[f] = None
        else:
            payload[f] = float(v) if f in FLOAT_STAT_FIELDS else int(float(v))
    body = StatsIn.model_validate(payload)
    owner = owner_id(db)
    own = PlayerSeasonStats.organization_id.is_(None) if owner is None else PlayerSeasonStats.organization_id == owner
    existing = db.scalar(select(PlayerSeasonStats).where(
        PlayerSeasonStats.player_id == player.id, PlayerSeasonStats.season == body.season,
        PlayerSeasonStats.league_id == body.league_id, PlayerSeasonStats.data_source_id == source.id, own))
    rowobj = existing or PlayerSeasonStats(player_id=player.id)
    for k, v in body.model_dump().items():
        setattr(rowobj, k, v)
    rowobj.is_fictional = source.is_fictional
    rowobj.last_updated = utcnow()
    if existing is None:
        db.add(rowobj)
    if player.organization_id == owner:
        player.last_updated = utcnow()
    db.flush()
    return rowobj, existing is None


def _err(e: Exception) -> str:
    if getattr(e, "status_code", None) == 402:
        return e.detail
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
    return str(e)


def run_rows(db: Session, rows: list[dict], fn, dry_run: bool) -> dict:
    created = updated = 0
    errors = []
    for i, row in enumerate(rows, start=1):
        sp = db.begin_nested()
        try:
            _, was_created = fn(row)
            sp.commit()
            created += was_created
            updated += not was_created
        except Exception as e:  # noqa: BLE001 — report every row-level failure
            sp.rollback()
            errors.append({"row": i, "error": _err(e)})
    return {"rows": len(rows), "created": created, "updated": updated, "errors": errors, "dry_run": dry_run}


def parse_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))
