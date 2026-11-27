"""Test configuration.

By default tests run against a throwaway SQLite file for speed. Set TEST_DATABASE_URL to
run the same suite against PostgreSQL, e.g.
    TEST_DATABASE_URL=postgresql+psycopg://raja:raja@localhost:5432/raja_scout_test pytest
(the database is wiped at the start of the run).
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["SEED_SAMPLE_DATA"] = "true"
os.environ.setdefault("DEMO_PASSWORD", "RajaDemo2026!")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = os.environ["DEMO_PASSWORD"]
EMAILS = {
    "administrator": "admin@raja-scout.local",
    "sporting_director": "director@raja-scout.local",
    "head_of_scouting": "head.scouting@raja-scout.local",
    "data_analyst": "analyst@raja-scout.local",
    "video_scout": "video@raja-scout.local",
    "regional_scout": "scout.westafrica@raja-scout.local",
}


@pytest.fixture(scope="session")
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for role, email in EMAILS.items():
        r = client.post("/api/auth/token", data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        out[role] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return out


@pytest.fixture
def H(tokens):
    """Headers by role: H['sporting_director']."""
    return tokens


@pytest.fixture(scope="session")
def real_source(client, tokens):
    r = client.post("/api/data-sources", headers=tokens["head_of_scouting"], json={
        "name": "Test Licensed Provider", "source_type": "api_import", "license_notes": "Test contract"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def make_player(client, tokens, real_source):
    def _make(**kw):
        body = {"full_name": f"Test Player {uuid.uuid4().hex[:8]}", "nationality": "Morocco",
                "primary_position": "CM", "date_of_birth": "2001-03-04", "data_source_id": real_source["id"],
                "estimated_fee_eur": 500000, "salary_expectation_eur": 90000, **kw}
        r = client.post("/api/players", headers=tokens["head_of_scouting"], json=body)
        assert r.status_code == 201, r.text
        return r.json()
    return _make


def stat_line(source_id, **kw):
    base = {"season": "2025-26", "data_source_id": source_id, "appearances": 25, "starts": 22, "minutes": 1980,
            "team_matches": 30, "passes_attempted": 1500, "passes_completed": 1290, "progressive_passes": 110,
            "interceptions": 30, "defensive_duels": 150, "defensive_duels_won": 90}
    base.update(kw)
    return base
