"""Run the Raja Scout MCP server.

    python -m app.mcp                      # stdio (local development agents, e.g. Claude Code)
    python -m app.mcp --http --port 8001   # Streamable HTTP on 127.0.0.1 (bearer token per request)

stdio: the caller's access token is read from RAJA_SCOUT_MCP_TOKEN (get one by signing in:
POST /api/auth/token). It is re-validated on every tool call (expiry, revocation, membership).
HTTP: each request must carry ``Authorization: Bearer <token>``; requests without a valid
token are rejected with 401 before any MCP processing.

This process is separate from the web app and is not started by any deployment config.
"""
from __future__ import annotations

import argparse
import os
import sys

import anyio

from ..config import settings


def http_app(host: str, port: int):
    from mcp.server.auth.middleware.auth_context import get_access_token
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings

    from . import gateway
    from .server import build_server

    class Verifier:
        async def verify_token(self, token: str) -> AccessToken | None:
            user_id = await anyio.to_thread.run_sync(gateway.verify_bearer, token)
            return None if user_id is None else AccessToken(token=token, client_id=str(user_id), scopes=[],
                                                             subject=str(user_id))

    def token_source():
        t = get_access_token()
        return t.token if t else None

    base = settings.public_base_url or f"http://{host}:{port}"
    server = build_server(token_source, transport="http", token_verifier=Verifier(),
                          auth=AuthSettings(issuer_url=base, resource_server_url=f"{base}/mcp",
                                            validate_token_resource=False))  # verifier checks the token itself
    return server.streamable_http_app(host=host)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.mcp")
    ap.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    a = ap.parse_args(argv)
    if a.http:
        import uvicorn
        uvicorn.run(http_app(a.host, a.port), host=a.host, port=a.port, log_level="info")
        return 0
    from .server import build_server
    if not os.getenv("RAJA_SCOUT_MCP_TOKEN"):
        print("RAJA_SCOUT_MCP_TOKEN is not set: every tool call will be refused as unauthenticated.",
              file=sys.stderr)
    build_server(lambda: os.getenv("RAJA_SCOUT_MCP_TOKEN"), transport="stdio").run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
