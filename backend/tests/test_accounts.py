"""Stage 3: individual account provisioning (invitations) and password reset links."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.accounts import hash_token
from app.models import Invitation
from conftest import PASSWORD, _sys, create_org


@pytest.fixture(scope="module")
def D(client):
    return create_org(client, "dunes-sc", "Dunes SC")


def invite(client, org, email, role="video_scout"):
    r = client.post("/api/users/invitations", headers=org["H"]["administrator"], json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["invite_url"].rsplit("/", 1)[1], r.json()


def test_invite_new_user_end_to_end(client, D):
    assert client.post("/api/users/invitations", headers=D["H"]["head_of_scouting"],
                       json={"email": "x@y.io", "role": "video_scout"}).status_code == 403
    token, inv = invite(client, D, "new.scout@dunes.ma", "regional_scout")
    assert inv["status"] == "pending" and "/#/invite/" in inv["invite_url"]
    with _sys() as db:  # only the hash is stored
        row = db.scalar(select(Invitation).where(Invitation.id == inv["id"]))
        assert row.token_hash == hash_token(token) and token not in row.token_hash
    prev = client.get(f"/api/auth/invitations/{token}").json()
    assert prev == {**prev, "organization": "Dunes SC", "email": "new.scout@dunes.ma", "existing_account": False}
    assert client.post("/api/auth/invitations/accept", json={"token": token, "password": "weak"}).status_code == 422
    assert client.post("/api/auth/invitations/accept", json={"token": token, "password": "Str0ng-password"}).status_code == 422
    r = client.post("/api/auth/invitations/accept", json={"token": token, "password": "Str0ng-password", "full_name": "New Scout"})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "regional_scout" and me["organization"]["slug"] == "dunes-sc"
    assert client.post("/api/auth/invitations/accept", json={"token": token, "password": "Str0ng-password",
                                                             "full_name": "x"}).status_code == 410  # single use
    assert client.get(f"/api/auth/invitations/{token}").status_code == 410
    assert client.post("/api/users/invitations", headers=D["H"]["administrator"],
                       json={"email": "new.scout@dunes.ma", "role": "video_scout"}).status_code == 409


def test_revoked_expired_and_unknown_links(client, D):
    t1, inv1 = invite(client, D, "revoke.me@dunes.ma")
    assert client.delete(f"/api/users/invitations/{inv1['id']}", headers=D["H"]["administrator"]).status_code == 204
    assert client.get(f"/api/auth/invitations/{t1}").status_code == 410
    t2, inv2 = invite(client, D, "expire.me@dunes.ma")
    with _sys() as db:
        db.get(Invitation, inv2["id"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.post("/api/auth/invitations/accept", json={"token": t2, "password": "Str0ng-password",
                                                             "full_name": "Late"}).status_code == 410
    assert client.get("/api/auth/invitations/not-a-real-token").status_code == 404
    # re-inviting revokes the previous live link
    t3, _ = invite(client, D, "twice@dunes.ma")
    invite(client, D, "twice@dunes.ma")
    assert client.get(f"/api/auth/invitations/{t3}").status_code == 410


def test_existing_account_must_prove_ownership(client, D, H):
    token, _ = invite(client, D, "analyst@raja-scout.local", "data_analyst")  # account exists in demo org
    assert client.get(f"/api/auth/invitations/{token}").json()["existing_account"] is True
    assert client.post("/api/auth/invitations/accept", json={"token": token, "password": "Wrong-pass-123"}).status_code == 401
    r = client.post("/api/auth/invitations/accept", json={"token": token, "password": PASSWORD})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=H["data_analyst"]).json()
    assert {o["name"] for o in me["organizations"]} >= {"Dunes SC"}
    # the demo account's own organization and credentials are unaffected
    assert client.post("/api/auth/token", data={"username": "analyst@raja-scout.local", "password": PASSWORD}).status_code == 200


def test_invitations_are_tenant_isolated(client, D, B):
    _, inv = invite(client, D, "isolated@dunes.ma")
    assert all(i["id"] != inv["id"] for i in client.get("/api/users/invitations", headers=B["H"]["administrator"]).json())
    assert client.delete(f"/api/users/invitations/{inv['id']}", headers=B["H"]["administrator"]).status_code == 404


def test_password_reset_link(client, D):
    token, _ = invite(client, D, "forgetful@dunes.ma")
    acc = client.post("/api/auth/invitations/accept", json={"token": token, "password": "First-pass-123",
                                                            "full_name": "Forgetful"}).json()
    old = {"Authorization": f"Bearer {acc['access_token']}"}
    uid = client.get("/api/auth/me", headers=old).json()["id"]
    assert client.post(f"/api/users/{uid}/password-reset-link", headers=D["H"]["head_of_scouting"]).status_code == 403
    link = client.post(f"/api/users/{uid}/password-reset-link", headers=D["H"]["administrator"]).json()["reset_url"]
    raw = link.rsplit("/", 1)[1]
    assert client.post("/api/auth/password-reset", json={"token": raw, "new_password": "short"}).status_code == 422
    assert client.post("/api/auth/password-reset", json={"token": raw, "new_password": "Second-pass-456"}).status_code == 200
    assert client.post("/api/auth/password-reset", json={"token": raw, "new_password": "Third-pass-789"}).status_code == 410
    assert client.get("/api/players", headers=old).status_code == 401  # sessions revoked
    assert client.post("/api/auth/token", data={"username": "forgetful@dunes.ma", "password": "Second-pass-456"}).status_code == 200


def test_reset_link_refused_for_multi_org_accounts(client, D, H):
    uid = client.get("/api/auth/me", headers=H["data_analyst"]).json()["id"]  # also member of Dunes (above)
    r = client.post(f"/api/users/{uid}/password-reset-link", headers=D["H"]["administrator"])
    assert r.status_code == 403
