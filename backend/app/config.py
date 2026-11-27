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
    seed_sample_data: bool = field(default_factory=lambda: _bool("SEED_SAMPLE_DATA", True))
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

    def __post_init__(self) -> None:
        if not self.secret_key:
            if self.env == "production":
                raise RuntimeError("SECRET_KEY must be set in production")
            # Ephemeral key for development/tests: tokens are invalidated on restart.
            self.secret_key = secrets.token_urlsafe(48)
        if self.env == "production" and len(self.secret_key) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters in production")


settings = Settings()
