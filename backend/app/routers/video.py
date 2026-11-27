"""Video scouting: licensed footage links, timestamped observations and match reports.

The platform stores *links* to footage on licensed platforms only. It never downloads,
hosts or redistributes video. Highlight packages are explicitly flagged and are never
treated as complete match analysis.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..database import get_db
from ..models import MatchReport, MatchVideo, Player, User, VideoObservation
from ..schemas import MatchReportIn, ObservationIn, ObservationOut, VideoIn, VideoOut
from ..security import Ctx, has_permission, require
from ..serializers import match_report_out

router = APIRouter(prefix="/api", tags=["video & match reports"])


def _video(db: Session, video_id: int) -> MatchVideo:
    v = db.scalar(select(MatchVideo).where(MatchVideo.id == video_id).options(selectinload(MatchVideo.observations)))
    if v is None:
        raise HTTPException(404, "Video not found")
    return v


def _video_out(v: MatchVideo) -> dict:
    out = VideoOut.model_validate(v).model_dump()
    out["player_name"] = v.player.full_name if v.player else None
    out["analysis_scope"] = "full_match" if v.is_full_match else "partial_or_highlights"
    if not v.is_full_match:
        out["scope_warning"] = "Not full-match footage: observations cannot substitute for complete match analysis."
    return out


@router.get("/videos")
def list_videos(player_id: int | None = None, _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    q = select(MatchVideo).options(selectinload(MatchVideo.observations), selectinload(MatchVideo.player)) \
        .order_by(MatchVideo.match_date.desc().nulls_last(), MatchVideo.id.desc())
    if player_id:
        q = q.where(MatchVideo.player_id == player_id)
    return [_video_out(v) for v in db.scalars(q).all()]


@router.post("/videos", status_code=201, summary="Register a link to licensed footage")
def create_video(body: VideoIn, request: Request, user: Ctx = Depends(require("video:write")),
                 db: Session = Depends(get_db)):
    if db.get(Player, body.player_id) is None:
        raise HTTPException(404, "Player not found")
    v = MatchVideo(**body.model_dump(), created_by_id=user.id)
    db.add(v)
    db.flush()
    audit.log(db, user, "video.create", "match_video", v.id,
              {"player_id": v.player_id, "license_type": v.license_type, "rights_holder": v.rights_holder}, request)
    db.commit()
    return _video_out(_video(db, v.id))


@router.get("/videos/{video_id}")
def get_video(video_id: int, _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    return _video_out(_video(db, video_id))


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: int, request: Request, user: Ctx = Depends(require("video:write")),
                 db: Session = Depends(get_db)):
    v = _video(db, video_id)
    audit.log(db, user, "video.delete", "match_video", v.id, {"player_id": v.player_id}, request)
    db.delete(v)
    db.commit()


@router.post("/videos/{video_id}/observations", status_code=201, response_model=ObservationOut)
def add_observation(video_id: int, body: ObservationIn, request: Request, user: Ctx = Depends(require("video:write")),
                    db: Session = Depends(get_db)):
    v = _video(db, video_id)
    if v.duration_minutes and body.timestamp_seconds > v.duration_minutes * 60:
        raise HTTPException(422, "Timestamp is beyond the footage duration")
    obs = VideoObservation(video_id=v.id, scout_id=user.id, **body.model_dump())
    db.add(obs)
    db.flush()
    audit.log(db, user, "video.observation_add", "video_observation", obs.id, {"video_id": v.id}, request)
    db.commit()
    return obs


@router.delete("/videos/{video_id}/observations/{obs_id}", status_code=204)
def delete_observation(video_id: int, obs_id: int, request: Request, user: Ctx = Depends(require("video:write")),
                       db: Session = Depends(get_db)):
    obs = db.get(VideoObservation, obs_id)
    if obs is None or obs.video_id != video_id:
        raise HTTPException(404, "Observation not found")
    if obs.scout_id != user.id and not has_permission(user, "users:manage") and user.role != "head_of_scouting":
        raise HTTPException(403, "Only the author or Head of Scouting can delete an observation")
    audit.log(db, user, "video.observation_delete", "video_observation", obs.id, {"video_id": video_id}, request)
    db.delete(obs)
    db.commit()


# --------------------------------------------------------------------------- match reports
@router.get("/match-reports")
def list_match_reports(player_id: int | None = None, scout_id: int | None = None,
                       _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    q = select(MatchReport).options(selectinload(MatchReport.scout)).order_by(MatchReport.created_at.desc())
    if player_id:
        q = q.where(MatchReport.player_id == player_id)
    if scout_id:
        q = q.where(MatchReport.scout_id == scout_id)
    return [match_report_out(r) for r in db.scalars(q).all()]


@router.post("/match-reports", status_code=201, summary="Save an individual match report (video or live)")
def create_match_report(body: MatchReportIn, request: Request, user: Ctx = Depends(require("match_reports:write")),
                        db: Session = Depends(get_db)):
    if db.get(Player, body.player_id) is None:
        raise HTTPException(404, "Player not found")
    if body.video_id:
        v = db.get(MatchVideo, body.video_id)
        if v is None or v.player_id != body.player_id:
            raise HTTPException(422, "Video does not belong to this player")
        if body.observation_type == "video_full_match" and not v.is_full_match:
            raise HTTPException(422, "This footage is not registered as a full match; use observation_type 'video_highlights'")
    elif body.observation_type.startswith("video"):
        raise HTTPException(422, "Video reports must reference a registered video")
    r = MatchReport(**body.model_dump(), scout_id=user.id)
    db.add(r)
    db.flush()
    audit.log(db, user, "match_report.create", "match_report", r.id,
              {"player_id": r.player_id, "type": r.observation_type}, request)
    db.commit()
    db.refresh(r)
    return match_report_out(r)


@router.get("/match-reports/{report_id}")
def get_match_report(report_id: int, _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    r = db.get(MatchReport, report_id)
    if r is None:
        raise HTTPException(404, "Match report not found")
    return match_report_out(r)
