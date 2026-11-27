"""Alembic migration tests (PostgreSQL only).

Set MIGRATION_TEST_DATABASE_URL to a *dedicated, disposable* PostgreSQL database; its
public schema is dropped and recreated by these tests."""
import os

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.database import Base
from app.migrate import alembic_config

URL = os.environ.get("MIGRATION_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="MIGRATION_TEST_DATABASE_URL not set (PostgreSQL required)")


@pytest.fixture
def engine():
    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    yield eng
    eng.dispose()


def _run(engine, fn, rev):
    with engine.begin() as conn:
        fn(alembic_config(conn), rev)


def test_upgrade_empty_database_matches_models(engine):
    _run(engine, command.upgrade, "head")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], diff
    _run(engine, command.downgrade, "base")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' "
                                 "AND table_name <> 'alembic_version'")).scalar() == 0


def test_legacy_single_club_data_is_migrated(engine):
    _run(engine, command.upgrade, "0001_legacy")
    with engine.begin() as c:
        c.execute(text("INSERT INTO users (id, email, full_name, role, region, hashed_password, is_active, created_at) "
                       "VALUES (1, 'sd@club.ma', 'SD', 'sporting_director', 'MA', 'x', true, now()), "
                       "(2, 'vs@club.ma', 'VS', 'video_scout', NULL, 'x', true, now())"))
        c.execute(text("INSERT INTO data_sources (id, name, source_type, is_fictional, created_at) "
                       "VALUES (1, 'Provider', 'api_import', false, now())"))
        c.execute(text("INSERT INTO players (id, full_name, nationality, primary_position, secondary_positions, "
                       "availability, estimated_fee_eur, salary_expectation_eur, agent_name, tactical_role, notes, "
                       "data_source_id, is_fictional, created_at, last_updated) VALUES (1, 'Legacy Player', "
                       "'Morocco', 'CB', '[]', 'available', 1500000, 200000, 'Agent X', 'Stopper', 'secret', 1, "
                       "false, now(), now())"))
        c.execute(text("INSERT INTO pipeline_entries (id, player_id, stage, priority, created_at, updated_at) "
                       "VALUES (1, 1, 'shortlisted', 'high', now(), now())"))
        c.execute(text("INSERT INTO pipeline_events (id, entry_id, to_stage, created_at) "
                       "VALUES (1, 1, 'identified', now())"))
        c.execute(text("INSERT INTO match_videos (id, player_id, home_team, away_team, video_url, license_type, "
                       "rights_holder, license_confirmed, is_full_match, created_at) "
                       "VALUES (1, 1, 'H', 'A', 'https://v', 'club_internal', 'Club', true, true, now())"))
        c.execute(text("INSERT INTO video_observations (id, video_id, timestamp_seconds, category, assessment, "
                       "created_at) VALUES (1, 1, 10, 'passing', 'positive', now())"))
        c.execute(text("INSERT INTO recruitment_budgets (id, season, transfer_budget_eur, wage_budget_eur, "
                       "updated_at) VALUES (1, '2026-27', 5000000, 1000000, now())"))
        c.execute(text("INSERT INTO audit_logs (id, action, created_at) VALUES (1, 'auth.login', now())"))

    _run(engine, command.upgrade, "head")
    with engine.connect() as c:
        org = c.execute(text("SELECT id, slug, is_demo FROM organizations")).one()
        assert org.slug == "legacy-organization" and org.is_demo is False
        roles = dict(c.execute(text("SELECT user_id, role FROM memberships WHERE organization_id = :o"),
                               {"o": org.id}).all())
        assert roles == {1: "sporting_director", 2: "video_scout"}
        a = c.execute(text("SELECT * FROM player_assessments")).one()
        assert (a.organization_id, a.estimated_fee, a.salary_expectation, a.agent_name, a.tactical_role,
                a.availability, a.notes) == (org.id, 1500000, 200000, "Agent X", "Stopper", "available", "secret")
        for t in ("players", "data_sources", "pipeline_entries", "pipeline_events", "match_videos",
                  "video_observations", "recruitment_budgets", "audit_logs"):
            assert c.execute(text(f"SELECT count(*) FROM {t} WHERE organization_id IS DISTINCT FROM :o"),
                             {"o": org.id}).scalar() == 0, t
        assert c.execute(text("SELECT transfer_budget FROM recruitment_budgets")).scalar() == 5000000
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
        assert diff == [], diff

    _run(engine, command.downgrade, "0001_legacy")
    with engine.connect() as c:
        p = c.execute(text("SELECT estimated_fee_eur, agent_name, availability FROM players")).one()
        assert tuple(p) == (1500000, "Agent X", "available")
        assert c.execute(text("SELECT role FROM users WHERE id = 1")).scalar() == "sporting_director"
        assert c.execute(text("SELECT transfer_budget_eur FROM recruitment_budgets")).scalar() == 5000000
