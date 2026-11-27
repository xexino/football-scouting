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
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    with TestClient(app) as c:  # startup runs migrations (PostgreSQL) and seeds the demo org
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
                "estimated_fee": 500000, "salary_expectation": 90000, **kw}
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


# --------------------------------------------------------------------------- second organization
from app.database import SessionLocal  # noqa: E402
from app.models import Membership, Organization, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.tenancy import SYSTEM, set_tenant  # noqa: E402

B_ROLES = ["administrator", "sporting_director", "head_of_scouting", "data_analyst", "video_scout"]


def _sys():
    db = SessionLocal()
    set_tenant(db, SYSTEM)
    return db


def create_org(client, slug: str, name: str, roles=B_ROLES, currency: str = "EUR", country: str = "Morocco"):
    """Create an organization with one member per role; returns {"id", "H": headers by role}."""
    with _sys() as db:
        org = Organization(slug=slug, name=name, country=country, currency=currency, settings={})
        db.add(org)
        db.flush()
        for role in roles:
            u = User(email=f"{slug}.{role}@example.com", full_name=f"{name} {role}", hashed_password=hash_password(PASSWORD))
            db.add(u)
            db.flush()
            db.add(Membership(user_id=u.id, organization_id=org.id, role=role))
        db.commit()
        org_id = org.id
    H = {}
    for role in roles:
        r = client.post("/api/auth/token", data={"username": f"{slug}.{role}@example.com", "password": PASSWORD})
        assert r.status_code == 200 and r.json()["organization_id"] == org_id, r.text
        H[role] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return {"id": org_id, "H": H}


@pytest.fixture(scope="session")
def B(client):
    """Second organization ("Rival FC") used by the isolation tests."""
    org = create_org(client, "rival", "Rival FC", currency="DZD", country="Algeria")
    org["source"] = client.post("/api/data-sources", headers=org["H"]["head_of_scouting"], json={
        "name": "Rival licensed feed", "source_type": "api_import", "license_notes": "Rival contract"}).json()
    return org
