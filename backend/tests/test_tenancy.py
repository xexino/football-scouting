"""Cross-tenant isolation. Organization A = demo org (fixtures H), organization B = "Rival FC".

Every test asserts that B can neither read nor modify A's private data, through any route,
and that shared reference data is visible to both but modifiable by neither."""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import (
    DataSource,
    League,
    MatchVideo,
    Membership,
    Organization,
    Player,
    PlayerSeasonStats,
    User,
    VideoObservation,
)
from app.security import create_access_token, hash_password
from app.tenancy import SYSTEM, TenantContextMissing, TenantViolation, set_tenant
from conftest import B_ROLES, PASSWORD, _sys, stat_line

@pytest.fixture(scope="session")
def shared(client):
    """Shared reference data created by the platform (SYSTEM context)."""
    with _sys() as db:
        src = DataSource(name="Platform reference feed", source_type="api_import", license_notes="Redistributable")
        lg = League(name="Shared League", country="Morocco", strength_coefficient=1.0, coefficient_source="test")
        db.add_all([src, lg])
        db.flush()
        p = Player(full_name="Shared Reference Player", nationality="Morocco", primary_position="CB",
                   date_of_birth=None, data_source_id=src.id)
        db.add(p)
        db.flush()
        db.add(PlayerSeasonStats(player_id=p.id, season="2025-26", league_id=lg.id, data_source_id=src.id,
                                 minutes=1800, interceptions=20))
        db.commit()
        return {"player_id": p.id, "source_id": src.id, "league_id": lg.id}


def ids(resp):
    return {x["id"] for x in resp.json()["items"]} if "items" in resp.json() else {x["id"] for x in resp.json()}


# --------------------------------------------------------------------------- private players
def test_private_player_invisible_to_other_org(client, H, B, make_player, real_source):
    p = make_player(full_name="Secret Target " + uuid.uuid4().hex[:6])
    pid = p["id"]
    hb = B["H"]["head_of_scouting"]
    assert client.get(f"/api/players/{pid}", headers=hb).status_code == 404
    assert client.patch(f"/api/players/{pid}", headers=hb, json={"full_name": "x"}).status_code == 404
    assert client.delete(f"/api/players/{pid}", headers=hb).status_code == 404
    assert client.get(f"/api/players/{pid}/stats", headers=hb).status_code == 404
    assert client.get(f"/api/players/{pid}/analytics", headers=hb).status_code == 404
    assert client.post(f"/api/players/{pid}/stats", headers=B["H"]["data_analyst"],
                       json=stat_line(B["source"]["id"])).status_code == 404
    assert pid not in ids(client.get("/api/players", params={"q": "Secret Target", "page_size": 200}, headers=hb))
    assert "Secret Target" not in client.get("/api/players/export.csv", headers=hb).text
    assert client.post("/api/compare", headers=hb, json={"player_ids": [pid, pid + 100000]}).status_code == 404
    assert client.post("/api/pipeline", headers=hb, json={"player_id": pid}).status_code == 404
    assert client.post("/api/reports/generate", headers=hb, json={"player_id": pid}).status_code == 404


def test_other_org_sees_none_of_demo_data(client, B):
    hb = B["H"]["sporting_director"]
    assert all(not p["is_fictional"] for p in client.get("/api/players?page_size=200", headers=hb).json()["items"])
    d = client.get("/api/dashboard", headers=hb).json()
    assert d["players"]["fictional"] == 0 and d["players"]["own"] == 0
    assert sum(d["pipeline"]["by_stage"].values()) == 0
    assert d["activity"]["match_reports_total"] == 0 and d["activity"]["per_scout"] == []
    assert d["budget"]["transfer_budget"] is None and d["budget"]["currency"] == "DZD"
    assert client.get("/api/videos", headers=hb).json() == []
    assert client.get("/api/match-reports", headers=hb).json() == []
    assert client.get("/api/reports", headers=hb).json() == []
    assert client.get("/api/budgets", headers=hb).json() == []
    assert client.get("/api/pipeline/events", headers=hb).json() == []
    names = {s["name"] for s in client.get("/api/data-sources", headers=hb).json()}
    assert "FICTIONAL SAMPLE DATA" not in names and "Test Licensed Provider" not in names
    assert all("fictional" not in lg["name"].lower() for lg in client.get("/api/leagues", headers=hb).json())


# --------------------------------------------------------------------------- shared reference data
def test_shared_player_visible_with_private_assessments(client, H, B, shared):
    pid = shared["player_id"]
    ha, hb = H["sporting_director"], B["H"]["sporting_director"]
    a = client.get(f"/api/players/{pid}", headers=ha).json()
    b = client.get(f"/api/players/{pid}", headers=hb).json()
    assert a["scope"] == b["scope"] == "shared" and not a["editable_identity"]
    # each organization keeps its own private valuation
    assert client.patch(f"/api/players/{pid}", headers=ha, json={"estimated_fee": 1_000_000, "notes": "A secret"}).status_code == 200
    assert client.patch(f"/api/players/{pid}", headers=hb, json={"estimated_fee": 42}).status_code == 200
    a = client.get(f"/api/players/{pid}", headers=ha).json()
    b = client.get(f"/api/players/{pid}", headers=hb).json()
    assert a["estimated_fee"] == 1_000_000 and a["notes"] == "A secret" and a["currency"] == "EUR"
    assert b["estimated_fee"] == 42 and b["notes"] is None and b["currency"] == "DZD"
    # neither can change shared identity or delete it
    assert client.patch(f"/api/players/{pid}", headers=hb, json={"full_name": "Hacked"}).status_code == 403
    assert client.delete(f"/api/players/{pid}", headers=B["H"]["head_of_scouting"]).status_code == 403
    assert client.get(f"/api/players/{pid}", headers=ha).json()["full_name"] == "Shared Reference Player"
    # both can track the same shared player in their own pipelines
    assert client.post("/api/pipeline", headers=H["head_of_scouting"], json={"player_id": pid}).status_code == 201
    eb = client.post("/api/pipeline", headers=B["H"]["head_of_scouting"], json={"player_id": pid})
    assert eb.status_code == 201
    assert client.get(f"/api/pipeline/{eb.json()['id']}", headers=H["head_of_scouting"]).status_code == 404


def test_imported_stats_stay_private(client, H, B, shared, real_source):
    pid = shared["player_id"]
    before_b = client.get(f"/api/players/{pid}/stats", headers=B["H"]["data_analyst"]).json()
    r = client.post(f"/api/players/{pid}/stats", headers=H["data_analyst"],
                    json=stat_line(real_source["id"], season="2024-25"))
    assert r.status_code == 201
    a_stats = client.get(f"/api/players/{pid}/stats", headers=H["data_analyst"]).json()
    b_stats = client.get(f"/api/players/{pid}/stats", headers=B["H"]["data_analyst"]).json()
    assert len(a_stats) == len(before_b) + 1 and b_stats == before_b
    # B cannot record stats under A's source, nor delete A's or shared rows
    assert client.post(f"/api/players/{pid}/stats", headers=B["H"]["data_analyst"],
                       json=stat_line(real_source["id"])).status_code == 422
    assert client.delete(f"/api/players/{pid}/stats/{r.json()['id']}", headers=B["H"]["data_analyst"]).status_code == 404
    shared_row = next(s for s in b_stats if s["season"] == "2025-26")
    assert client.delete(f"/api/players/{pid}/stats/{shared_row['id']}", headers=B["H"]["data_analyst"]).status_code == 403
    assert client.get("/api/players", headers=B["H"]["data_analyst"], params={"q": "Shared Reference"}).json()["total"] == 1


def test_percentile_pools_exclude_other_org_data(client, H, B, make_player, real_source, shared):
    before = client.get(f"/api/players/{shared['player_id']}/analytics", headers=B["H"]["data_analyst"]).json()
    for _ in range(6):  # A adds six private CBs with stats
        p = make_player(primary_position="CB")
        client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"], json=stat_line(real_source["id"]))
    after = client.get(f"/api/players/{shared['player_id']}/analytics", headers=B["H"]["data_analyst"]).json()
    assert after["pool"]["size"] == before["pool"]["size"]
    a_view = client.get(f"/api/players/{shared['player_id']}/analytics", headers=H["data_analyst"]).json()
    assert a_view["pool"]["size"] > after["pool"]["size"]


# --------------------------------------------------------------------------- scouting work
def test_video_reports_pipeline_isolation(client, H, B, make_player):
    p = make_player()
    v = client.post("/api/videos", headers=H["video_scout"], json={
        "player_id": p["id"], "home_team": "A", "away_team": "B", "video_url": "https://licensed.example.com/1",
        "license_type": "licensed_full_match", "rights_holder": "Provider", "license_confirmed": True,
        "is_full_match": True}).json()
    mr = client.post("/api/match-reports", headers=H["video_scout"], json={
        "player_id": p["id"], "video_id": v["id"], "observation_type": "video_full_match"}).json()
    rep = client.post("/api/reports/generate", headers=H["head_of_scouting"], json={"player_id": p["id"]}).json()
    e = client.post("/api/pipeline", headers=H["head_of_scouting"], json={"player_id": p["id"]}).json()
    hb = B["H"]["head_of_scouting"]
    assert client.get(f"/api/videos/{v['id']}", headers=hb).status_code == 404
    assert client.post(f"/api/videos/{v['id']}/observations", headers=hb,
                       json={"timestamp_seconds": 5, "category": "passing"}).status_code == 404
    assert client.delete(f"/api/videos/{v['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/match-reports/{mr['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/reports/{rep['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/reports/{rep['id']}/export.md", headers=hb).status_code == 404
    assert client.patch(f"/api/reports/{rep['id']}", headers=hb, json={"risk_level": "low"}).status_code == 404
    assert client.delete(f"/api/reports/{rep['id']}", headers=hb).status_code == 404
    assert client.get(f"/api/pipeline/{e['id']}", headers=hb).status_code == 404
    assert client.post(f"/api/pipeline/{e['id']}/move", headers=hb,
                       json={"to_stage": "rejected", "note": "sabotage"}).status_code == 404
    assert client.patch(f"/api/pipeline/{e['id']}", headers=hb, json={"priority": "low"}).status_code == 404
    assert client.get(f"/api/pipeline/player/{p['id']}", headers=hb).json() is None
    # B's own player cannot be attached to A's video
    bp = client.post("/api/players", headers=hb, json={"full_name": "B Own", "nationality": "Algeria",
                                                       "primary_position": "W"}).json()
    assert client.post("/api/match-reports", headers=hb, json={
        "player_id": bp["id"], "video_id": v["id"], "observation_type": "video_full_match"}).status_code == 422


def test_audit_budget_member_isolation(client, H, B):
    assert client.put("/api/budgets", headers=B["H"]["sporting_director"],
                      json={"season": "2026-27", "transfer_budget": 900_000}).status_code == 200  # same season as A
    assert [b["transfer_budget"] for b in client.get("/api/budgets", headers=H["sporting_director"]).json()] == [6_000_000]
    b_logs = client.get("/api/admin/audit-logs?limit=1000", headers=B["H"]["administrator"]).json()
    assert b_logs and all(not (l["user_email"] or "").endswith("raja-scout.local") for l in b_logs)
    a_logs = client.get("/api/admin/audit-logs?limit=1000", headers=H["administrator"]).json()
    assert all(not (l["user_email"] or "").startswith("rival.") for l in a_logs)
    b_members = {m["email"] for m in client.get("/api/users", headers=B["H"]["administrator"]).json()}
    assert b_members == {f"rival.{r}@example.com" for r in B_ROLES}
    a_user_id = client.get("/api/auth/me", headers=H["video_scout"]).json()["id"]
    assert client.patch(f"/api/users/{a_user_id}", headers=B["H"]["administrator"],
                        json={"role": "data_analyst"}).status_code == 404
    assert all(u["full_name"].startswith("Rival FC") for u in client.get("/api/users/directory", headers=B["H"]["video_scout"]).json())
    exp = client.get("/api/admin/export", headers=B["H"]["administrator"]).json()
    assert exp["organization"]["slug"] == "rival"
    assert all(r["organization_id"] in (None, B["id"]) for t in exp["tables"].values() for r in t if "organization_id" in r)


def test_shared_account_cannot_be_hijacked(client, H, B):
    """B adds an existing A user (e.g. a consultant). B must not be able to set their password."""
    email = "consultant@example.com"
    r = client.post("/api/users", headers=H["administrator"], json={
        "email": email, "full_name": "Consultant", "role": "data_analyst", "password": "Consult4nt-pass"})
    assert r.status_code == 201
    # B cannot attach the existing account directly (no consent, would disclose PII) ...
    r = client.post("/api/users", headers=B["H"]["administrator"], json={
        "email": email, "full_name": "ignored", "role": "video_scout", "password": "Attack3r-pass!"})
    assert r.status_code == 409 and "Consultant" not in r.text
    # ... only via an invitation that the owner accepts with their own password
    inv = client.post("/api/users/invitations", headers=B["H"]["administrator"],
                      json={"email": email, "role": "video_scout"}).json()
    tok_inv = inv["invite_url"].rsplit("/", 1)[1]
    assert client.post("/api/auth/invitations/accept", json={"token": tok_inv, "password": "Attack3r-pass!"}).status_code == 401
    r = client.post("/api/auth/invitations/accept", json={"token": tok_inv, "password": "Consult4nt-pass"})
    assert r.status_code == 200
    uid = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()["id"]

    assert client.patch(f"/api/users/{uid}", headers=B["H"]["administrator"], json={"password": "Attack3r-pass!"}).status_code == 403
    assert client.post("/api/auth/token", data={"username": email, "password": "Attack3r-pass!"}).status_code == 401
    tok = client.post("/api/auth/token", data={"username": email, "password": "Consult4nt-pass"}).json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert {o["id"] for o in me["organizations"]} == {1, B["id"]}
    sw = client.post("/api/auth/switch-organization", headers={"Authorization": f"Bearer {tok}"},
                     json={"organization_id": B["id"]})
    assert sw.status_code == 200
    hb = {"Authorization": f"Bearer {sw.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=hb).json()["role"] == "video_scout"
    assert client.post("/api/auth/switch-organization", headers=hb, json={"organization_id": 999999}).status_code == 403


# --------------------------------------------------------------------------- tokens
def test_forged_org_claim_rejected(client, B):
    with _sys() as db:
        user = db.scalar(select(User).where(User.email == "rival.head_of_scouting@example.com"))
        forged = create_access_token(user, 1)  # validly signed, but user is not a member of org 1
        no_org = create_access_token(user, None)
    assert client.get("/api/players", headers={"Authorization": f"Bearer {forged}"}).status_code == 403
    assert client.get("/api/players", headers={"Authorization": f"Bearer {no_org}"}).status_code == 403


def test_password_change_revokes_tokens(client, B):
    with _sys() as db:
        org = db.get(Organization, B["id"])
        u = User(email="rotate@example.com", full_name="Rotate", hashed_password=hash_password("Rotate-pass-1"))
        db.add(u)
        db.flush()
        db.add(Membership(user_id=u.id, organization_id=org.id, role="video_scout"))
        db.commit()
    t1 = client.post("/api/auth/token", data={"username": "rotate@example.com", "password": "Rotate-pass-1"}).json()["access_token"]
    h1 = {"Authorization": f"Bearer {t1}"}
    r = client.post("/api/auth/change-password", headers=h1, json={"current_password": "Rotate-pass-1",
                                                                     "new_password": "Rotate-pass-2"})
    assert r.status_code == 200
    assert client.get("/api/players", headers=h1).status_code == 401
    assert client.get("/api/players", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


# --------------------------------------------------------------------------- ORM / database layer
def test_queries_fail_closed_without_tenant(client):
    with SessionLocal() as db:
        with pytest.raises(TenantContextMissing):
            db.scalars(select(Player)).all()
        with pytest.raises(TenantContextMissing):
            db.get(MatchVideo, 1)


def test_write_guard_blocks_cross_tenant_and_shared_writes(client, B, shared):
    with SessionLocal() as db:
        set_tenant(db, B["id"])
        p = db.get(Player, shared["player_id"])
        p.full_name = "tampered"
        with pytest.raises(TenantViolation):
            db.flush()
        db.rollback()
        db.add(Player(full_name="smuggled", nationality="X", primary_position="ST", organization_id=1))
        with pytest.raises(TenantViolation):
            db.flush()
        db.rollback()
        assert db.get(MatchVideo, 1) is None  # demo org video invisible


def test_composite_fk_blocks_cross_org_child_rows(client, B):
    with _sys() as db:
        video = db.scalar(select(MatchVideo).where(MatchVideo.organization_id == 1))
        assert video is not None
        db.add(VideoObservation(video_id=video.id, organization_id=B["id"], timestamp_seconds=1, category="passing"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_import_matching_shared_player_updates_only_private_assessment(client, H, B, shared):
    csv = "full_name,nationality,primary_position,height_cm,estimated_fee,availability\n" \
          "Shared Reference Player,Morocco,ST,150,777,available\n"
    r = client.post("/api/import/players", headers=B["H"]["head_of_scouting"],
                    files={"file": ("p.csv", csv, "text/csv")}, data={"data_source_id": str(B["source"]["id"])})
    assert r.status_code == 200 and r.json()["updated"] == 1, r.text
    b = client.get(f"/api/players/{shared['player_id']}", headers=B["H"]["sporting_director"]).json()
    a = client.get(f"/api/players/{shared['player_id']}", headers=H["sporting_director"]).json()
    assert b["estimated_fee"] == 777 and b["availability"] == "available"
    assert b["primary_position"] == "CB" and b["height_cm"] is None  # shared identity untouched
    assert a["estimated_fee"] != 777
