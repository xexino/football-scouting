PLAYERS_CSV = """full_name,date_of_birth,nationality,club,club_country,league,league_country,primary_position,secondary_positions,height_cm,preferred_foot,contract_expiry,estimated_fee,availability
Import Alpha,2002-02-02,Senegal,Import FC,Senegal,Import League,Senegal,CB,DM|FB,188,right,2027-06-30,750000,available
Import Beta,2003-03-03,Mali,Import FC,Senegal,Import League,Senegal,XX,,180,right,,,unknown
Import Gamma,2001-01-01,Ghana,,,,,W,,175,left,,,
"""

STATS_CSV = """full_name,date_of_birth,season,league,league_country,minutes,appearances,starts,interceptions,pressures
Import Alpha,2002-02-02,2025-26,Import League,Senegal,1800,22,20,35,
Unknown Person,1990-01-01,2025-26,Import League,Senegal,900,10,10,5,
"""


def upload(client, h, kind, content, source_id, dry_run=False):
    return client.post(f"/api/import/{kind}", headers=h, files={"file": (f"{kind}.csv", content, "text/csv")},
                       data={"data_source_id": str(source_id), "dry_run": "true" if dry_run else "false"})


def test_templates(client, H):
    r = client.get("/api/import/templates/players.csv", headers=H["data_analyst"])
    assert r.status_code == 200 and r.text.startswith("full_name,")


def test_csv_dry_run_changes_nothing(client, H, real_source):
    r = upload(client, H["data_analyst"], "players", PLAYERS_CSV, real_source["id"], dry_run=True).json()
    assert r["dry_run"] and r["created"] == 2 and len(r["errors"]) == 1
    found = client.get("/api/players?q=Import Alpha", headers=H["data_analyst"]).json()["total"]
    assert found == 0


def test_csv_import_players_and_stats(client, H, real_source):
    r = upload(client, H["head_of_scouting"], "players", PLAYERS_CSV, real_source["id"]).json()
    assert r["created"] == 2 and r["errors"][0]["row"] == 2  # invalid position rejected, others kept
    alpha = client.get("/api/players?q=Import Alpha", headers=H["head_of_scouting"]).json()["items"][0]
    assert alpha["club_name"] == "Import FC" and alpha["secondary_positions"] == ["DM", "FB"]
    assert alpha["estimated_fee"] == 750000 and alpha["data_source"] == real_source["name"]
    # re-import updates instead of duplicating
    r2 = upload(client, H["head_of_scouting"], "players", PLAYERS_CSV, real_source["id"]).json()
    assert r2["updated"] == 2 and r2["created"] == 0

    s = upload(client, H["data_analyst"], "stats", STATS_CSV, real_source["id"]).json()
    assert s["created"] == 1 and len(s["errors"]) == 1
    stats = client.get(f"/api/players/{alpha['id']}/stats", headers=H["data_analyst"]).json()
    assert stats[0]["interceptions"] == 35 and stats[0]["pressures"] is None and stats[0]["tackles"] is None


def test_import_requires_known_source(client, H):
    assert upload(client, H["data_analyst"], "players", PLAYERS_CSV, 99999).status_code == 422


def test_analyst_import_drops_financials(client, H, real_source):
    csv = "full_name,date_of_birth,nationality,primary_position,estimated_fee\nFee Drop,2000-01-01,Egypt,ST,999\n"
    upload(client, H["data_analyst"], "players", csv, real_source["id"])
    p = client.get("/api/players?q=Fee Drop", headers=H["sporting_director"]).json()["items"][0]
    assert p["estimated_fee"] is None


def test_json_import(client, H, real_source):
    body = {"data_source_id": real_source["id"],
            "players": [{"full_name": "Json Player", "date_of_birth": "2000-05-05", "nationality": "Tunisia",
                         "primary_position": "GK", "league": "Json League", "league_country": "Tunisia"}],
            "stats": [{"full_name": "Json Player", "date_of_birth": "2000-05-05", "season": "2025-26",
                       "league": "Json League", "league_country": "Tunisia", "minutes": 2700, "saves": 80,
                       "shots_on_target_faced": 110, "goals_conceded": 30, "psxg_faced": 33.5}]}
    r = client.post("/api/import/json", headers=H["head_of_scouting"], json=body).json()
    assert r["players"]["created"] == 1 and r["stats"]["created"] == 1
    pid = client.get("/api/players?q=Json Player", headers=H["head_of_scouting"]).json()["items"][0]["id"]
    a = client.get(f"/api/players/{pid}/analytics", headers=H["head_of_scouting"]).json()
    pm = {m["key"]: m["value"] for m in a["profile_metrics"]}
    assert pm["save_pct"] == 72.7 and pm["goals_prevented_p90"] == 0.117
