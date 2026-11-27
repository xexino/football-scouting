"""The current organization's identity, branding and settings."""
from __future__ import annotations

import base64
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..models import LANGUAGES
from ..security import Ctx, get_ctx, require
from ..serializers import organization_out

router = APIRouter(prefix="/api/organization", tags=["organization"])

# Currencies offered in the UI (North Africa first, then wider Africa + common transfer currencies).
CURRENCIES = ("MAD", "DZD", "TND", "EGP", "LYD", "MRU", "XOF", "XAF", "NGN", "GHS", "KES", "ZAR",
              "EUR", "USD", "GBP", "SAR", "AED", "QAR")
SETTINGS_KEYS = {
    "home_league": (str, 120),      # used in reports: "may not translate to <home_league>"
    "report_footer": (str, 300),    # printed on exported reports
    "accent_color": (str, 7),       # #RRGGBB, optional UI accent
}
MAX_LOGO_BYTES = 256 * 1024
_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg"}


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=40)
    country: str | None = Field(default=None, max_length=100)
    primary_language: str | None = None
    currency: str | None = None
    timezone: str | None = None
    settings: dict | None = None

    @field_validator("primary_language")
    @classmethod
    def _lang(cls, v):
        if v is not None and v not in LANGUAGES:
            raise ValueError(f"Supported languages: {', '.join(LANGUAGES)}")
        return v

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        if v is not None:
            v = v.upper()
            if v not in CURRENCIES:
                raise ValueError(f"Supported currencies: {', '.join(CURRENCIES)}")
        return v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v is not None and v not in available_timezones():
            raise ValueError("Unknown IANA timezone")
        return v

    @field_validator("settings")
    @classmethod
    def _settings(cls, v):
        if v is None:
            return v
        clean = {}
        for k, val in v.items():
            if k not in SETTINGS_KEYS:
                raise ValueError(f"Unknown setting '{k}'. Allowed: {', '.join(SETTINGS_KEYS)}")
            typ, maxlen = SETTINGS_KEYS[k]
            if val is None or val == "":
                clean[k] = None  # explicit removal
                continue
            if not isinstance(val, typ) or len(val) > maxlen:
                raise ValueError(f"Invalid value for '{k}'")
            if k == "accent_color" and not (val.startswith("#") and len(val) == 7
                                             and all(c in "0123456789abcdefABCDEF" for c in val[1:])):
                raise ValueError("accent_color must be #RRGGBB")
            clean[k] = val
        return clean


@router.get("", summary="Current organization identity & settings")
def get_org(ctx: Ctx = Depends(get_ctx)):
    out = organization_out(ctx.organization)
    out["options"] = {"languages": LANGUAGES, "currencies": CURRENCIES, "settings": list(SETTINGS_KEYS)}
    return out


@router.patch("", summary="Update organization identity & settings")
def update_org(body: OrganizationUpdate, request: Request, ctx: Ctx = Depends(require("org:manage")),
               db: Session = Depends(get_db)):
    org = ctx.organization
    changes = body.model_dump(exclude_unset=True)
    if "settings" in changes:
        merged = {**(org.settings or {}), **changes["settings"]}
        changes["settings"] = {k: v for k, v in merged.items() if v is not None}
    for k, v in changes.items():
        setattr(org, k, v)
    audit.log(db, ctx, "organization.update", "organization", org.id, changes, request)
    db.commit()
    return organization_out(org)


def detect_image_type(data: bytes) -> str | None:
    for sig, mime in _SIGNATURES.items():
        if data.startswith(sig):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/logo", summary="Upload the organization logo (PNG, JPEG or WebP, max 256 KB)")
async def upload_logo(request: Request, file: UploadFile = File(...), ctx: Ctx = Depends(require("org:manage")),
                      db: Session = Depends(get_db)):
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(413, "Logo too large (max 256 KB)")
    mime = detect_image_type(data)  # by content, never by the client-declared type; SVG is refused
    if mime is None:
        raise HTTPException(422, "Logo must be a PNG, JPEG or WebP image")
    ctx.organization.logo_data_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    audit.log(db, ctx, "organization.logo_update", "organization", ctx.organization_id,
              {"bytes": len(data), "type": mime}, request)
    db.commit()
    return organization_out(ctx.organization)


@router.delete("/logo", status_code=204)
def delete_logo(request: Request, ctx: Ctx = Depends(require("org:manage")), db: Session = Depends(get_db)):
    ctx.organization.logo_data_url = None
    audit.log(db, ctx, "organization.logo_delete", "organization", ctx.organization_id, None, request)
    db.commit()
