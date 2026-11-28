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
from .routers import (
    admin,
    auth,
    compare,
    dashboard,
    imports,
    organization,
    pipeline,
    platform,
    players,
    reference,
    reports,
    subscription,
    users,
    video,
)

logger = logging.getLogger("raja_scout")
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def check_environment_separation() -> None:
    """Demo and customer data must never share a deployment."""
    from sqlalchemy import select

    from .models import Organization
    from .tenancy import SYSTEM, set_tenant
    with SessionLocal() as db:
        set_tenant(db, SYSTEM)
        flags = set(db.scalars(select(Organization.is_demo)).all())
    if settings.deployment_mode == "demo" and False in flags:
        raise RuntimeError("DEPLOYMENT_MODE=demo but this database contains customer (non-demo) organizations. "
                           "Refusing to start: customer data must never be exposed in a demo environment.")
    if settings.deployment_mode == "customer" and True in flags:
        raise RuntimeError("DEPLOYMENT_MODE=customer but this database contains demo organizations. "
                           "Remove them (python -m app.cli delete-org demo-fc) or use a separate demo database.")


def init_db(seed: bool | None = None) -> None:
    from .migrate import migrate_database
    migrate_database()
    check_environment_separation()
    do_seed = seed if seed is not None else settings.deployment_mode == "demo"
    if do_seed and settings.deployment_mode != "demo":
        raise RuntimeError("Demo data can only be loaded when DEPLOYMENT_MODE=demo")
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
    docs_url="/docs" if settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.expose_api_docs else None,
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
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if settings.env == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(TenantViolation)
async def _tenant_violation(request, exc):
    logger.warning("Tenant violation on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Access to data outside your organization is not permitted"}, status_code=403)


@app.exception_handler(TenantContextMissing)
async def _tenant_missing(request, exc):
    logger.error("Missing tenant context on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"detail": "Internal authorization error"}, status_code=500)


app.include_router(platform.billing_router)
for r in (auth, organization, subscription, platform, users, reference, players, compare, video, reports, pipeline, dashboard, imports, admin):
    app.include_router(r.router)


@app.get("/api/public/config", tags=["system"], summary="Public, non-sensitive client configuration")
def public_config():
    out = {"product": "Raja Scout Intelligence", "deployment_mode": settings.deployment_mode,
           "notice": "Independent software. Not affiliated with, endorsed or sponsored by Raja Club Athletic "
                     "or any club using it."}
    if settings.deployment_mode == "demo":
        out["demo_accounts"] = ["director@raja-scout.local", "head.scouting@raja-scout.local", "analyst@raja-scout.local",
                                "video@raja-scout.local", "scout.westafrica@raja-scout.local", "admin@raja-scout.local"]
    return out


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
