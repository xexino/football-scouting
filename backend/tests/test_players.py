from conftest import stat_line


def test_seed_is_flagged_fictional(client, H):
    data = client.get("/api/players?page_size=200&include_fictional=true", headers=H["data_analyst"]).json()
    seeded = [p for p in data["items"] if p["data_source"] == "FICTIONAL SAMPLE DATA"]
    assert len(seeded) >= 90
    assert all(p["is_fictional"] for p in seeded)


def test_create_and_provenance(client, H, make_player, real_source):
    p = make_player(full_name="Provenance Check", secondary_positions=["DM"])
    assert p["data_source"] == real_source["name"] and p["is_fictional"] is False
    assert p["last_updated"]


def test_search_filters(client, H, make_player):
    a = make_player(full_name="Zed Searchable", primary_position="ST", height_cm=191, preferred_foot="left",
                    nationality="Ghana", date_of_birth="2004-01-01", availability="available")
    q = lambda **kw: client.get("/api/players", params={"include_fictional": False, **kw}, headers=H["sporting_director"]).json()  # noqa: E731
    assert any(p["id"] == a["id"] for p in q(q="zed search")["items"])
    assert any(p["id"] == a["id"] for p in q(position="ST", height_min=190, foot="left")["items"])
    assert not any(p["id"] == a["id"] for p in q(position="ST", height_min=195)["items"])
    assert any(p["id"] == a["id"] for p in q(nationality="ghana", availability="available")["items"])
    assert not any(p["id"] == a["id"] for p in q(age_max=18)["items"])
    assert any(p["id"] == a["id"] for p in q(fee_max=600000, pipeline_stage="none")["items"])
    assert all(not p["is_fictional"] for p in q(page_size=200)["items"])


def test_secondary_position_search(client, H, make_player):
    p = make_player(primary_position="CM", secondary_positions=["AM"])
    ids = lambda **kw: [x["id"] for x in client.get("/api/players", params={"position": "AM", "page_size": 200, **kw}, headers=H["data_analyst"]).json()["items"]]  # noqa: E731
    assert p["id"] in ids()
    assert p["id"] not in ids(primary_only=True)


def test_stats_upsert_and_stat_filters(client, H, make_player, real_source):
    p = make_player(primary_position="DM")
    r = client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"], json=stat_line(real_source["id"]))
    assert r.status_code == 201
    assert r.json()["pressures"] is None  # not provided ⇒ NULL, not 0
    # idempotent per player/season/league/source
    r2 = client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"],
                     json=stat_line(real_source["id"], interceptions=40))
    assert r2.json()["id"] == r.json()["id"] and r2.json()["interceptions"] == 40
    res = client.get("/api/players", headers=H["data_analyst"], params={
        "stat_filters": "prog_passes_p90>=4.9,pass_pct>=85", "include_fictional": False}).json()
    match = [x for x in res["items"] if x["id"] == p["id"]]
    assert match and match[0]["matched_metrics"]["prog_passes_p90"] == 5.0
    assert client.get("/api/players", headers=H["data_analyst"], params={"stat_filters": "nope>=1"}).status_code == 422


def test_stats_validation(client, H, make_player, real_source):
    p = make_player()
    bad = stat_line(real_source["id"], passes_completed=2000)  # more than attempted
    assert client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"], json=bad).status_code == 422
    no_src = stat_line(999999)
    assert client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"], json=no_src).status_code == 422
    assert client.post(f"/api/players/{p['id']}/stats", headers=H["video_scout"],
                       json=stat_line(real_source["id"])).status_code == 403


def test_analytics_output(client, H, make_player, real_source):
    p = make_player(primary_position="CM")
    client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"], json=stat_line(real_source["id"], minutes=450))
    a = client.get(f"/api/players/{p['id']}/analytics", headers=H["data_analyst"]).json()
    assert a["has_data"] and a["sample_reliable"] is False
    assert any("Small sample" in c for c in a["caveats"])
    assert any("not how good the player is" in c for c in a["caveats"])
    assert a["provenance"]["evidence_type"] == "verified_data"
    keys = [m["key"] for m in a["profile_metrics"]]
    assert "prog_passes_p90" in keys and "save_pct" not in keys
    empty = client.get(f"/api/players/{make_player()['id']}/analytics", headers=H["data_analyst"]).json()
    assert empty["has_data"] is False


def test_csv_export(client, H):
    r = client.get("/api/players/export.csv", headers=H["video_scout"])
    assert r.status_code == 200 and r.text.startswith("id,scope,full_name")
    # fee column present but empty for a role without financial access
    header, first = r.text.splitlines()[:2]
    idx = header.split(",").index("estimated_fee")
    assert first.split(",")[idx] == ""


def test_delete_requires_permission(client, H, make_player):
    p = make_player()
    assert client.delete(f"/api/players/{p['id']}", headers=H["data_analyst"]).status_code == 403
    assert client.delete(f"/api/players/{p['id']}", headers=H["head_of_scouting"]).status_code == 204
    assert client.get(f"/api/players/{p['id']}", headers=H["head_of_scouting"]).status_code == 404
