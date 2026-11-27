"""End-to-end recruitment workflow: video → match reports → report → pipeline."""
import pytest


def video_body(pid, **kw):
    b = {"player_id": pid, "home_team": "A", "away_team": "B", "video_url": "https://licensed.example.com/m/1",
         "license_type": "licensed_full_match", "rights_holder": "Provider", "license_confirmed": True,
         "is_full_match": True, "duration_minutes": 95}
    b.update(kw)
    return b


def test_video_licensing_rules(client, H, make_player):
    p = make_player()
    assert client.post("/api/videos", headers=H["video_scout"], json=video_body(p["id"], license_confirmed=False)).status_code == 422
    assert client.post("/api/videos", headers=H["video_scout"],
                       json=video_body(p["id"], license_type="highlights", is_full_match=True)).status_code == 422
    assert client.post("/api/videos", headers=H["video_scout"], json=video_body(p["id"], video_url="ftp://x")).status_code == 422
    assert client.post("/api/videos", headers=H["data_analyst"], json=video_body(p["id"])).status_code == 403
    hl = client.post("/api/videos", headers=H["video_scout"],
                     json=video_body(p["id"], license_type="highlights", is_full_match=False)).json()
    assert hl["scope_warning"]


def test_observations_and_highlight_reports(client, H, make_player):
    p = make_player()
    hl = client.post("/api/videos", headers=H["video_scout"],
                     json=video_body(p["id"], license_type="highlights", is_full_match=False, duration_minutes=5)).json()
    obs = {"timestamp_seconds": 120, "category": "progressive_pass", "phase": "in_possession", "assessment": "positive",
           "technical_comment": "Line-breaking pass"}
    assert client.post(f"/api/videos/{hl['id']}/observations", headers=H["video_scout"], json=obs).status_code == 201
    assert client.post(f"/api/videos/{hl['id']}/observations", headers=H["video_scout"],
                       json={**obs, "timestamp_seconds": 999}).status_code == 422  # beyond duration
    # a highlights video cannot back a full-match report
    r = client.post("/api/match-reports", headers=H["video_scout"], json={
        "player_id": p["id"], "video_id": hl["id"], "observation_type": "video_full_match"})
    assert r.status_code == 422
    r = client.post("/api/match-reports", headers=H["video_scout"], json={
        "player_id": p["id"], "video_id": hl["id"], "observation_type": "video_highlights", "overall_rating": 8})
    assert r.status_code == 201
    assert r.json()["is_complete_match_analysis"] is False and "not equivalent" in r.json()["evidence_warning"]


def test_report_generation_separates_evidence(client, H, make_player):
    p = make_player()
    client.post("/api/match-reports", headers=H["regional_scout"], json={
        "player_id": p["id"], "observation_type": "live", "technical_rating": 7,
        "technical_notes": "Two-footed, receives on the half-turn.", "recommendation": "shortlist"})
    rep = client.post("/api/reports/generate", headers=H["regional_scout"], json={"player_id": p["id"]}).json()
    s = rep["sections"]
    tech = [i for i in s["technical"]["items"] if i["evidence_type"] == "scout_opinion"]
    assert tech and "Demo Regional Scout" in tech[0]["source"]
    assert s["mental"]["items"][0]["evidence_type"] == "insufficient_evidence"
    assert s["statistical_analysis"]["items"][0]["evidence_type"] == "insufficient_evidence"
    assert any(i["evidence_type"] == "scout_input_required" for i in s["recommendation"]["items"])
    assert any(i["evidence_type"] == "verified_data" for i in s["profile"]["items"])
    assert rep["recommendation"] is None  # the platform never decides
    # Data items must cite a source when edited
    bad = {"profile": {"title": "x", "items": [{"evidence_type": "verified_data", "text": "made up"}]}}
    assert client.patch(f"/api/reports/{rep['id']}", headers=H["regional_scout"], json={"sections": bad}).status_code == 422
    # finalisation rules
    assert client.post(f"/api/reports/{rep['id']}/finalize", headers=H["regional_scout"]).status_code == 403
    assert client.post(f"/api/reports/{rep['id']}/finalize", headers=H["head_of_scouting"]).status_code == 422
    client.patch(f"/api/reports/{rep['id']}", headers=H["head_of_scouting"], json={"recommendation": "shortlist"})
    assert client.post(f"/api/reports/{rep['id']}/finalize", headers=H["head_of_scouting"]).json()["status"] == "final"
    assert client.patch(f"/api/reports/{rep['id']}", headers=H["head_of_scouting"], json={"risk_level": "low"}).status_code == 409
    md = client.get(f"/api/reports/{rep['id']}/export.md", headers=H["video_scout"]).text
    assert "[SCOUT]" in md and "[DATA]" in md


@pytest.fixture
def entry(client, H, make_player):
    p = make_player()
    e = client.post("/api/pipeline", headers=H["regional_scout"], json={"player_id": p["id"], "priority": "high"})
    assert e.status_code == 201
    return p, e.json()


def move(client, h, eid, stage, note="Decision rationale"):
    return client.post(f"/api/pipeline/{eid}/move", headers=h, json={"to_stage": stage, "note": note})


def test_pipeline_full_lifecycle(client, H, entry):
    p, e = entry
    eid = e["id"]
    assert client.post("/api/pipeline", headers=H["regional_scout"], json={"player_id": p["id"]}).status_code == 409
    # cannot skip stages without approval rights
    assert move(client, H["regional_scout"], eid, "video_analysis").status_code == 422
    # note is mandatory
    assert move(client, H["regional_scout"], eid, "under_observation", note="").status_code == 422
    for st in ("under_observation", "data_analysis", "video_analysis"):
        assert move(client, H["data_analyst"], eid, st).status_code == 200
    # evidence gate: shortlist needs a match report
    assert move(client, H["head_of_scouting"], eid, "shortlisted").status_code == 422
    client.post("/api/match-reports", headers=H["regional_scout"], json={"player_id": p["id"], "observation_type": "live"})
    assert move(client, H["head_of_scouting"], eid, "shortlisted").status_code == 200
    assert move(client, H["head_of_scouting"], eid, "live_scouting").status_code == 200
    # approval: only sporting director, and requires a final report
    assert move(client, H["head_of_scouting"], eid, "approved").status_code == 403
    assert move(client, H["sporting_director"], eid, "approved").status_code == 422
    rep = client.post("/api/reports/generate", headers=H["head_of_scouting"], json={"player_id": p["id"]}).json()
    client.patch(f"/api/reports/{rep['id']}", headers=H["head_of_scouting"], json={"recommendation": "sign"})
    client.post(f"/api/reports/{rep['id']}/finalize", headers=H["head_of_scouting"])
    assert move(client, H["sporting_director"], eid, "approved").status_code == 200
    assert move(client, H["head_of_scouting"], eid, "negotiation").status_code == 403
    assert move(client, H["sporting_director"], eid, "negotiation").status_code == 200
    assert move(client, H["head_of_scouting"], eid, "rejected").status_code == 403
    assert move(client, H["sporting_director"], eid, "signed").status_code == 200
    assert move(client, H["sporting_director"], eid, "rejected").status_code == 409  # signed is final
    hist = client.get(f"/api/pipeline/{eid}", headers=H["video_scout"]).json()["history"]
    assert [h["to_stage"] for h in hist] == ["identified", "under_observation", "data_analysis", "video_analysis",
                                             "shortlisted", "live_scouting", "approved", "negotiation", "signed"]
    assert all(h["user_name"] for h in hist)


def test_pipeline_reject_and_reopen(client, H, entry):
    _, e = entry
    r = move(client, H["regional_scout"], e["id"], "rejected", "Below level in two live viewings")
    assert r.json()["rejection_reason"] == "Below level in two live viewings"
    assert move(client, H["regional_scout"], e["id"], "approved").status_code == 422
    r = move(client, H["regional_scout"], e["id"], "under_observation", "New information")
    assert r.status_code == 200 and "Re-opened" in r.json()["history"][-1]["note"]


def test_director_can_skip_with_trace(client, H, entry):
    _, e = entry
    r = move(client, H["sporting_director"], e["id"], "video_analysis", "Fast-track: known profile")
    assert r.status_code == 200 and "Skipped stage" in r.json()["history"][-1]["note"]


def test_compare(client, H, make_player, real_source):
    from conftest import stat_line
    ps = [make_player(primary_position="CB") for _ in range(3)]
    for p in ps:
        client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"], json=stat_line(real_source["id"]))
    r = client.post("/api/compare", headers=H["video_scout"], json={"player_ids": [p["id"] for p in ps]})
    assert r.status_code == 200
    d = r.json()
    assert d["position"] == "CB" and len(d["players"]) == 3
    assert d["players"][0]["financial"]["redacted"] is True
    assert d["players"][0]["tactical_suitability"]["evidence_type"] == "model_estimate"
    st = make_player(primary_position="ST")
    assert client.post("/api/compare", headers=H["video_scout"], json={"player_ids": [ps[0]["id"], st["id"]]}).status_code == 422
    assert client.post("/api/compare", headers=H["video_scout"], json={"player_ids": [ps[0]["id"]]}).status_code == 422
    six = [make_player()["id"] for _ in range(6)]
    assert client.post("/api/compare", headers=H["video_scout"], json={"player_ids": six}).status_code == 422


def test_dashboard(client, H):
    d = client.get("/api/dashboard", headers=H["sporting_director"]).json()
    assert d["players"]["total"] >= 96 and d["players"]["fictional"] >= 96
    assert set(d["pipeline"]["by_stage"]) >= {"identified", "signed", "rejected"}
    assert d["budget"]["transfer_budget_eur"] == 6_000_000
    assert len(d["activity"]["weekly"]) == 12
