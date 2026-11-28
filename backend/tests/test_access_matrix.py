"""Route-level access matrix, generated from the application's own route table."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Organization, Subscription, User
from app.security import hash_password
from conftest import PASSWORD, _sys, create_org
from test_isolation_crawler import TENANT_ROUTES, _deps, _flatten

ALL = sorted({(m, r.path, frozenset(_deps(r))) for r in _flatten(app.routes) for m in r.methods}, key=lambda x: x[:2])
PLATFORM = [(m, p) for m, p, d in ALL if any("require_platform_admin" in x for x in d)]
USER = [(m, p) for m, p, d in ALL if any("get_current_user" in x for x in d) and not any("get_ctx" in x for x in d)
        and not any("require_platform_admin" in x for x in d)]


def _url(path):
    return re.sub(r"{\w+}", "1", path)


@pytest.fixture(scope="module")
def raw():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def ops(client):
    with _sys() as db:
        db.add(User(email="matrix.ops@platform.example", full_name="Matrix Ops", is_platform_admin=True,
                    hashed_password=hash_password(PASSWORD)))
        db.commit()
    t = client.post("/api/auth/token", data={"username": "matrix.ops@platform.example", "password": PASSWORD})
    return {"Authorization": f"Bearer {t.json()['access_token']}"}


def test_anonymous_requests_rejected(raw):
    bad = []
    for m, p in TENANT_ROUTES + PLATFORM + USER:
        r = raw.request(m, _url(p), json={})
        if r.status_code != 401:
            bad.append((m, p, r.status_code))
    assert not bad, bad
    assert len(TENANT_ROUTES) + len(PLATFORM) + len(USER) == 78


def test_platform_routes_reject_organization_admins(raw, H):
    bad = [(m, p, r.status_code) for m, p in PLATFORM
           if (r := raw.request(m, _url(p), headers=H["administrator"], json={})).status_code != 403]
    assert not bad, bad


def test_tenant_routes_reject_platform_operator_without_membership(raw, ops):
    bad = [(m, p, r.status_code) for m, p in TENANT_ROUTES
           if (r := raw.request(m, _url(p), headers=ops, json={})).status_code != 403]
    assert not bad, bad


def test_every_write_route_is_read_only_when_subscription_expired(raw, client):
    org = create_org(client, "matrix-expired", "Matrix Expired")
    with _sys() as db:
        db.get(Organization, org["id"]).is_demo = False
        db.add(Subscription(organization_id=org["id"], plan="enterprise", status="trialing", billing_provider="manual",
                            trial_ends_at=datetime.now(timezone.utc) - timedelta(days=1)))
        db.commit()
    h = org["H"]["administrator"]
    writes = [(m, p) for m, p in TENANT_ROUTES if m not in ("GET", "HEAD", "OPTIONS")]
    bad = [(m, p, r.status_code) for m, p in writes if (r := raw.request(m, _url(p), headers=h, json={})).status_code != 402]
    assert not bad, bad
    reads = [(m, p) for m, p in TENANT_ROUTES if m == "GET" and "{" not in p]
    assert all(raw.get(p, headers=h).status_code == 200 for _, p in reads)
    assert len(writes) == 34  # update deliberately when adding write routes
