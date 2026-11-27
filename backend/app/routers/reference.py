"""Leagues, clubs, data sources and enumerations."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..analytics import METRICS, POSITION_PROFILES, TACTICAL_ROLES
from ..database import get_db
from ..models import (
    AVAILABILITY,
    FEET,
    GAME_PHASES,
    OBSERVATION_ASSESSMENTS,
    OBSERVATION_CATEGORIES,
    PIPELINE_STAGES,
    POSITION_LABELS,
    PRIORITIES,
    RECOMMENDATIONS,
    REPORT_OBSERVATION_TYPES,
    SOURCE_TYPES,
    VIDEO_LICENSES,
    Club,
    DataSource,
    League,
    User,
)
from ..schemas import ClubIn, ClubOut, DataSourceIn, DataSourceOut, LeagueIn, LeagueOut
from ..security import Ctx, ROLE_LABELS, get_current_user, require

router = APIRouter(prefix="/api", tags=["reference"])


@router.get("/meta", summary="Enumerations, metric catalogue and tactical roles used by the UI")
def meta(_: User = Depends(get_current_user)):
    return {
        "positions": POSITION_LABELS,
        "feet": FEET,
        "availability": AVAILABILITY,
        "pipeline_stages": PIPELINE_STAGES,
        "priorities": PRIORITIES,
        "recommendations": RECOMMENDATIONS,
        "video_licenses": VIDEO_LICENSES,
        "observation_categories": OBSERVATION_CATEGORIES,
        "game_phases": GAME_PHASES,
        "observation_assessments": OBSERVATION_ASSESSMENTS,
        "report_observation_types": REPORT_OBSERVATION_TYPES,
        "source_types": SOURCE_TYPES,
        "roles": ROLE_LABELS,
        "metrics": {k: {"label": m.label, "group": m.group, "unit": m.unit, "higher_is_better": m.higher_is_better}
                    for k, m in METRICS.items()},
        "position_profiles": POSITION_PROFILES,
        "tactical_roles": {k: {"label": v["label"], "position": v["position"], "weights": v["weights"]}
                           for k, v in TACTICAL_ROLES.items()},
    }


@router.get("/leagues", response_model=list[LeagueOut])
def leagues(_: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    return db.scalars(select(League).order_by(League.country, League.name)).all()


@router.post("/leagues", response_model=LeagueOut, status_code=201)
def create_league(body: LeagueIn, request: Request, user: Ctx = Depends(require("players:write")),
                  db: Session = Depends(get_db)):
    if db.scalar(select(League).where(League.name == body.name, League.country == body.country)):
        raise HTTPException(409, "League already exists")
    league = League(**body.model_dump())
    db.add(league)
    db.flush()
    audit.log(db, user, "league.create", "league", league.id, body.model_dump(), request)
    db.commit()
    return league


@router.patch("/leagues/{league_id}", response_model=LeagueOut)
def update_league(league_id: int, body: LeagueIn, request: Request, user: Ctx = Depends(require("stats:write")),
                  db: Session = Depends(get_db)):
    league = db.get(League, league_id)
    if league is None:
        raise HTTPException(404, "League not found")
    for k, v in body.model_dump().items():
        setattr(league, k, v)
    audit.log(db, user, "league.update", "league", league.id, body.model_dump(), request)
    db.commit()
    return league


@router.get("/clubs", response_model=list[ClubOut])
def clubs(league_id: int | None = None, _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    q = select(Club).order_by(Club.name)
    if league_id:
        q = q.where(Club.league_id == league_id)
    return db.scalars(q).all()


@router.post("/clubs", response_model=ClubOut, status_code=201)
def create_club(body: ClubIn, request: Request, user: Ctx = Depends(require("players:write")),
                db: Session = Depends(get_db)):
    if db.scalar(select(Club).where(Club.name == body.name, Club.country == body.country)):
        raise HTTPException(409, "Club already exists")
    club = Club(**body.model_dump())
    db.add(club)
    db.flush()
    audit.log(db, user, "club.create", "club", club.id, body.model_dump(), request)
    db.commit()
    return club


@router.get("/data-sources", response_model=list[DataSourceOut])
def data_sources(_: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    return db.scalars(select(DataSource).order_by(DataSource.name)).all()


@router.post("/data-sources", response_model=DataSourceOut, status_code=201)
def create_data_source(body: DataSourceIn, request: Request, user: Ctx = Depends(require("players:write")),
                       db: Session = Depends(get_db)):
    if db.scalar(select(DataSource).where(DataSource.name == body.name)):
        raise HTTPException(409, "Data source already exists")
    src = DataSource(**body.model_dump())
    db.add(src)
    db.flush()
    audit.log(db, user, "data_source.create", "data_source", src.id, body.model_dump(), request)
    db.commit()
    return src
