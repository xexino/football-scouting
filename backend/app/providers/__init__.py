"""Boundary for external football-data providers — deliberately separate from ``app.mcp``.

Rules (docs/data/DATA_LICENSING_REGISTER.md, docs/mcp/MCP_ARCHITECTURE.md):

* A provider may be enabled for customer data only when the register marks it
  ``VERIFIED-COMMERCIAL-OK``. Everything else is refused here, in code.
* API keys are read server-side from environment variables, never sent to the browser or
  to an MCP client, and are redacted from every error message.
* Only public reference identifiers (league / team / player ids, names, seasons) may be sent
  to a provider. Requests carrying organization-private fields are refused.
* Provider failures (timeouts, HTTP errors, quota exhaustion, malformed payloads) become a
  ``ProviderError`` with a safe message; callers degrade gracefully.

No concrete adapter is enabled: no paid provider is approved and the keyless commercial-OK
sources are imported through the existing CSV/JSON import path.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from ..models import ASSESSMENT_FIELDS

COMMERCIAL_OK = "VERIFIED-COMMERCIAL-OK"

# Mirror of the register's status column for providers that have an adapter candidate.
LICENSE_STATUS = {
    "openfootball": COMMERCIAL_OK,
    "thesportsdb": COMMERCIAL_OK,          # data only, not images
    "statsbomb_open": "VERIFIED-NON-COMMERCIAL",
    "football_data_org": "UNVERIFIED",
    "api_football": "UNVERIFIED",
    "sportmonks": "UNVERIFIED",
    "sportapi": "UNVERIFIED",
    "wikidata": "UNVERIFIED",
}
PRIVATE_KEYS = set(ASSESSMENT_FIELDS) | {"rating", "recommendation", "sections", "potential_rating", "report",
                                         "observations", "technical_comment", "tactical_comment"}


class ProviderError(RuntimeError):
    def __init__(self, provider: str, kind: str, message: str):
        super().__init__(f"{provider}: {message}")
        self.provider, self.kind, self.message = provider, kind, message


class ProviderNotAllowed(ProviderError):
    pass


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    key_env: str | None = None
    key_header: str | None = None
    timeout_seconds: float = 10.0


Opener = Callable[[urllib.request.Request, float], object]


def _default_opener(req: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — https base URLs only (checked below)


class ProviderClient:
    def __init__(self, cfg: ProviderConfig, opener: Opener = _default_opener, production: bool = True):
        status = LICENSE_STATUS.get(cfg.name, "UNVERIFIED")
        if production and status != COMMERCIAL_OK:
            raise ProviderNotAllowed(cfg.name, "licence", f"licence status is {status}; not allowed for customer data")
        if not cfg.base_url.startswith("https://"):
            raise ProviderNotAllowed(cfg.name, "config", "provider base URL must use https")
        self.cfg, self._open = cfg, opener

    def _key(self) -> str | None:
        return os.getenv(self.cfg.key_env) if self.cfg.key_env else None

    def _redact(self, text: str) -> str:
        key = self._key()
        return text.replace(key, "[REDACTED]") if key else text

    def get_json(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        leaked = PRIVATE_KEYS & set(params)
        if leaked:
            raise ProviderNotAllowed(self.cfg.name, "privacy",
                                     f"refusing to send organization-private fields: {sorted(leaked)}")
        from urllib.parse import urlencode
        url = self.cfg.base_url.rstrip("/") + "/" + path.lstrip("/") + (f"?{urlencode(params)}" if params else "")
        headers = {"Accept": "application/json", "User-Agent": "raja-scout-provider-client"}
        key = self._key()
        if self.cfg.key_header:
            if not key:
                raise ProviderError(self.cfg.name, "config", f"API key not configured ({self.cfg.key_env})")
            headers[self.cfg.key_header] = key
        try:
            resp = self._open(urllib.request.Request(url, headers=headers), self.cfg.timeout_seconds)
            body = resp.read()
        except urllib.error.HTTPError as e:
            kind = {401: "auth", 403: "auth", 404: "not_found", 429: "quota"}.get(e.code, "upstream")
            raise ProviderError(self.cfg.name, kind, self._redact(f"HTTP {e.code} from provider")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ProviderError(self.cfg.name, "unavailable",
                                self._redact(f"provider unreachable ({type(e).__name__})")) from None
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            raise ProviderError(self.cfg.name, "malformed", "provider returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ProviderError(self.cfg.name, "malformed", "unexpected payload shape")
        return data
