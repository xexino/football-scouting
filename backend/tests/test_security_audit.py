"""Security audit findings (one test per finding). Written before the fixes: each failing
test demonstrated a real weakness; they now guard against regressions.
See docs/saas/07_SECURITY_AUDIT.md for severities."""
import pytest
from sqlalchemy import select

from app.config import Settings, settings
from app.models import AuditLog, Club
from conftest import PASSWORD, _sys, create_org


@pytest.fixture(scope="module")
def X(client):
    return create_org(client, "audit-x", "Audit X FC")


@pytest.fixture(scope="module")
def Y(client):
    return create_org(client, "audit-y", "Audit Y FC")


# F1 HIGH — cross-tenant account enumeration / non-consensual membership via direct member creation
def test_f1_direct_add_of_existing_account_is_refused_and_leaks_nothing(client, X):
    r = client.post("/api/users", headers=X["H"]["administrator"], json={
        "email": "director@raja-scout.local", "full_name": "whoever", "role": "video_scout", "password": "Irrelevant-1"})
    assert r.status_code == 409
    assert "Demo Sporting Director" not in r.text          # no PII of another organization's user
    assert "invitation" in r.json()["detail"].lower()      # must go through an invitation (owner consents)


# F2 HIGH — invitation acceptance was an unthrottled password-guessing oracle for existing accounts
def test_f2_invitation_accept_is_throttled(client, X):
    r = client.post("/api/users/invitations", headers=X["H"]["administrator"],
                    json={"email": "head.scouting@raja-scout.local", "role": "video_scout"})
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    codes = [client.post("/api/auth/invitations/accept", json={"token": token, "password": f"guess-{i}-xx"}).status_code
             for i in range(settings.max_login_attempts + 1)]
    assert codes[-1] == 429, codes
    # the legitimate owner's normal login is protected by the same account counter
    from app.models import LoginAttempt
    from sqlalchemy import delete
    with _sys() as db:
        db.execute(delete(LoginAttempt).where(LoginAttempt.key == "account:head.scouting@raja-scout.local"))
        db.commit()


# F3 MEDIUM — pipeline could be assigned to a user of another organization (leaks their name)
def test_f3_assigned_scout_must_be_member(client, X, Y):
    y_user = client.get("/api/auth/me", headers=Y["H"]["video_scout"]).json()
    p = client.post("/api/players", headers=X["H"]["head_of_scouting"], json={
        "full_name": "F3 Player", "nationality": "Mali", "primary_position": "ST"}).json()
    r = client.post("/api/pipeline", headers=X["H"]["head_of_scouting"],
                    json={"player_id": p["id"], "assigned_scout_id": y_user["id"]})
    assert r.status_code == 422 and y_user["full_name"] not in r.text
    e = client.post("/api/pipeline", headers=X["H"]["head_of_scouting"], json={"player_id": p["id"]}).json()
    r = client.patch(f"/api/pipeline/{e['id']}", headers=X["H"]["head_of_scouting"], json={"assigned_scout_id": y_user["id"]})
    assert r.status_code == 422 and y_user["full_name"] not in r.text


# F4 MEDIUM — player update accepted references to another organization's club / data source
def test_f4_player_update_validates_references(client, X, Y):
    yclub = client.post("/api/clubs", headers=Y["H"]["head_of_scouting"], json={"name": "Y Secret Club", "country": "MA"}).json()
    ysrc = client.post("/api/data-sources", headers=Y["H"]["head_of_scouting"],
                       json={"name": "Y secret source", "source_type": "manual"}).json()
    p = client.post("/api/players", headers=X["H"]["head_of_scouting"], json={
        "full_name": "F4 Player", "nationality": "Mali", "primary_position": "ST"}).json()
    assert client.patch(f"/api/players/{p['id']}", headers=X["H"]["head_of_scouting"],
                        json={"current_club_id": yclub["id"]}).status_code == 422
    assert client.patch(f"/api/players/{p['id']}", headers=X["H"]["head_of_scouting"],
                        json={"data_source_id": ysrc["id"]}).status_code == 422
    assert client.patch(f"/api/players/{p['id']}", headers=X["H"]["head_of_scouting"],
                        json={"current_club_id": 99999999}).status_code == 422  # no 500 / FK oracle
    with _sys() as db:
        assert db.get(Club, yclub["id"]).organization_id == Y["id"]


# F5 MEDIUM — organization export bulk-exported shared (platform-licensed) reference data
def test_f5_export_contains_only_own_rows(client, X):
    from app.models import DataSource, Player, PlayerSeasonStats
    with _sys() as db:  # shared, platform-licensed reference data visible to every organization
        src = DataSource(name="F5 licensed feed", source_type="api_import")
        db.add(src)
        db.flush()
        p = Player(full_name="F5 Shared", nationality="Morocco", primary_position="CB", data_source_id=src.id)
        db.add(p)
        db.flush()
        db.add(PlayerSeasonStats(player_id=p.id, season="2025-26", data_source_id=src.id, minutes=900))
        db.commit()
    exp = client.get("/api/admin/export", headers=X["H"]["administrator"]).json()
    rows = [r for t in exp["tables"].values() for r in t if "organization_id" in r]
    assert rows and all(r["organization_id"] == X["id"] for r in rows)


# F6 MEDIUM — CSV export allowed spreadsheet formula injection
def test_f6_csv_export_neutralises_formulas(client, X):
    client.post("/api/players", headers=X["H"]["head_of_scouting"], json={
        "full_name": '=HYPERLINK("http://evil.example","x")', "nationality": "+1", "primary_position": "ST"})
    text = client.get("/api/players/export.csv", headers=X["H"]["head_of_scouting"]).text
    assert ',=HYPERLINK' not in text and ",'=HYPERLINK" in text.replace('"', "")
    assert ",+1," not in text


# F7 MEDIUM — client-supplied X-Forwarded-For was trusted (audit IP spoofing / per-IP throttle bypass)
def test_f7_forwarded_for_not_trusted_by_default(client, X):
    client.post("/api/auth/token", headers={"X-Forwarded-For": "6.6.6.6"},
                data={"username": "audit-x.video_scout@example.com", "password": PASSWORD})
    with _sys() as db:
        last = db.scalars(select(AuditLog).where(AuditLog.action == "auth.login")
                          .order_by(AuditLog.id.desc())).first()
    assert last.ip_address != "6.6.6.6"


def test_f7_trusted_proxy_hops(monkeypatch):
    from types import SimpleNamespace

    from app.netutil import client_ip
    req = SimpleNamespace(headers={"x-forwarded-for": "6.6.6.6, 41.250.1.2"}, client=SimpleNamespace(host="10.0.0.5"))
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(req) == "10.0.0.5"
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert client_ip(req) == "41.250.1.2"           # the address appended by our own proxy, not the spoofed one


# F8 MEDIUM — no Content-Security-Policy; inline event handlers in the SPA
def test_f8_content_security_policy(client):
    csp = client.get("/").headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "unsafe-eval" not in csp
    js = client.get("/static/app.js").text
    assert 'onclick="' not in js and "onerror=" not in js


# F9 MEDIUM — CLI create-org created customer orgs inside a demo deployment (outage at next restart)
def test_f9_cli_create_org_respects_deployment_mode(client):
    from app import cli
    from app.models import Organization
    cli.create_org("cli-demo-check", "CLI Demo Check")
    with _sys() as db:
        org = db.scalar(select(Organization).where(Organization.slug == "cli-demo-check"))
        assert org.is_demo is True  # tests run with DEPLOYMENT_MODE=demo
    from app.main import check_environment_separation
    from conftest import demo_only_database
    with demo_only_database():
        check_environment_separation()
    with pytest.raises(SystemExit):
        cli.create_org("Bad Slug!", "x")


# F11 LOW — bcrypt 72-byte limit caused HTTP 500
def test_f11_overlong_passwords_rejected_cleanly(client, X):
    long_pw = "Aa1" + "x" * 100
    assert client.post("/api/auth/token", data={"username": "audit-x.video_scout@example.com",
                                                "password": long_pw}).status_code == 401
    r = client.post("/api/auth/change-password", headers=X["H"]["video_scout"],
                    json={"current_password": PASSWORD, "new_password": long_pw})
    assert r.status_code == 422


# F12 LOW — older password reset links stayed valid after a newer one / after use
def test_f12_reset_links_superseded(client):
    Z = create_org(client, "audit-z", "Audit Z FC")
    uid = client.get("/api/auth/me", headers=Z["H"]["video_scout"]).json()["id"]
    l1 = client.post(f"/api/users/{uid}/password-reset-link", headers=Z["H"]["administrator"]).json()["reset_url"]
    l2 = client.post(f"/api/users/{uid}/password-reset-link", headers=Z["H"]["administrator"]).json()["reset_url"]
    assert client.post("/api/auth/password-reset", json={"token": l1.rsplit("/", 1)[1],
                                                         "new_password": "Superseded-1x"}).status_code == 410
    assert client.post("/api/auth/password-reset", json={"token": l2.rsplit("/", 1)[1],
                                                         "new_password": "Current-pass-1"}).status_code == 200


# F13/F14 LOW — production config: wildcard CORS refused, API docs hidden by default
def test_f13_f14_production_hardening(monkeypatch):
    monkeypatch.setenv("RAJA_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.delenv("EXPOSE_API_DOCS", raising=False)
    assert Settings().expose_api_docs is False
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="CORS"):
        Settings()


# F18 MEDIUM — demo seeder re-ran on an upgraded database and created a duplicate demo organization
def test_f18_seed_never_runs_on_a_non_empty_database(client):
    from sqlalchemy import func

    from app.models import Organization
    from app.seed import seed
    with _sys() as db:
        n = db.scalar(select(func.count()).select_from(Organization))
        seed(db)
        assert db.scalar(select(func.count()).select_from(Organization)) == n


# Verification (no finding): token handling
def test_token_forgery_and_expiry_rejected(client, X):
    import base64
    import json
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt
    uid = client.get("/api/auth/me", headers=X["H"]["administrator"]).json()["id"]
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': str(uid), 'org': X['id'], 'ver': 0})}."
    wrong_key = pyjwt.encode({"sub": str(uid), "org": X["id"], "ver": 0,
                              "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "x" * 48, algorithm="HS256")
    expired = pyjwt.encode({"sub": str(uid), "org": X["id"], "ver": 0,
                            "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, settings.secret_key, algorithm="HS256")
    for tok in (unsigned, wrong_key, expired, "garbage", ""):
        assert client.get("/api/players", headers={"Authorization": f"Bearer {tok}"}).status_code == 401, tok[:20]
    # a validly signed token for an organization the user does not belong to
    other = pyjwt.encode({"sub": str(uid), "org": 1, "ver": 0,
                          "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, settings.secret_key, algorithm="HS256")
    assert client.get("/api/players", headers={"Authorization": f"Bearer {other}"}).status_code == 403
