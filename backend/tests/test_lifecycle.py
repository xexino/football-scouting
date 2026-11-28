"""Stage 3: tenant export and two-step deletion."""
import pytest
from sqlalchemy import func, select

from app.lifecycle import purge_organization, schedule_deletion, tenant_row_counts
from app.models import AuditLog, Membership, Organization, Player, User
from conftest import PASSWORD, _sys, create_org, stat_line


def test_two_step_deletion_removes_everything_and_only_that(client, H):
    E = create_org(client, "ephemeral", "Ephemeral FC")
    h = E["H"]["head_of_scouting"]
    src = client.post("/api/data-sources", headers=h, json={"name": "E feed", "source_type": "manual"}).json()
    p = client.post("/api/players", headers=h, json={"full_name": "E Player", "nationality": "Ghana",
                                                       "primary_position": "W", "estimated_fee": 5,
                                                       "data_source_id": src["id"]}).json()
    client.post(f"/api/players/{p['id']}/stats", headers=E["H"]["data_analyst"], json=stat_line(src["id"]))
    v = client.post("/api/videos", headers=E["H"]["video_scout"], json={
        "player_id": p["id"], "home_team": "A", "away_team": "B", "video_url": "https://licensed.example.com/e",
        "license_type": "club_internal", "rights_holder": "Ephemeral FC", "license_confirmed": True}).json()
    client.post(f"/api/videos/{v['id']}/observations", headers=E["H"]["video_scout"],
                json={"timestamp_seconds": 5, "category": "passing"})
    client.post("/api/match-reports", headers=E["H"]["video_scout"], json={
        "player_id": p["id"], "video_id": v["id"], "observation_type": "video_highlights"})
    client.post("/api/reports/generate", headers=h, json={"player_id": p["id"]})
    client.post("/api/pipeline", headers=h, json={"player_id": p["id"]})
    client.put("/api/budgets", headers=E["H"]["sporting_director"], json={"season": "2026-27", "transfer_budget": 1})
    client.post("/api/users/invitations", headers=E["H"]["administrator"], json={"email": "z@e.io", "role": "video_scout"})
    # a consultant who also works for the demo organization
    client.post("/api/users", headers=E["H"]["administrator"], json={
        "email": "video@raja-scout.local", "full_name": "x", "role": "video_scout", "password": "unused-Pass1"})

    export = client.get("/api/admin/export", headers=E["H"]["administrator"]).json()
    assert len(export["tables"]["players"]) >= 1 and len(export["tables"]["match_videos"]) == 1

    with _sys() as db:
        before_demo = tenant_row_counts(db, 1)
        shared_players = db.scalar(select(func.count()).select_from(Player).where(Player.organization_id.is_(None)))
        counts = tenant_row_counts(db, E["id"])
        assert all(counts[t] >= 1 for t in ("players", "player_assessments", "player_season_stats", "match_videos",
                                            "video_observations", "match_reports", "scouting_reports",
                                            "pipeline_entries", "pipeline_events", "recruitment_budgets",
                                            "invitations", "audit_logs"))
        org = db.get(Organization, E["id"])
        with pytest.raises(ValueError, match="Schedule the deletion first"):
            purge_organization(db, org, "ephemeral")
        schedule_deletion(db, org, "test")
        db.commit()

    # step 1: access is blocked immediately, data retained
    assert client.get("/api/players", headers=h).status_code == 403
    assert client.post("/api/auth/token", data={"username": "ephemeral.head_of_scouting@example.com",
                                                "password": PASSWORD}).status_code == 403

    with _sys() as db:
        org = db.get(Organization, E["id"])
        with pytest.raises(ValueError, match="Confirmation"):
            purge_organization(db, org, "wrong-slug")
        result = purge_organization(db, org, "ephemeral", "test")
        db.commit()
        assert result["accounts_deleted"] == 5  # the five Ephemeral-only staff accounts
        assert all(v == 0 for v in tenant_row_counts(db, E["id"]).values())
        assert db.get(Organization, E["id"]) is None
        assert tenant_row_counts(db, 1) == before_demo  # other organizations untouched
        assert db.scalar(select(func.count()).select_from(Player).where(Player.organization_id.is_(None))) == shared_players
        consultant = db.scalar(select(User).where(User.email == "video@raja-scout.local"))
        assert consultant is not None and db.scalar(select(func.count()).select_from(Membership)
                                                    .where(Membership.user_id == consultant.id)) == 1
        assert db.scalar(select(User).where(User.email == "ephemeral.head_of_scouting@example.com")) is None
        rec = db.scalar(select(AuditLog).where(AuditLog.action == "organization.purged",
                                               AuditLog.entity_id == E["id"]))
        assert rec is not None and rec.organization_id is None and rec.details["slug"] == "ephemeral"
    assert client.get("/api/players", headers=H["video_scout"]).status_code == 200


def test_lifecycle_requires_system_context(client, B):
    from app.database import SessionLocal
    from app.tenancy import set_tenant
    with SessionLocal() as db:
        set_tenant(db, B["id"])
        with pytest.raises(RuntimeError, match="SYSTEM"):
            schedule_deletion(db, Organization(slug="x", name="x"))
