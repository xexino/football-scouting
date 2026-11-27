"""Consolidated scouting reports."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..database import get_db
from ..models import Club, Player, PlayerSeasonStats, ScoutingReport, User
from ..report_generator import generate_report, report_to_markdown
from ..schemas import ReportGenerateIn, ReportUpdate
from ..security import Ctx, has_permission, require
from ..serializers import report_out

router = APIRouter(prefix="/api/reports", tags=["scouting reports"])

EVIDENCE_TYPES = {"verified_data", "fictional_sample", "scout_opinion", "model_estimate",
                  "insufficient_evidence", "scout_input_required"}


def _player(db: Session, player_id: int) -> Player:
    p = db.scalar(select(Player).where(Player.id == player_id).options(
        selectinload(Player.club).selectinload(Club.league), selectinload(Player.data_source),
        selectinload(Player.stats).selectinload(PlayerSeasonStats.league),
        selectinload(Player.stats).selectinload(PlayerSeasonStats.data_source)))
    if p is None:
        raise HTTPException(404, "Player not found")
    return p


def _report(db: Session, report_id: int) -> ScoutingReport:
    r = db.scalar(select(ScoutingReport).where(ScoutingReport.id == report_id)
                  .options(selectinload(ScoutingReport.author), selectinload(ScoutingReport.player)))
    if r is None:
        raise HTTPException(404, "Report not found")
    return r


@router.get("")
def list_reports(player_id: int | None = None, _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    q = select(ScoutingReport).options(selectinload(ScoutingReport.author), selectinload(ScoutingReport.player)) \
        .order_by(ScoutingReport.updated_at.desc())
    if player_id:
        q = q.where(ScoutingReport.player_id == player_id)
    out = []
    for r in db.scalars(q).all():
        d = report_out(r)
        d.pop("sections")
        out.append(d)
    return out


@router.post("/generate", status_code=201, summary="Draft a report from platform evidence (evidence-tagged)")
def generate(body: ReportGenerateIn, request: Request, user: Ctx = Depends(require("reports:write")),
             db: Session = Depends(get_db)):
    p = _player(db, body.player_id)
    draft = generate_report(db, p, body.season, body.tactical_role, org=user.organization)
    r = ScoutingReport(player_id=p.id, author_id=user.id, title=f"Scouting report — {p.full_name}",
                       sections=draft["sections"], risk_level=draft["risk_level"], auto_generated=True)
    db.add(r)
    db.flush()
    audit.log(db, user, "report.generate", "scouting_report", r.id, {"player_id": p.id}, request)
    db.commit()
    return report_out(_report(db, r.id))


@router.get("/{report_id}")
def get_report(report_id: int, _: Ctx = Depends(require("players:read")), db: Session = Depends(get_db)):
    return report_out(_report(db, report_id))


@router.get("/{report_id}/export.md", response_class=PlainTextResponse, summary="Export report as Markdown")
def export_report(report_id: int, request: Request, user: Ctx = Depends(require("players:read")),
                  db: Session = Depends(get_db)):
    r = _report(db, report_id)
    audit.log(db, user, "report.export", "scouting_report", r.id, None, request)
    db.commit()
    return PlainTextResponse(report_to_markdown(r, r.player, user.organization), headers={
        "Content-Disposition": f"attachment; filename=report_{r.id}.md"})


def _validate_sections(sections: dict) -> None:
    for key, sec in sections.items():
        if key.startswith("_"):
            continue
        if not isinstance(sec, dict) or not isinstance(sec.get("items", []), list):
            raise HTTPException(422, f"Section '{key}' must be an object with an 'items' list")
        for it in sec.get("items", []):
            if not isinstance(it, dict) or it.get("evidence_type") not in EVIDENCE_TYPES or not it.get("text"):
                raise HTTPException(422, f"Every item in '{key}' needs 'text' and a valid 'evidence_type' "
                                         f"({', '.join(sorted(EVIDENCE_TYPES))})")
            if it["evidence_type"] in ("verified_data", "fictional_sample") and not it.get("source"):
                raise HTTPException(422, f"Data items in '{key}' must cite a source")


@router.patch("/{report_id}")
def update_report(report_id: int, body: ReportUpdate, request: Request, user: Ctx = Depends(require("reports:write")),
                  db: Session = Depends(get_db)):
    r = _report(db, report_id)
    if r.status == "final":
        raise HTTPException(409, "Final reports are locked. Generate a new version instead.")
    if r.author_id != user.id and not has_permission(user, "reports:finalize"):
        raise HTTPException(403, "Only the author or a senior user can edit this report")
    changes = body.model_dump(exclude_unset=True)
    if "sections" in changes:
        _validate_sections(changes["sections"])
        # Scout-written items added by a user are attributed to them.
        for key, sec in changes["sections"].items():
            if key.startswith("_"):
                continue
            for it in sec.get("items", []):
                if it["evidence_type"] == "scout_opinion" and not it.get("source"):
                    it["source"] = user.full_name
    for k, v in changes.items():
        setattr(r, k, v)
    audit.log(db, user, "report.update", "scouting_report", r.id, {"fields": list(changes)}, request)
    db.commit()
    return report_out(_report(db, r.id))


@router.post("/{report_id}/finalize", summary="Lock a report (requires recommendation)")
def finalize(report_id: int, request: Request, user: Ctx = Depends(require("reports:finalize")),
             db: Session = Depends(get_db)):
    r = _report(db, report_id)
    if r.status == "final":
        raise HTTPException(409, "Report already final")
    if not r.recommendation:
        raise HTTPException(422, "Set a recruitment recommendation before finalising")
    if r.player and r.player.is_fictional and r.recommendation == "sign":
        raise HTTPException(422, "Cannot finalise a 'sign' recommendation for a fictional sample player")
    r.status = "final"
    audit.log(db, user, "report.finalize", "scouting_report", r.id, {"recommendation": r.recommendation}, request)
    db.commit()
    return report_out(_report(db, r.id))


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: int, request: Request, user: Ctx = Depends(require("reports:write")),
                  db: Session = Depends(get_db)):
    r = _report(db, report_id)
    if r.status == "final" and not has_permission(user, "users:manage"):
        raise HTTPException(403, "Final reports can only be deleted by an administrator")
    if r.author_id != user.id and not has_permission(user, "reports:finalize"):
        raise HTTPException(403, "Only the author or a senior user can delete this report")
    audit.log(db, user, "report.delete", "scouting_report", r.id, {"player_id": r.player_id}, request)
    db.delete(r)
    db.commit()
