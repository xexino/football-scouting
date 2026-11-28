"""The single security choke point for every MCP tool call.

Transport-agnostic (stdio, Streamable HTTP, in-process tests): the transport supplies the
caller's bearer token, this module does everything else, on *every* call:

1. authenticate the token (signature, expiry, active user, token version = not revoked);
2. resolve organization membership and set the tenant context (``security.get_ctx``) — from
   here on the ORM tenant filter makes other clubs' rows invisible;
3. apply the existing RBAC permissions of the role;
4. rate-limit per user and organization (counted from the audit log, so it holds across
   workers and restarts);
5. run the tool, which calls the existing REST endpoint functions / application services;
6. write an audit record for allowed, denied, failed and rate-limited calls.

Errors returned to the agent never contain tokens, SQL or stack traces.
"""
from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.params import Depends as DependsParam
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import settings
from ..database import SessionLocal
from ..models import AuditLog
from ..security import Ctx, decode_token, get_ctx
from ..tenancy import TenantContextMissing, TenantViolation

logger = logging.getLogger("raja_scout.mcp")

MAX_AUDIT_ARG_CHARS = 200


class ToolError(Exception):
    """A refusal or failure reported to the agent as a tool error (never raised to the transport)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., Any]          # fn(ctx, db, **args) -> JSON-able
    permissions: tuple[str, ...]    # role must hold all of them
    write: bool = False
    description: str = ""
    preview: Callable[..., Any] | None = None  # write tools: fn(ctx, db, **args) -> summary for the human
    routers: tuple[Callable, ...] = field(default=())  # endpoints the tool calls (permission consistency test)


class _MethodOnly:
    """``get_ctx`` only reads ``request.method`` (to block writes for read-only subscriptions)."""

    def __init__(self, method: str):
        self.method = method


# --------------------------------------------------------------------------- calling endpoints
def call_endpoint(endpoint: Callable, ctx: Ctx, db: Session, **kwargs):
    """Call a FastAPI endpoint function directly, as the authenticated context.

    Endpoint defaults such as ``Query(None)`` are FieldInfo objects, not values; they are
    resolved here so the function behaves exactly as it does behind the REST API. The
    endpoint's own ``Depends(require(...))`` is satisfied with the gateway's context — the
    gateway has already enforced at least the same permissions (see ``router_permissions``).
    """
    args = {}
    for name, p in inspect.signature(endpoint).parameters.items():
        if name in kwargs:
            args[name] = kwargs.pop(name)
        elif name == "db":
            args[name] = db
        elif isinstance(p.default, DependsParam):
            args[name] = ctx
        elif name == "request":
            args[name] = None  # audit.log records no IP for MCP-originated writes
        elif isinstance(p.default, FieldInfo):
            if p.default.default is PydanticUndefined:
                raise TypeError(f"{endpoint.__name__}: missing required argument {name}")
            args[name] = p.default.default
        elif p.default is inspect.Parameter.empty:
            raise TypeError(f"{endpoint.__name__}: missing required argument {name}")
        else:
            args[name] = p.default
    if kwargs:
        raise TypeError(f"{endpoint.__name__}: unexpected arguments {sorted(kwargs)}")
    return endpoint(**args)


def router_permissions(endpoint: Callable) -> set[str]:
    """Permissions an endpoint demands through ``Depends(require(...))``."""
    perms: set[str] = set()
    for p in inspect.signature(endpoint).parameters.values():
        if isinstance(p.default, DependsParam) and p.default.dependency is not None:
            dep = p.default.dependency
            for cell in dep.__closure__ or ():
                value = cell.cell_contents
                if isinstance(value, tuple) and all(isinstance(v, str) for v in value):
                    perms.update(value)
    return perms


# --------------------------------------------------------------------------- helpers
def _sanitize(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        s = v if isinstance(v, (int, float, bool)) or v is None else str(v)
        if isinstance(s, str) and len(s) > MAX_AUDIT_ARG_CHARS:
            s = s[:MAX_AUDIT_ARG_CHARS] + "…"
        out[k] = s
    return out


def _audit(db: Session, ctx: Ctx, action: str, spec_name: str, args: dict, outcome: str,
           transport: str, started: float, extra: dict | None = None) -> None:
    details = {"tool": spec_name, "args": _sanitize(args), "outcome": outcome, "transport": transport,
               "duration_ms": round((time.monotonic() - started) * 1000)}
    if extra:
        details.update(extra)
    audit.log(db, ctx, action, "mcp_tool", None, details)
    db.commit()


def _recent_calls(db: Session, ctx: Ctx) -> int:
    since = datetime.now(timezone.utc) - timedelta(seconds=60)
    return db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.user_id == ctx.id, AuditLog.action.like("mcp.%"), AuditLog.action != "mcp.rate_limited",
        AuditLog.created_at >= since)) or 0


def _http_to_tool_error(e: HTTPException) -> ToolError:
    code = {400: "invalid_input", 401: "unauthenticated", 402: "subscription_read_only", 403: "forbidden",
            404: "not_found", 409: "conflict", 422: "invalid_input", 429: "rate_limited"}.get(e.status_code, "error")
    detail = e.detail if isinstance(e.detail, str) else "Request rejected"
    return ToolError(code, detail)


# --------------------------------------------------------------------------- authentication
def authenticate(db: Session, token: str | None, *, write: bool) -> Ctx:
    if not token:
        raise ToolError("unauthenticated", "Authentication required")
    try:
        decode_token(token)
        return get_ctx(_MethodOnly("POST" if write else "GET"), token, db)
    except HTTPException as e:
        raise _http_to_tool_error(e)


def verify_bearer(token: str) -> int | None:
    """Connection-level check used by the HTTP transport (returns the user id, or None)."""
    with SessionLocal() as db:
        try:
            ctx = authenticate(db, token, write=False)
            return ctx.id
        except ToolError:
            return None


# --------------------------------------------------------------------------- the call
def invoke(spec: ToolSpec, args: dict, token: str | None, *, transport: str, phase: str = "execute",
           approval: str | None = None) -> dict:
    """Run one tool call end to end. Returns a JSON-able dict; never raises.

    ``phase``: "execute" (default) or "preview" (write tools: authorise and describe the action,
    change nothing). ``approval`` is recorded in the audit log for executed write actions.
    """
    started = time.monotonic()
    db = SessionLocal()
    ctx: Ctx | None = None
    action = "mcp.tool_call" if not spec.write else ("mcp.write_preview" if phase == "preview" else "mcp.write_executed")
    try:
        ctx = authenticate(db, token, write=spec.write and phase == "execute")
        missing = [p for p in spec.permissions if p not in ctx.permissions]
        if missing:
            _audit(db, ctx, "mcp.tool_denied", spec.name, args, "forbidden", transport, started,
                   {"missing": missing})
            raise ToolError("forbidden", f"Your role ({ctx.role}) lacks permission: {', '.join(missing)}")
        if _recent_calls(db, ctx) >= settings.mcp_rate_limit_per_minute:
            _audit(db, ctx, "mcp.rate_limited", spec.name, args, "rate_limited", transport, started)
            raise ToolError("rate_limited", "Too many tool calls; limit is "
                                            f"{settings.mcp_rate_limit_per_minute} per minute. Try again shortly.")
        if phase == "preview":
            if spec.preview is None:
                raise ToolError("error", "This tool has no preview")
            result = spec.preview(ctx, db, **args)
        else:
            result = spec.fn(ctx, db, **args)
        result = jsonable_encoder(result)
        db.rollback()  # read tools must not leave anything pending; write endpoints commit themselves
        _audit(db, ctx, action, spec.name, args, "ok", transport, started,
               {"approval": approval} if approval else None)
        return result if isinstance(result, dict) else {"items": result}
    except ToolError as e:
        if ctx is None:
            logger.info("mcp call refused before authentication: tool=%s code=%s", spec.name, e.code)
        return e.as_dict()
    except HTTPException as e:
        err = _http_to_tool_error(e)
        db.rollback()
        if ctx is not None:
            _audit(db, ctx, action, spec.name, args, err.code, transport, started)
        return err.as_dict()
    except (TenantViolation, TenantContextMissing):
        db.rollback()
        logger.warning("mcp tenant guard triggered: tool=%s", spec.name)
        if ctx is not None:
            _audit(db, ctx, action, spec.name, args, "tenant_violation", transport, started)
        return ToolError("forbidden", "Access to that data is not allowed").as_dict()
    except Exception:  # noqa: BLE001 — never leak internals to the agent
        db.rollback()
        logger.exception("mcp tool failed: %s", spec.name)
        if ctx is not None:
            _audit(db, ctx, action, spec.name, args, "internal_error", transport, started)
        return ToolError("internal_error", "The tool failed. The incident was logged.").as_dict()
    finally:
        db.close()


def record(token: str | None, spec: ToolSpec, args: dict, action: str, outcome: str, transport: str) -> None:
    """Audit an event that happens outside ``invoke`` (e.g. a human declined a write action)."""
    started = time.monotonic()
    with SessionLocal() as db:
        try:
            ctx = authenticate(db, token, write=False)
        except ToolError:
            return
        _audit(db, ctx, action, spec.name, args, outcome, transport, started)
