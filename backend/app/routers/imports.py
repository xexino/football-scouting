"""Data import via CSV upload or JSON (API/ETL integration)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..importers import import_player, import_stats, parse_csv, run_rows, template_csv
from ..models import DataSource, User
from ..security import Ctx, has_permission, require

router = APIRouter(prefix="/api/import", tags=["data import"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _source(db: Session, source_id: int) -> DataSource:
    src = db.get(DataSource, source_id)
    if src is None:
        raise HTTPException(422, "Unknown data source. Register the source (with licence notes) before importing.")
    if src.organization_id is None:
        raise HTTPException(422, "Imports must use one of your organization's own data sources")
    return src


@router.get("/templates/{kind}.csv", response_class=PlainTextResponse)
def template(kind: str, _: Ctx = Depends(require("import:run"))):
    if kind not in ("players", "stats"):
        raise HTTPException(404, "Unknown template")
    return PlainTextResponse(template_csv(kind), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={kind}_template.csv"})


async def _read(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 10 MB)")
    return content


@router.post("/players", summary="Import player profiles from CSV")
async def import_players_csv(request: Request, file: UploadFile = File(...), data_source_id: int = Form(...),
                             dry_run: bool = Form(False), user: Ctx = Depends(require("import:run")),
                             db: Session = Depends(get_db)):
    src = _source(db, data_source_id)
    rows = parse_csv(await _read(file))
    fin = has_permission(user, "financials:read")
    result = run_rows(db, rows, lambda r: import_player(db, r, src, user.id, fin), dry_run)
    return _finish(db, user, request, "import.players_csv", src, result, file.filename)


@router.post("/stats", summary="Import season statistics from CSV")
async def import_stats_csv(request: Request, file: UploadFile = File(...), data_source_id: int = Form(...),
                           dry_run: bool = Form(False), user: Ctx = Depends(require("import:run", "stats:write")),
                           db: Session = Depends(get_db)):
    src = _source(db, data_source_id)
    rows = parse_csv(await _read(file))
    result = run_rows(db, rows, lambda r: import_stats(db, r, src), dry_run)
    return _finish(db, user, request, "import.stats_csv", src, result, file.filename)


class JsonImport(BaseModel):
    data_source_id: int
    dry_run: bool = False
    players: list[dict] = []
    stats: list[dict] = []


@router.post("/json", summary="Import players and stats as JSON (for provider adapters / ETL jobs)")
def import_json(body: JsonImport, request: Request, user: Ctx = Depends(require("import:run", "stats:write")),
                db: Session = Depends(get_db)):
    src = _source(db, body.data_source_id)
    fin = has_permission(user, "financials:read")
    pres = run_rows(db, body.players, lambda r: import_player(db, r, src, user.id, fin), body.dry_run)
    sres = run_rows(db, body.stats, lambda r: import_stats(db, r, src), body.dry_run)
    result = {"players": pres, "stats": sres, "dry_run": body.dry_run}
    return _finish(db, user, request, "import.json", src, result, None)


def _finish(db: Session, user: User, request: Request, action: str, src: DataSource, result: dict, filename):
    if result.get("dry_run"):
        db.rollback()
        return result
    summary = {k: v for k, v in result.items() if k != "errors"}
    audit.log(db, user, action, "data_source", src.id, {"filename": filename, "summary": _shrink(summary)}, request)
    db.commit()
    return result


def _shrink(d):
    if isinstance(d, dict):
        return {k: (len(v) if k == "errors" else _shrink(v)) for k, v in d.items()}
    return d
