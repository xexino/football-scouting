def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_login_and_me(client, H):
    me = client.get("/api/auth/me", headers=H["sporting_director"]).json()
    assert me["role"] == "sporting_director"
    assert "pipeline:approve" in me["permissions"]


def test_bad_login_and_no_token(client):
    r = client.post("/api/auth/token", data={"username": "director@raja-scout.local", "password": "wrong-password1"})
    assert r.status_code == 401
    assert client.get("/api/players").status_code == 401
    assert client.get("/api/players", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_login_lockout(client):
    for _ in range(5):
        client.post("/api/auth/token", data={"username": "nobody@x.io", "password": "x"})
    r = client.post("/api/auth/token", data={"username": "nobody@x.io", "password": "x"})
    assert r.status_code == 429


def test_user_management_admin_only(client, H):
    body = {"email": "new.scout@raja-scout.local", "full_name": "New Scout", "role": "regional_scout",
            "password": "weak"}
    assert client.post("/api/users", headers=H["head_of_scouting"], json=body).status_code == 403
    assert client.post("/api/users", headers=H["administrator"], json=body).status_code == 422  # weak password
    body["password"] = "Str0ngPassword"
    r = client.post("/api/users", headers=H["administrator"], json=body)
    assert r.status_code == 201
    assert "hashed_password" not in r.json()
    assert client.post("/api/users", headers=H["administrator"], json=body).status_code == 409
    tok = client.post("/api/auth/token", data={"username": body["email"], "password": body["password"]})
    assert tok.status_code == 200
    # deactivate → cannot log in
    client.patch(f"/api/users/{r.json()['id']}", headers=H["administrator"], json={"is_active": False})
    assert client.post("/api/auth/token", data={"username": body["email"], "password": body["password"]}).status_code == 401


def test_financials_redacted_for_scouts(client, H, make_player):
    p = make_player()
    d = client.get(f"/api/players/{p['id']}", headers=H["sporting_director"]).json()
    assert d["estimated_fee_eur"] == 500000
    v = client.get(f"/api/players/{p['id']}", headers=H["video_scout"]).json()
    assert v["estimated_fee_eur"] is None and v["salary_expectation_eur"] is None and v["financials_redacted"]
    assert client.get("/api/players?fee_max=100000", headers=H["video_scout"]).status_code == 403
    assert client.patch(f"/api/players/{p['id']}", headers=H["regional_scout"],
                        json={"estimated_fee_eur": 1}).status_code == 403
    assert client.get("/api/dashboard", headers=H["video_scout"]).json()["budget"] is None


def test_role_restrictions(client, H):
    assert client.post("/api/import/json", headers=H["video_scout"], json={"data_source_id": 1}).status_code == 403
    assert client.get("/api/admin/audit-logs", headers=H["data_analyst"]).status_code == 403
    assert client.get("/api/admin/export", headers=H["regional_scout"]).status_code == 403
    assert client.put("/api/budgets", headers=H["head_of_scouting"],
                      json={"season": "2027-28", "transfer_budget_eur": 1}).status_code == 403


def test_audit_log_records_actions(client, H, make_player):
    p = make_player()
    logs = client.get("/api/admin/audit-logs?action=player.create", headers=H["administrator"]).json()
    assert any(l["entity_id"] == p["id"] for l in logs)
    assert any(l["action"] == "auth.login" for l in client.get("/api/admin/audit-logs", headers=H["administrator"]).json())


def test_export_excludes_password_hashes(client, H):
    r = client.get("/api/admin/export", headers=H["administrator"])
    assert r.status_code == 200
    data = r.json()
    assert "players" in data["tables"]
    assert all("hashed_password" not in u for u in data["tables"]["users"])
