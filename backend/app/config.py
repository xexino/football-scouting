"""Application configuration, read from environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("RAJA_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql+psycopg://raja:raja@localhost:5432/raja_scout"
        )
    )
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", ""))
    token_expire_minutes: int = field(
        default_factory=lambda: int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))
    )
    # "demo": public demo with fictional data only (seeded, demo accounts shown on login).
    # "customer": real customer data; demo data is never loaded. See docs/saas/04_STAGE3_PRODUCTION.md
    deployment_mode: str = field(default_factory=lambda: os.getenv("DEPLOYMENT_MODE", ""))
    # API docs are hidden in production unless explicitly enabled.
    expose_api_docs: bool = field(default_factory=lambda: _bool("EXPOSE_API_DOCS",
                                                                os.getenv("RAJA_ENV", "development") != "production"))
    # Number of reverse proxies under our control in front of the app (see app/netutil.py).
    trusted_proxy_hops: int = field(default_factory=lambda: int(os.getenv("TRUSTED_PROXY_HOPS", "0")))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "").rstrip("/"))
    invitation_ttl_hours: int = field(default_factory=lambda: int(os.getenv("INVITATION_TTL_HOURS", "168")))
    password_reset_ttl_hours: int = field(default_factory=lambda: int(os.getenv("PASSWORD_RESET_TTL_HOURS", "24")))
    cors_origins: list[str] = field(
        default_factory=lambda: [o for o in os.getenv("CORS_ORIGINS", "").split(",") if o]
    )
    # Minimum minutes before per-90 figures are treated as a reliable sample.
    min_minutes_reliable: int = field(
        default_factory=lambda: int(os.getenv("MIN_MINUTES_RELIABLE", "900"))
    )
    # Minimum minutes for a player to be included in percentile reference pools.
    min_minutes_pool: int = field(
        default_factory=lambda: int(os.getenv("MIN_MINUTES_POOL", "450"))
    )
    max_login_attempts: int = field(
        default_factory=lambda: int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
    )
    login_lockout_seconds: int = field(
        default_factory=lambda: int(os.getenv("LOGIN_LOCKOUT_SECONDS", "900"))
    )
    max_login_attempts_per_ip: int = field(
        default_factory=lambda: int(os.getenv("MAX_LOGIN_ATTEMPTS_PER_IP", "30"))
    )

    # MCP (Model Context Protocol) gateway for AI agents — see docs/mcp/MCP_ARCHITECTURE.md.
    # Write tools stay unregistered (not even listed) unless explicitly enabled.
    mcp_write_tools_enabled: bool = field(default_factory=lambda: _bool("MCP_WRITE_TOOLS_ENABLED", False))
    mcp_rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("MCP_RATE_LIMIT_PER_MINUTE", "60")))

    # Run table creation / demo seeding inside the web process. Disable when a separate
    # bootstrap step runs first (Docker image), so several workers don't race.
    init_on_startup: bool = field(default_factory=lambda: _bool("INIT_ON_STARTUP", True))

    def __post_init__(self) -> None:
        # Hosting providers give "postgres://" or "postgresql://" URLs; use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefix):]
        if not self.deployment_mode:
            self.deployment_mode = "customer" if self.env == "production" else "demo"
        if self.deployment_mode not in ("demo", "customer"):
            raise RuntimeError("DEPLOYMENT_MODE must be 'demo' or 'customer'")
        if self.env == "production" and self.database_url.startswith("sqlite"):
            raise RuntimeError("SQLite is not supported in production; use PostgreSQL")
        if self.env == "production" and "*" in self.cors_origins:
            raise RuntimeError("CORS_ORIGINS='*' is not allowed in production; list exact origins")
        if not self.secret_key:
            if self.env == "production":
                raise RuntimeError("SECRET_KEY must be set in production")
            # Ephemeral key for development/tests: tokens are invalidated on restart.
            self.secret_key = secrets.token_urlsafe(48)
        if self.env == "production" and len(self.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters in production")


settings = Settings()
