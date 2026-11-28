"""Stage 4: plans, subscription status, read-only enforcement, seat/player limits, feature
gating, platform operator console, billing interface."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Organization, Subscription, User
from app.security import hash_password
from app.subscriptions import GRACE_DAYS, effective_status
from conftest import PASSWORD, _sys, create_org

NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


def customer_org(client, slug, plan="club_pro", status="active", **sub):
    """A real (non-demo) customer organization with a subscription."""
    org = create_org(client, slug, slug.title())
    with _sys() as db:
        db.get(Organization, org["id"]).is_demo = False
        db.add(Subscription(organization_id=org["id"], plan=plan, status=status, billing_provider="manual", **sub))
        db.commit()
    return org


def set_sub(org_id, **kw):
    with _sys() as db:
        s = db.scalar(select(Subscription).where(Subscription.organization_id == org_id))
        for k, v in kw.items():
            setattr(s, k, v)
        db.commit()


def new_player(client, h, name="Limit Player"):
    return client.post("/api/players", headers=h, json={"full_name": name, "nationality": "Mali", "primary_position": "CM"})


# --------------------------------------------------------------------------- status logic (unit)
@pytest.mark.parametrize("status, trial, period, expected", [
    ("trialing", 5, None, "trialing"), ("trialing", -1, None, "expired"),
    ("active", None, 10, "active"), ("active", None, -3, "past_due"),
    ("active", None, -(GRACE_DAYS + 1), "expired"), ("past_due", None, -2, "past_due"),
    ("suspended", None, 30, "suspended"), ("canceled", None, None, "canceled"),
])
def test_effective_status(status, trial, period, expected):
    sub = SimpleNamespace(status=status, trial_ends_at=NOW() + timedelta(days=trial) if trial is not None else None,
                          current_period_end=NOW() + timedelta(days=period) if period is not None else None)
    assert effective_status(sub) == expected
    assert effective_status(None) == "none"


# --------------------------------------------------------------------------- read-only enforcement
def test_trial_then_expiry_makes_workspace_read_only(client):
    org = customer_org(client, "trial-club", status="trialing", trial_ends_at=NOW() + timedelta(days=10))
    h = org["H"]["head_of_scouting"]
    s = client.get("/api/subscription", headers=org["H"]["video_scout"]).json()
    assert s["effective_status"] == "trialing" and s["writable"] and s["trial_days_left"] in (9, 10)
    assert s["limits"]["seats"] == 15 and len(s["available_plans"]) == 3
    p = new_player(client, h).json()
    set_sub(org["id"], trial_ends_at=NOW() - timedelta(minutes=1))
    assert client.get("/api/subscription", headers=h).json()["effective_status"] == "expired"
    r = new_player(client, h, "Blocked")
    assert r.status_code == 402 and "read-only" in r.json()["detail"]
    assert client.patch(f"/api/players/{p['id']}", headers=h, json={"notes": "x"}).status_code == 402
    assert client.post("/api/pipeline", headers=h, json={"player_id": p["id"]}).status_code == 402
    # reading and exporting keep working
    assert client.get(f"/api/players/{p['id']}", headers=h).status_code == 200
    assert client.get("/api/dashboard", headers=org["H"]["sporting_director"]).status_code == 200
    assert client.get("/api/admin/export", headers=org["H"]["administrator"]).status_code == 200
    set_sub(org["id"], status="active", current_period_end=NOW() + timedelta(days=30))
    assert new_player(client, h, "Unblocked").status_code == 201


@pytest.mark.parametrize("status", ["suspended", "canceled", "expired"])
def test_inactive_statuses_are_read_only(client, status):
    org = customer_org(client, f"st-{status}", status=status)
    assert new_player(client, org["H"]["head_of_scouting"]).status_code == 402
    assert client.get("/api/players", headers=org["H"]["head_of_scouting"]).status_code == 200


def test_grace_period_after_missed_renewal(client):
    org = customer_org(client, "grace-club", current_period_end=NOW() - timedelta(days=3))
    h = org["H"]["head_of_scouting"]
    assert client.get("/api/subscription", headers=h).json()["effective_status"] == "past_due"
    assert new_player(client, h).status_code == 201
    set_sub(org["id"], current_period_end=NOW() - timedelta(days=GRACE_DAYS + 1))
    assert new_player(client, h, "Late").status_code == 402


def test_missing_subscription_fails_closed(client):
    org = create_org(client, "no-sub-club", "No Sub Club")
    with _sys() as db:
        db.get(Organization, org["id"]).is_demo = False
        db.commit()
    assert new_player(client, org["H"]["head_of_scouting"]).status_code == 402
    assert client.get("/api/subscription", headers=org["H"]["head_of_scouting"]).json()["effective_status"] == "none"


def test_demo_organizations_are_unlimited(client, H):
    s = client.get("/api/subscription", headers=H["sporting_director"]).json()
    assert s["plan"] == "demo" and s["writable"] and s["limits"]["seats"] is None


# --------------------------------------------------------------------------- limits
def test_seat_limit_counts_members_and_pending_invitations(client):
    org = customer_org(client, "seat-club", plan="scout")
    a = org["H"]["administrator"]
    used = client.get("/api/subscription", headers=a).json()["usage"]["seats_used"]
    assert used == 5  # five members on a 3-seat plan: over the limit
    inv = lambda e: client.post("/api/users/invitations", headers=a, json={"email": e, "role": "video_scout"})  # noqa: E731
    assert inv("one@seat.ma").status_code == 402
    set_sub(org["id"], seats_override=6)
    r = inv("one@seat.ma")
    assert r.status_code == 201
    assert inv("two@seat.ma").status_code == 402
    assert client.post("/api/users", headers=a, json={"email": "direct@seat.ma", "full_name": "Direct",
                                                       "role": "video_scout", "password": "Direct-pass-1"}).status_code == 402
    client.delete(f"/api/users/invitations/{r.json()['id']}", headers=a)  # revoking frees the seat
    assert inv("two@seat.ma").status_code == 201
    # reactivating a member also needs a free seat
    members = client.get("/api/users", headers=a).json()
    vs = next(m for m in members if m["role"] == "video_scout")
    assert client.patch(f"/api/users/{vs['id']}", headers=a, json={"is_active": False}).status_code == 200
    assert inv("three@seat.ma").status_code == 201
    assert client.patch(f"/api/users/{vs['id']}", headers=a, json={"is_active": True}).status_code == 402


def test_private_player_limit_api_and_import(client):
    org = customer_org(client, "player-cap", plan="scout", players_override=2)
    h = org["H"]["head_of_scouting"]
    assert new_player(client, h, "P1").status_code == 201
    assert new_player(client, h, "P2").status_code == 201
    r = new_player(client, h, "P3")
    assert r.status_code == 402 and "player limit" in r.json()["detail"]
    src = client.post("/api/data-sources", headers=h, json={"name": "cap feed", "source_type": "manual"}).json()
    csv = "full_name,nationality,primary_position\nP1,Mali,CM\nNew One,Mali,ST\n"
    res = client.post("/api/import/players", headers=h, files={"file": ("p.csv", csv, "text/csv")},
                      data={"data_source_id": str(src["id"])}).json()
    assert res["updated"] == 1 and res["created"] == 0 and "player limit" in res["errors"][0]["error"]


def test_feature_gating_api_import(client):
    scout = customer_org(client, "feat-scout", plan="scout")
    pro = customer_org(client, "feat-pro", plan="club_pro")
    for org, expected in ((scout, 402), (pro, 200)):
        h = org["H"]["head_of_scouting"]
        src = client.post("/api/data-sources", headers=h, json={"name": "provider feed", "source_type": "api_import"}).json()
        r = client.post("/api/import/json", headers=h, json={"data_source_id": src["id"], "players": []})
        assert r.status_code == expected, (org, r.text)


# --------------------------------------------------------------------------- platform operator
@pytest.fixture(scope="module")
def P(client):
    with _sys() as db:
        db.add(User(email="ops@platform.example", full_name="Platform Ops", is_platform_admin=True,
                    hashed_password=hash_password(PASSWORD)))
        db.commit()
    r = client.post("/api/auth/token", data={"username": "ops@platform.example", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["organization_id"] is None
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_platform_admin_has_no_tenant_data_access(client, P, H):
    assert client.get("/api/players", headers=P).status_code == 403
    assert client.get("/api/dashboard", headers=P).status_code == 403
    assert client.get("/api/platform/organizations", headers=H["administrator"]).status_code == 403  # org admin ≠ platform
    orgs = client.get("/api/platform/organizations", headers=P).json()
    demo = next(o for o in orgs if o["slug"] == "demo-fc")
    assert demo["subscription"]["usage"]["private_players"] >= 96
    body = str(orgs)
    assert "-Fict" not in body and "estimated_fee" not in body and "logo_data_url': 'data" not in body


def test_platform_onboarding_and_subscription_management(client, P, monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "customer")  # a customer org, not a demo org
    r = client.post("/api/platform/organizations", headers=P, json={
        "slug": "oasis-fc", "name": "Oasis FC", "country": "Tunisia", "currency": "tnd", "plan": "scout",
        "trial_days": 14, "admin_email": "boss@oasis.tn"})
    assert r.status_code == 201, r.text
    org = r.json()
    assert org["is_demo"] is False and org["subscription"]["effective_status"] == "trialing"
    assert org["subscription"]["plan"] == "scout" and org["currency"] == "TND"
    token = org["admin_invite_url"].rsplit("/", 1)[1]
    acc = client.post("/api/auth/invitations/accept", json={"token": token, "password": "Oasis-boss-2026",
                                                            "full_name": "Oasis Boss"}).json()
    ha = {"Authorization": f"Bearer {acc['access_token']}"}
    assert client.get("/api/auth/me", headers=ha).json()["role"] == "administrator"
    assert client.get("/api/subscription", headers=ha).json()["usage"]["active_members"] == 1
    assert client.post("/api/platform/organizations", headers=P, json={
        "slug": "oasis-fc", "name": "dup", "admin_email": "x@y.io"}).status_code == 409
    assert client.post("/api/platform/organizations", headers=P, json={
        "slug": "Bad Slug", "name": "x", "admin_email": "x@y.io"}).status_code == 422

    up = client.patch(f"/api/platform/organizations/{org['id']}/subscription", headers=P, json={
        "plan": "enterprise", "status": "active", "current_period_end": (NOW() + timedelta(days=365)).isoformat()}).json()
    assert up["subscription"]["plan"] == "enterprise" and up["subscription"]["limits"]["seats"] is None
    assert client.patch(f"/api/platform/organizations/{org['id']}/subscription", headers=P,
                        json={"status": "bogus"}).status_code == 422
    client.post(f"/api/platform/organizations/{org['id']}/suspend", headers=P)
    assert new_player(client, ha).status_code == 402
    client.post(f"/api/platform/organizations/{org['id']}/reactivate", headers=P)
    assert new_player(client, ha).status_code == 201

    plat = client.get("/api/platform/audit-logs", headers=P).json()
    assert {"platform.organization_create", "platform.subscription_update"} <= {e["action"] for e in plat}
    tenant = client.get("/api/admin/audit-logs?limit=1000", headers=ha).json()
    assert not any(e["action"].startswith("platform.") for e in tenant)

    client.post(f"/api/platform/organizations/{org['id']}/schedule-deletion", headers=P)
    assert client.get("/api/players", headers=ha).status_code == 403
    assert client.post(f"/api/platform/organizations/{org['id']}/purge", headers=P,
                       json={"confirm_slug": "nope"}).status_code == 422
    res = client.post(f"/api/platform/organizations/{org['id']}/purge", headers=P, json={"confirm_slug": "oasis-fc"})
    assert res.status_code == 200 and res.json()["accounts_deleted"] == 1
    assert all(o["slug"] != "oasis-fc" for o in client.get("/api/platform/organizations", headers=P).json())


def test_platform_org_in_demo_deployment_is_demo(client, P):
    r = client.post("/api/platform/organizations", headers=P, json={
        "slug": "demo-two", "name": "Demo Two", "admin_email": "d2@demo.example"})
    assert r.status_code == 201 and r.json()["is_demo"] is True


def test_billing_webhook_disabled_for_manual_provider(client):
    assert client.post("/api/billing/webhook/manual", content=b"{}").status_code == 404
    assert client.post("/api/billing/webhook/stripe", content=b"{}").status_code == 404
    from app.billing import get_provider
    assert get_provider().name == "manual" and get_provider().checkout_url(None, "scout") is None
    with pytest.raises(RuntimeError, match="not implemented"):
        get_provider("paddle")
