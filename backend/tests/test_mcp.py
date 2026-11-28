"""Security and behaviour tests for the Raja Scout MCP server (app/mcp).

Covers: anonymous access, invalid/expired/revoked authentication, cross-tenant isolation,
role permissions, every read-only tool, write-tool human approval, input validation,
provider failures, rate limiting and audit logging. Calls go through a real MCP client
(in-process transport) and, for the connection-level checks, over Streamable HTTP.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
from datetime import datetime, timedelta, timezone

import anyio
import httpx2
import jwt
import pytest
import uvicorn
from sqlalchemy import select

from mcp import Client
from mcp.types import ElicitResult

from app.config import settings
from app.mcp import gateway
from app.mcp.server import build_server
from app.mcp.tools import READ_TOOLS, WRITE_TOOLS
from app.models import AuditLog, Player, User
from app.providers import ProviderClient, ProviderConfig, ProviderError, ProviderNotAllowed
from app.security import ALGORITHM

from conftest import _sys, create_org, stat_line

PRIVATE_NOTE = "MCP-SECRET-NOTE-rival-only"


def tok(headers: dict) -> str:
    return headers["Authorization"].split(" ", 1)[1]


@pytest.fixture(autouse=True)
def generous_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "mcp_rate_limit_per_minute", 100_000)


def call(token, tool, args=None, *, write=False, elicit=None):
    """Call one tool through a real MCP client session; returns (is_error, payload)."""
    server = build_server(lambda: token, transport="test", write_tools=write)

    async def go():
        try:
            return await inner()
        except BaseExceptionGroup as eg:  # protocol-level refusal (e.g. client cannot elicit)
            return True, " ".join(repr(e) for e in eg.exceptions)

    async def inner():
        async with Client(server, elicitation_callback=elicit) as c:
            res = await c.call_tool(tool, args or {})
            if res.is_error:
                text = " ".join(getattr(x, "text", "") for x in res.content)
                if "{" in text:  # refusal raised before approval: "Error executing tool X: {json}"
                    try:
                        return True, json.loads(text[text.index("{"):])
                    except ValueError:
                        pass
                return True, text
            payload = res.structured_content
            if payload is None:
                payload = json.loads(res.content[0].text)
            return False, payload.get("result", payload) if set(payload) == {"result"} else payload

    return anyio.run(go)


def ok(token, tool, args=None, **kw):
    err, out = call(token, tool, args, **kw)
    assert not err and "error" not in out, out
    return out


def audit_rows(action_prefix="mcp.", since=None):
    with _sys() as db:
        q = select(AuditLog).where(AuditLog.action.like(f"{action_prefix}%")).order_by(AuditLog.id)
        if since is not None:
            q = q.where(AuditLog.id > since)
        return db.scalars(q).all()


def last_audit_id():
    with _sys() as db:
        return db.scalar(select(AuditLog.id).order_by(AuditLog.id.desc()).limit(1)) or 0


# --------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def B(client):
    """A rival organization owned by these tests (the shared "Rival FC" must stay empty for test_tenancy)."""
    org = create_org(client, "mcp-rival", "MCP Rival FC", currency="DZD", country="Algeria")
    org["source"] = client.post("/api/data-sources", headers=org["H"]["head_of_scouting"], json={
        "name": "MCP rival licensed feed", "source_type": "api_import", "license_notes": "Rival contract"}).json()
    return org


@pytest.fixture(scope="module")
def rival(client, B):
    """The rival's private records: a private player with stats, a report, a pipeline entry, and a
    private note on a shared player."""
    hb = B["H"]
    p = client.post("/api/players", headers=hb["head_of_scouting"], json={
        "full_name": "Rival Private Prospect", "nationality": "Algeria", "primary_position": "CB",
        "date_of_birth": "2006-01-01", "data_source_id": B["source"]["id"], "notes": PRIVATE_NOTE}).json()
    assert client.post(f"/api/players/{p['id']}/stats", headers=hb["head_of_scouting"],
                       json=stat_line(B["source"]["id"])).status_code == 201
    rep = client.post("/api/reports/generate", headers=hb["head_of_scouting"], json={"player_id": p["id"]}).json()
    entry = client.post("/api/pipeline", headers=hb["head_of_scouting"], json={"player_id": p["id"], "priority": "high"}).json()
    with _sys() as db:
        shared = Player(full_name="MCP Platform Striker", nationality="Morocco", primary_position="ST",
                        organization_id=None, is_fictional=False)
        db.add(shared)
        db.commit()
        shared_id = shared.id
    assert client.patch(f"/api/players/{shared_id}", headers=hb["sporting_director"],
                        json={"notes": PRIVATE_NOTE, "estimated_fee": 4242}).status_code == 200
    return {"player_id": p["id"], "report_id": rep["id"], "entry_id": entry["id"], "shared_id": shared_id}


@pytest.fixture(scope="module")
def demo_ids(client, tokens):
    H = tokens
    players = client.get("/api/players", headers=H["sporting_director"], params={"position": "CB", "page_size": 5}).json()
    videos = client.get("/api/videos", headers=H["sporting_director"]).json()
    board = client.get("/api/pipeline", headers=H["sporting_director"]).json()
    entry = next(e for e in board["columns"]["identified"])
    reports = client.get("/api/reports", headers=H["sporting_director"]).json()
    return {"cbs": [p["id"] for p in players["items"]], "video_id": videos[0]["id"], "entry": entry,
            "report_id": reports[0]["id"]}


# --------------------------------------------------------------------------- authentication
def test_anonymous_calls_are_refused_and_reveal_nothing(client):
    before = last_audit_id()
    for name in READ_TOOLS:
        args = {"player_id": 1} if name in ("get_player_profile", "get_player_statistics") else \
            {"player_ids": [1, 2]} if name == "compare_players" else \
            {"position": "CB", "metrics": ["pass_pct"]} if name == "generate_shortlist" else {}
        err, out = call(None, name, args)
        assert not err and out == {"error": "unauthenticated", "message": "Authentication required"}, (name, out)
    assert audit_rows(since=before) == []  # no organization known: nothing attributable to audit


def test_invalid_expired_and_revoked_tokens_are_refused(client, H):
    good = tok(H["data_analyst"])
    payload = jwt.decode(good, options={"verify_signature": False})
    forged = jwt.encode({**payload}, "not-the-server-secret-" * 3, algorithm=ALGORITHM)
    expired = jwt.encode({**payload, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
                         settings.secret_key, algorithm=ALGORITHM)
    no_org = jwt.encode({**payload, "org": None}, settings.secret_key, algorithm=ALGORITHM)
    other_org = jwt.encode({**payload, "org": 999_999}, settings.secret_key, algorithm=ALGORITHM)
    for bad in ("garbage", "", "Bearer x", forged, expired):
        _, out = call(bad, "search_players")
        assert out["error"] == "unauthenticated", (bad[:20], out)
    for bad in (no_org, other_org):  # valid identity, but no membership in the claimed organization
        _, out = call(bad, "search_players")
        assert out["error"] == "forbidden", out

    org = create_org(client, "mcp-revoke", "Revoke FC", roles=["administrator"])
    t = tok(org["H"]["administrator"])
    assert ok(t, "search_players")["total"] >= 0
    with _sys() as db:  # password change / logout-all bumps token_version -> old tokens die
        u = db.scalar(select(User).where(User.email == "mcp-revoke.administrator@example.com"))
        u.token_version += 1
        db.commit()
    assert call(t, "search_players")[1]["error"] == "unauthenticated"


def test_http_transport_authenticates_every_connection(client, H):
    from app.mcp.__main__ import http_app
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(http_app("127.0.0.1", port), port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/mcp"
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    hdr = {"Accept": "application/json, text/event-stream"}
    try:
        assert httpx2.post(url, json=init, headers=hdr).status_code == 401
        assert httpx2.post(url, json=init, headers={**hdr, "Authorization": "Bearer garbage"}).status_code == 401
        assert httpx2.post(url, json=init, headers={**hdr, "Authorization": "Basic abc"}).status_code == 401

        async def session():
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
            async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {tok(H['sporting_director'])}"}) as hc:
                async with streamable_http_client(url, http_client=hc) as streams:
                    async with ClientSession(streams[0], streams[1]) as sess:
                        await sess.initialize()
                        names = [t.name for t in (await sess.list_tools()).tools]
                        res = await sess.call_tool("search_players", {"positions": ["CB"], "page_size": 3})
                        return names, res.structured_content or json.loads(res.content[0].text)
        names, out = anyio.run(session)
        assert sorted(names) == sorted(READ_TOOLS)  # write tools are not exposed by default
        assert out["total"] > 0 and len(out["items"]) == 3
    finally:
        server.should_exit = True


# --------------------------------------------------------------------------- tenant isolation
def test_cross_tenant_private_records_are_invisible(client, H, rival):
    t = tok(H["sporting_director"])
    for tool, args in [("get_player_profile", {"player_id": rival["player_id"]}),
                       ("get_player_statistics", {"player_id": rival["player_id"]}),
                       ("get_scouting_reports", {"report_id": rival["report_id"]})]:
        assert call(t, tool, args)[1]["error"] == "not_found", tool
    found = ok(t, "search_players", {"query": "Rival Private", "page_size": 50})
    assert found["total"] == 0
    assert call(t, "compare_players", {"player_ids": [rival["player_id"], rival["shared_id"]],
                                       "allow_mixed_positions": True})[1]["error"] == "not_found"
    board = ok(t, "get_recruitment_pipeline")
    assert rival["player_id"] not in [e["player_id"] for col in board["columns"].values() for e in col]
    assert ok(t, "get_recruitment_pipeline", {"player_id": rival["player_id"]})["entry"] is None
    reports = ok(t, "get_scouting_reports")["reports"]
    assert rival["report_id"] not in [r["id"] for r in reports]
    # shared player: visible to both, but Rival's private note/valuation never reaches us
    prof = ok(t, "get_player_profile", {"player_id": rival["shared_id"], "include_private_assessment": True})
    assert PRIVATE_NOTE not in json.dumps(prof) and "4242" not in json.dumps(prof)
    young = ok(t, "find_young_talents", {"max_age": 23, "positions": ["CB"], "min_minutes": 0, "limit": 50})
    assert rival["player_id"] not in [c["id"] for c in young["candidates"]]
    short = ok(t, "generate_shortlist", {"position": "CB", "metrics": ["pass_pct"], "min_minutes": 0, "limit": 20,
                                         "exclude_in_pipeline": False})
    assert rival["player_id"] not in [s["player"]["id"] for s in short["shortlist"]]


def test_rival_sees_its_own_records(B, rival):
    t = tok(B["H"]["sporting_director"])
    prof = ok(t, "get_player_profile", {"player_id": rival["player_id"], "include_private_assessment": True})
    assert prof["organisation_private"]["notes"] == PRIVATE_NOTE
    assert ok(t, "get_scouting_reports", {"report_id": rival["report_id"]})["report"]["player_id"] == rival["player_id"]


# --------------------------------------------------------------------------- permissions & privacy
def test_private_assessment_is_opt_in_and_financials_follow_rbac(client, H, rival):
    pid = rival["shared_id"]
    client.patch(f"/api/players/{pid}", headers=H["sporting_director"],
                 json={"notes": "demo club note", "estimated_fee": 1_500_000})
    director, scout = tok(H["sporting_director"]), tok(H["video_scout"])
    default = ok(director, "get_player_profile", {"player_id": pid})
    assert "organisation_private" not in default and "notes" not in default and "estimated_fee" not in default
    full = ok(director, "get_player_profile", {"player_id": pid, "include_private_assessment": True})
    assert full["organisation_private"]["notes"] == "demo club note"
    assert full["organisation_private"]["estimated_fee"] == 1_500_000
    assert "Do not send" in full["organisation_private"]["notice"]
    limited = ok(scout, "get_player_profile", {"player_id": pid, "include_private_assessment": True})
    assert "estimated_fee" not in limited["organisation_private"]
    assert limited["organisation_private"]["financials"] == "hidden for your role"
    # financial filters stay forbidden for roles without financials:read (enforced by the endpoint)
    assert ok(director, "get_club_requirements")["budgets"] != "hidden for your role"
    assert ok(scout, "get_club_requirements")["budgets"] == "hidden for your role"


def test_tool_permissions_cover_the_endpoints_they_call():
    for spec in list(READ_TOOLS.values()) + list(WRITE_TOOLS.values()):
        for endpoint in spec.routers:
            assert gateway.router_permissions(endpoint) <= set(spec.permissions), (spec.name, endpoint.__name__)
        assert spec.permissions, spec.name


def test_role_without_permission_is_denied_and_audited(client, H, demo_ids):
    before = last_audit_id()
    t = tok(H["data_analyst"])  # data analysts have no video:write
    noop = lambda *_: pytest.fail("must not ask for approval before authorisation")  # noqa: E731
    err, out = call(t, "add_video_observation", {"video_id": demo_ids["video_id"], "timestamp_seconds": 10,
                                                 "category": "passing"}, write=True, elicit=noop)
    assert out["error"] == "forbidden" and "video:write" in out["message"]
    rows = audit_rows(since=before)
    assert [r.action for r in rows] == ["mcp.tool_denied"] and rows[0].details["missing"] == ["video:write"]


# --------------------------------------------------------------------------- read-only tools
def test_every_read_tool_works_for_the_sporting_director(H, demo_ids):
    t = tok(H["sporting_director"])
    pid = demo_ids["cbs"][0]
    assert ok(t, "search_players", {"positions": ["CB"], "age_max": 30, "sort": "metric:aerial_pct",
                                    "order": "desc", "stat_filters": "aerial_pct>=40"})["total"] > 0
    prof = ok(t, "get_player_profile", {"player_id": pid})
    assert prof["id"] == pid and prof["seasons"]
    stats = ok(t, "get_player_statistics", {"player_id": pid})
    assert stats["season_lines"] and "metrics" in json.dumps(stats["analytics"]) and stats["notice"]
    young = ok(t, "find_young_talents", {"max_age": 23, "metric": "prog_passes_p90", "min_minutes": 0})
    assert young["candidates"] and all(c["age"] <= 23 for c in young["candidates"])
    assert "never a verdict" in young["notice"]
    cmp = ok(t, "compare_players", {"player_ids": demo_ids["cbs"][:3]})
    assert len(cmp["players"]) == 3
    req = ok(t, "get_club_requirements")
    assert req["positional_targets"] and req["derived_from"]
    board = ok(t, "get_recruitment_pipeline", {"stage": "identified"})
    assert list(board["columns"]) == ["identified"]
    assert ok(t, "get_recruitment_pipeline", {"player_id": demo_ids["entry"]["player_id"]})["entry"]["history"]
    assert ok(t, "get_scouting_reports")["reports"]
    assert ok(t, "get_scouting_reports", {"report_id": demo_ids["report_id"]})["report"]["sections"]
    short = ok(t, "generate_shortlist", {"position": "CB", "metrics": ["aerial_pct", "pass_pct"], "min_minutes": 0,
                                         "exclude_in_pipeline": False, "limit": 5})
    assert short["saved"] is False and 0 < len(short["shortlist"]) <= 5
    scores = [s["score"] for s in short["shortlist"]]
    assert scores == sorted(scores, reverse=True)
    text = json.dumps([young, short, stats]).lower()
    assert "guaranteed" not in text and "future star" not in text


def test_read_tools_change_nothing(client, H):
    t = tok(H["head_of_scouting"])
    snap = lambda: (client.get("/api/pipeline", headers=H["head_of_scouting"]).json()["total"],  # noqa: E731
                    len(client.get("/api/reports", headers=H["head_of_scouting"]).json()))
    before = snap()
    ok(t, "generate_shortlist", {"position": "ST", "metrics": ["npxg_p90"], "min_minutes": 0})
    ok(t, "get_club_requirements")
    assert snap() == before


def test_input_validation(H, demo_ids):
    t = tok(H["sporting_director"])
    bad = [("get_player_profile", {"player_id": -1}), ("get_player_profile", {"player_id": "1 OR 1=1"}),
           ("search_players", {"positions": ["XX"]}), ("search_players", {"page_size": 10_000}),
           ("search_players", {"stat_filters": "pass_pct>=1; DROP TABLE players"}),
           ("search_players", {"sort": "full_name; DELETE"}), ("search_players", {"query": "x" * 500}),
           ("compare_players", {"player_ids": [1]}), ("compare_players", {"player_ids": list(range(1, 8))}),
           ("find_young_talents", {"max_age": 30}), ("generate_shortlist", {"position": "CB", "metrics": []}),
           ("generate_shortlist", {"position": "CB", "metrics": ["not_a_metric"]}),
           ("get_player_statistics", {"player_id": 1, "season": "../../etc"})]
    for tool, args in bad:
        err, out = call(t, tool, args)
        assert err or out.get("error") == "invalid_input", (tool, args, out)
    # undeclared arguments never reach the tool (dropped by the schema layer)
    assert ok(t, "search_players", {"sql": "DROP TABLE players"})["total"] == ok(t, "search_players")["total"]
    # SQL-looking text in a name search is just a harmless search term
    assert ok(t, "search_players", {"query": "' OR '1'='1"})["total"] == 0
    assert call(t, "search_players", {"stat_filters": "unknown_metric>=1"})[1]["error"] == "invalid_input"


def test_no_raw_query_or_sql_tool_exists():
    tools = anyio.run(build_server(lambda: None, transport="t", write_tools=True).list_tools)
    for t in tools:
        props = set((t.input_schema or {}).get("properties", {}))
        assert not props & {"sql", "query_sql", "raw", "statement", "table"}, t.name
    assert {t.name for t in tools} == set(READ_TOOLS) | set(WRITE_TOOLS)


# --------------------------------------------------------------------------- write tools
def test_write_tools_are_not_exposed_by_default():
    names = {t.name for t in anyio.run(build_server(lambda: None, transport="t").list_tools)}
    assert names == set(READ_TOOLS) and not names & set(WRITE_TOOLS)


def _accept(approve=True):
    async def cb(_ctx, _params):
        return ElicitResult(action="accept", content={"approve": approve})
    return cb


async def _decline(_ctx, _params):
    return ElicitResult(action="decline")


def test_write_needs_human_approval_via_elicitation(client, H, demo_ids):
    t = tok(H["head_of_scouting"])
    entry = demo_ids["entry"]
    stage = lambda: client.get(f"/api/pipeline/{entry['id']}", headers=H["head_of_scouting"]).json()["stage"]  # noqa
    args = {"entry_id": entry["id"], "to_stage": "under_observation", "note": "Agent suggests watching him live"}
    before = last_audit_id()

    # client cannot ask a human -> refused by the protocol layer, nothing changes
    err, out = call(t, "update_recruitment_status", args, write=True, elicit=None)
    assert err and "elicitation capability" in out and stage() == "identified"
    # human declines / answers "no" -> nothing changes
    assert call(t, "update_recruitment_status", args, write=True, elicit=_decline)[1]["error"] == "declined"
    assert call(t, "update_recruitment_status", args, write=True, elicit=_accept(False))[1]["error"] == "declined"
    assert stage() == "identified"
    # human approves -> executed through the normal pipeline rules, with history and audit
    out = ok(t, "update_recruitment_status", args, write=True, elicit=_accept())
    assert out["updated"] and stage() == "under_observation"
    actions = [r.action for r in audit_rows(since=before)]
    assert actions.count("mcp.write_declined") == 2 and "mcp.write_executed" in actions
    executed = [r for r in audit_rows(since=before) if r.action == "mcp.write_executed"]
    assert len(executed) == 1 and executed[0].details["approval"] == "human_elicitation"
    assert any(r.action == "pipeline.move" for r in audit_rows("pipeline.", since=before))


def test_write_still_enforces_business_rules_and_rbac(client, H, demo_ids):
    # a video scout may move scouting stages but not approve signings (pipeline:approve)
    entry = demo_ids["entry"]
    t = tok(H["video_scout"])
    err, out = call(t, "update_recruitment_status", {"entry_id": entry["id"], "to_stage": "approved",
                                                     "note": "Approve please"}, write=True, elicit=_accept())
    assert out.get("error") in ("forbidden", "invalid_input", "conflict"), out
    # creating a report and an observation, both approved by the human
    hos = tok(H["head_of_scouting"])
    rep = ok(hos, "create_scouting_report", {"player_id": demo_ids["cbs"][0]}, write=True, elicit=_accept())
    assert rep["created"] and client.get(f"/api/reports/{rep['report_id']}", headers=H["head_of_scouting"]).status_code == 200
    obs = ok(hos, "add_video_observation", {"video_id": demo_ids["video_id"], "timestamp_seconds": 75,
                                            "category": "passing", "assessment": "positive",
                                            "technical_comment": "Good weight of pass"}, write=True, elicit=_accept())
    assert obs["created"]


def test_write_against_other_tenant_is_refused(B, H, rival):
    t = tok(H["head_of_scouting"])
    err, out = call(t, "update_recruitment_status", {"entry_id": rival["entry_id"], "to_stage": "under_observation",
                                                     "note": "cross-tenant attempt"}, write=True, elicit=_accept())
    assert out["error"] == "not_found"


# --------------------------------------------------------------------------- rate limiting & audit
def test_rate_limit_per_user(client, monkeypatch):
    org = create_org(client, "mcp-rate", "Rate FC", roles=["regional_scout"])
    t = tok(org["H"]["regional_scout"])
    monkeypatch.setattr(settings, "mcp_rate_limit_per_minute", 3)
    for _ in range(3):
        ok(t, "get_scouting_reports")
    out = call(t, "get_scouting_reports")[1]
    assert out["error"] == "rate_limited"
    assert audit_rows("mcp.rate_limited")[-1].user_email == "mcp-rate.regional_scout@example.com"


def test_every_call_is_audited_without_secrets(H, demo_ids):
    t = tok(H["data_analyst"])
    before = last_audit_id()
    ok(t, "get_player_profile", {"player_id": demo_ids["cbs"][0]})
    call(t, "get_player_profile", {"player_id": 99_999_999})
    rows = audit_rows(since=before)
    assert [r.action for r in rows] == ["mcp.tool_call", "mcp.tool_call"]
    assert [r.details["outcome"] for r in rows] == ["ok", "not_found"]
    for r in rows:
        assert r.details["tool"] == "get_player_profile" and r.user_email == "analyst@raja-scout.local"
        assert t not in json.dumps(r.details) and r.organization_id is not None


def test_internal_errors_do_not_leak(monkeypatch, H):
    def boom(*_a, **_k):
        raise RuntimeError("psycopg.OperationalError: password=hunter2 host=db.internal")
    spec = READ_TOOLS["get_club_requirements"]
    monkeypatch.setitem(READ_TOOLS, "get_club_requirements", gateway.ToolSpec(spec.name, boom, spec.permissions))
    out = call(tok(H["sporting_director"]), "get_club_requirements")[1]
    assert out["error"] == "internal_error" and "hunter2" not in json.dumps(out)


# --------------------------------------------------------------------------- external providers
class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body


def _opener(behaviour):
    def open_(req, timeout):
        if isinstance(behaviour, Exception):
            raise behaviour
        return _Resp(behaviour)
    return open_


def test_provider_failures_degrade_safely(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "sk-live-super-secret")
    cfg = ProviderConfig("thesportsdb", "https://example.invalid/api", key_env="TEST_PROVIDER_KEY", key_header="X-Key")
    cases = {
        "unavailable": TimeoutError("timed out"),
        "quota": urllib.error.HTTPError("u", 429, "Too Many", {}, None),
        "auth": urllib.error.HTTPError("u", 401, "sk-live-super-secret rejected", {}, None),
        "upstream": urllib.error.HTTPError("u", 503, "down", {}, None),
        "malformed": b"<html>not json</html>",
    }
    for kind, behaviour in cases.items():
        with pytest.raises(ProviderError) as e:
            ProviderClient(cfg, opener=_opener(behaviour)).get_json("leagues", {"country": "Morocco"})
        assert e.value.kind == kind and "sk-live-super-secret" not in str(e.value)
    assert ProviderClient(cfg, opener=_opener(b'{"leagues": []}')).get_json("leagues") == {"leagues": []}


def test_provider_policy_blocks_unverified_sources_and_private_data(monkeypatch):
    for name in ("sportmonks", "api_football", "sportapi", "football_data_org", "statsbomb_open", "unknown"):
        with pytest.raises(ProviderNotAllowed):
            ProviderClient(ProviderConfig(name, "https://example.invalid"))
    with pytest.raises(ProviderNotAllowed):
        ProviderClient(ProviderConfig("thesportsdb", "http://plain-http.invalid"))
    c = ProviderClient(ProviderConfig("thesportsdb", "https://example.invalid"), opener=_opener(b"{}"))
    with pytest.raises(ProviderNotAllowed):
        c.get_json("players", {"name": "X", "notes": "our private opinion"})
    with pytest.raises(ProviderError):  # key configured as required but missing
        ProviderClient(ProviderConfig("thesportsdb", "https://example.invalid", key_env="MISSING_KEY_X",
                                      key_header="X-Key"), opener=_opener(b"{}")).get_json("x")


def test_mcp_server_is_separate_from_provider_adapters():
    import pathlib
    src = "".join(p.read_text() for p in pathlib.Path(gateway.__file__).parent.glob("*.py"))
    assert "app.providers" not in src and "..providers" not in src
    assert "urllib" not in src and "httpx" not in src  # the MCP server makes no outbound calls
