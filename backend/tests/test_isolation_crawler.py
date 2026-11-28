"""Automated cross-tenant crawler.

Organization V ("victim") gets a complete set of private records, each containing a unique
marker string. The attacker organization's *administrator* (all permissions) then calls
every tenant-scoped route discovered from the application itself — every method, with the
victim's ids substituted into path parameters and into request bodies. Assertions:

1. no response body ever contains a victim marker (no read / export leak);
2. no request targeting a victim id succeeds (2xx) on an id-addressed route;
3. the victim's full organization export is identical before and after (nothing modified
   or deleted).

Run in both directions. New routes are covered automatically.
"""
import json
import re
import uuid

import pytest
from fastapi.routing import APIRoute

from app.main import app
from conftest import create_org, stat_line


def _flatten(routes):
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        if hasattr(r, "original_router"):
            yield from _flatten(r.original_router.routes)


def _deps(route):
    names = set()

    def walk(d):
        for sub in d.dependencies:
            names.add(getattr(sub.call, "__qualname__", str(sub.call)))
            walk(sub)
    walk(route.dependant)
    return names


TENANT_ROUTES = sorted({(m, r.path) for r in _flatten(app.routes) if any("get_ctx" in d for d in _deps(r))
                        for m in r.methods})


def test_route_inventory_is_complete():
    # if this number changes, review the new routes for tenant isolation
    assert len(TENANT_ROUTES) >= 64
    public = sorted({(m, r.path) for r in _flatten(app.routes) for m in r.methods
                     if not ({"get_ctx", "get_current_user", "require_platform_admin"}
                             & {n.split(".")[0] for n in _deps(r)} | {n for n in _deps(r) if "get_" in n or "require" in n})})
    assert {p for _, p in public} <= {"/", "/api/health", "/api/public/config", "/api/auth/token",
                                       "/api/auth/invitations/{token}", "/api/auth/invitations/accept",
                                       "/api/auth/password-reset", "/api/billing/webhook/{provider}"}, public


def _populate(client, org, tag):
    """Create one of every private resource in ``org``; return (ids, markers)."""
    H = org["H"]
    m = {k: f"{tag}-{k}-{uuid.uuid4().hex[:8]}" for k in
         ("player", "notes", "source", "league", "club", "video", "obs", "match", "report", "pipeline", "budget",
          "invite", "agent")}
    hs = H["head_of_scouting"]
    src = client.post("/api/data-sources", headers=hs, json={"name": m["source"], "source_type": "manual",
                                                              "license_notes": m["source"]}).json()
    lg = client.post("/api/leagues", headers=hs, json={"name": m["league"], "country": "Morocco"}).json()
    cl = client.post("/api/clubs", headers=hs, json={"name": m["club"], "country": "Morocco", "league_id": lg["id"]}).json()
    p = client.post("/api/players", headers=hs, json={
        "full_name": m["player"], "nationality": "Morocco", "primary_position": "CM", "current_club_id": cl["id"],
        "data_source_id": src["id"], "notes": m["notes"], "agent_name": m["agent"], "estimated_fee": 777}).json()
    st = client.post(f"/api/players/{p['id']}/stats", headers=H["data_analyst"],
                     json=stat_line(src["id"], league_id=lg["id"], club_name=m["club"])).json()
    v = client.post("/api/videos", headers=H["video_scout"], json={
        "player_id": p["id"], "home_team": m["video"], "away_team": "B", "video_url": "https://licensed.example.com/x",
        "license_type": "club_internal", "rights_holder": "Club", "license_confirmed": True, "is_full_match": True}).json()
    ob = client.post(f"/api/videos/{v['id']}/observations", headers=H["video_scout"],
                     json={"timestamp_seconds": 3, "category": "passing", "technical_comment": m["obs"]}).json()
    mr = client.post("/api/match-reports", headers=H["video_scout"], json={
        "player_id": p["id"], "video_id": v["id"], "observation_type": "video_full_match", "summary": m["match"]}).json()
    rep = client.post("/api/reports/generate", headers=hs, json={"player_id": p["id"]}).json()
    client.patch(f"/api/reports/{rep['id']}", headers=hs, json={"title": m["report"]})
    e = client.post("/api/pipeline", headers=hs, json={"player_id": p["id"], "note": m["pipeline"]}).json()
    client.put("/api/budgets", headers=H["sporting_director"], json={"season": "2030-31", "transfer_budget": 1,
                                                                    "notes": m["budget"]})
    inv = client.post("/api/users/invitations", headers=H["administrator"],
                      json={"email": f"{m['invite']}@example.com", "role": "video_scout"}).json()
    uid = client.get("/api/auth/me", headers=H["video_scout"]).json()["id"]
    ids = {"player_id": p["id"], "stats_id": st["id"], "video_id": v["id"], "obs_id": ob["id"], "report_id": rep["id"],
           "entry_id": e["id"], "league_id": lg["id"], "invitation_id": inv["id"], "user_id": uid,
           "match_report_id": mr["id"], "data_source_id": src["id"], "club_id": cl["id"]}
    assert all(isinstance(x, int) for x in ids.values()), ids
    return ids, set(m.values())


def _body(ids):
    """A request body that points every plausible field at the victim's records."""
    return {"player_id": ids["player_id"], "player_ids": [ids["player_id"], ids["player_id"] + 1],
            "video_id": ids["video_id"], "data_source_id": ids["data_source_id"], "league_id": ids["league_id"],
            "current_club_id": ids["club_id"], "assigned_scout_id": ids["user_id"], "to_stage": "rejected",
            "note": "crawler", "season": "2025-26", "timestamp_seconds": 1, "category": "passing",
            "observation_type": "live", "home_team": "x", "away_team": "y", "video_url": "https://x.example/1",
            "license_type": "club_internal", "rights_holder": "xx", "license_confirmed": True,
            "full_name": "Crawler", "nationality": "X", "primary_position": "ST", "name": "crawler-name",
            "source_type": "manual", "country": "X", "email": "crawler@example.com", "role": "video_scout",
            "transfer_budget": 1, "title": "crawler", "minutes": 1}


def _snapshot(client, admin_headers):
    exp = client.get("/api/admin/export", headers=admin_headers).json()
    tables = {k: v for k, v in exp["tables"].items() if k not in ("audit_logs",)}
    return json.dumps(tables, sort_keys=True, default=str)


@pytest.mark.parametrize("direction", ["A_attacks_B", "B_attacks_A"])
def test_crawl_every_tenant_route_across_organizations(client, direction):
    tag = direction.replace("_attacks_", "")
    victim = create_org(client, f"crawl-victim-{tag.lower()}", f"Crawl Victim {tag}")
    attacker = create_org(client, f"crawl-attacker-{tag.lower()}", f"Crawl Attacker {tag}")
    ids, markers = _populate(client, victim, f"SECRET{tag}")
    _populate(client, attacker, f"OWN{tag}")  # attacker has its own data so list endpoints are non-trivial
    before = _snapshot(client, victim["H"]["administrator"])
    ah = attacker["H"]["administrator"]
    from fastapi.testclient import TestClient
    raw = TestClient(app, raise_server_exceptions=False)  # record 5xx instead of raising
    leaks, successes, errors = [], [], []
    for method, path in TENANT_ROUTES:
        params = re.findall(r"{(\w+)}", path)
        url = path
        for prm in params:
            url = url.replace("{" + prm + "}", str(ids.get(prm, ids["player_id"])))
        if "/export.md" in url:
            url = url.replace("{report_id}", str(ids["report_id"]))
        kw = {} if method in ("GET", "DELETE") else {"json": _body(ids)}
        if path in ("/api/import/players", "/api/import/stats", "/api/organization/logo") and method == "POST":
            kw = {"files": {"file": ("x.csv", "full_name\nx\n", "text/csv")}, "data": {"data_source_id": str(ids["data_source_id"])}}
        r = raw.request(method, url, headers=ah, **kw)
        text = r.text
        if r.status_code >= 500:
            errors.append((method, url, r.status_code))
        if any(mk in text for mk in markers):
            leaks.append((method, url, r.status_code))
        if params and 200 <= r.status_code < 300 and method != "GET" or (params and method == "GET" and r.status_code == 200
                                                                         and text not in ("null", "[]")):
            successes.append((method, url, r.status_code, text[:120]))
    assert not leaks, f"victim data leaked: {leaks}"
    assert not errors, f"server errors on attacker input: {errors}"
    assert not successes, f"requests on victim ids succeeded: {successes}"
    assert _snapshot(client, victim["H"]["administrator"]) == before, "victim data was modified"


REFERENCE_FIELDS = {  # column -> which victim id it must never point to
    "current_club_id": "club_id", "data_source_id": "data_source_id", "league_id": "league_id",
    "assigned_scout_id": "user_id", "video_id": "video_id", "player_id": "player_id", "entry_id": "entry_id",
}


@pytest.mark.parametrize("direction", ["A_attacks_B", "B_attacks_A"])
def test_own_records_cannot_reference_other_organization(client, direction):
    """Second pass: the attacker edits ITS OWN records (own ids in the path) while every body
    field points at the victim's records. Nothing may leak, the victim must be unchanged, and
    no attacker row may end up referencing a victim row."""
    tag = "R" + direction.replace("_attacks_", "")
    victim = create_org(client, f"ref-victim-{tag.lower()}", f"Ref Victim {tag}")
    attacker = create_org(client, f"ref-attacker-{tag.lower()}", f"Ref Attacker {tag}")
    vids, markers = _populate(client, victim, f"SECRET{tag}")
    aids, _ = _populate(client, attacker, f"OWN{tag}")
    before = _snapshot(client, victim["H"]["administrator"])
    from fastapi.testclient import TestClient
    raw = TestClient(app, raise_server_exceptions=False)
    ah = attacker["H"]["administrator"]
    leaks, errors = [], []
    for method, path in TENANT_ROUTES:
        if method in ("GET", "DELETE"):
            continue
        url = path
        for prm in re.findall(r"{(\w+)}", path):
            url = url.replace("{" + prm + "}", str(aids.get(prm, aids["player_id"])))
        if path in ("/api/import/players", "/api/import/stats", "/api/organization/logo"):
            continue
        r = raw.request(method, url, headers=ah, json=_body(vids))
        if any(mk in r.text for mk in markers):
            leaks.append((method, url))
        if r.status_code >= 500:
            errors.append((method, url, r.status_code))
    assert not leaks and not errors, (leaks, errors)
    assert _snapshot(client, victim["H"]["administrator"]) == before
    exp = client.get("/api/admin/export", headers=ah).json()
    bad = [(t, row.get("id"), col) for t, rows in exp["tables"].items() for row in rows
           for col, kind in REFERENCE_FIELDS.items()
           if col in row and row[col] is not None and row[col] == vids[kind] and not (t == "players" and col == "player_id")]
    assert not bad, f"attacker rows reference victim records: {bad}"
