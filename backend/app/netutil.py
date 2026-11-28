"""Client IP resolution that cannot be spoofed with a client-supplied X-Forwarded-For.

* ``TRUSTED_PROXY_HOPS=0`` (default): use the socket peer address (correct when the app is
  reached directly or behind a proxy configured via uvicorn ``--forwarded-allow-ips`` with
  that proxy's exact address).
* ``TRUSTED_PROXY_HOPS=N``: the app sits behind exactly N proxies we control (e.g. a PaaS
  load balancer). Each proxy *appends* the address it saw, so the client is the N-th entry
  from the right; anything further left was written by the client and is ignored.
"""
from __future__ import annotations

from .config import settings


def client_ip(request) -> str | None:
    hops = settings.trusted_proxy_hops
    if hops > 0:
        raw = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else None
