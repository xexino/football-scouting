"""Bring the database schema to the latest Alembic revision.

* PostgreSQL (all real deployments): ``alembic upgrade head``.
  A database created by the pre-Alembic version (tables present, no ``alembic_version``)
  is first stamped as ``0001_legacy`` so the multi-tenant data migration runs on it.
* SQLite (tests / quick local experiments only): ``create_all`` + stamp head, because the
  migrations use PostgreSQL features.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .database import Base, engine

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def alembic_config(connection=None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["configure_logger"] = False
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def migrate_database(eng=None) -> str:
    with (eng or engine).begin() as conn:
        cfg = alembic_config(conn)
        tables = set(inspect(conn).get_table_names())
        if conn.dialect.name == "sqlite":
            Base.metadata.create_all(conn)
            command.stamp(cfg, "head")
            return "sqlite:create_all"
        if "alembic_version" not in tables and "players" in tables:
            command.stamp(cfg, "0001_legacy")  # adopt a database created before migrations existed
        command.upgrade(cfg, "head")
        return "postgresql:upgraded"
