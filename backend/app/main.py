"""Raja Scout Intelligence — FastAPI application."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .database import Base, SessionLocal, engine
from .tenancy import TenantContextMissing, TenantViolation
from .routers import admin, auth, compare, dashboard, imports, organization, pipeline, players, reference, reports, users, video

logger = logging.getLogger("raja_scout")
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def init_db(seed: bool | None = None) -> None:
    from .migrate import migrate_database
    migrate_database()
    do_seed = seed if seed is not None else settings.seed_sample_data
    if do_seed and settings.env == "production" and os.getenv("ALLOW_DEMO_IN_PRODUCTION") != "1":
        raise RuntimeError("Refusing to load fictional demo data and demo accounts in production. "
                           "Set SEED_SAMPLE_DATA=false and create users with `python -m app.cli create-user`.")
    if do_seed:
        from .seed import seed as run_seed
        with SessionLocal() as db:
            run_seed(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.init_on_startup:
        init_db()
    yield


app = FastAPI(
    title="Raja Scout Intelligence API",
    version="1.0.0",
    description=(
        "Raja Scout Intelligence — multi-tenant football recruitment intelligence platform (SaaS). "
        "Independent software; not affiliated with or endorsed by Raja Club Athletic. "
        "Authenticate via `POST /api/auth/token`, then send `Authorization: Bearer <token>`. "
        "All statistics carry provenance; fictional sample data is flagged `is_fictional`."
    ),
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


@app.exception_handler(TenantViolation)
async def _tenant_violation(request, exc):
    logger.warning("Tenant violation on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Access to data outside your organization is not permitted"}, status_code=403)


@app.exception_handler(TenantContextMissing)
async def _tenant_missing(request, exc):
    logger.error("Missing tenant context on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Internal authorization error"}, status_code=500)


for r in (auth, organization, users, reference, players, compare, video, reports, pipeline, dashboard, imports, admin):
    app.include_router(r.router)


@app.get("/api/health", tags=["system"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "env": settings.env}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
