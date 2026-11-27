"""Stage 2: organization identity, branding and independence from any single club."""
import base64

import pytest

from conftest import create_org, stat_line

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'


@pytest.fixture(scope="module")
def C(client):
    return create_org(client, "atlas-ac", "Atlas Athletic Club", currency="MAD")


def test_get_organization_for_any_member(client, C):
    o = client.get("/api/organization", headers=C["H"]["video_scout"]).json()
    assert o["name"] == "Atlas Athletic Club" and o["currency"] == "MAD" and "MAD" in o["options"]["currencies"]
    me = client.get("/api/auth/me", headers=C["H"]["video_scout"]).json()
    assert me["organization"]["slug"] == "atlas-ac" and me["role"] == "video_scout"


def test_only_org_admin_can_update(client, C):
    assert client.patch("/api/organization", headers=C["H"]["sporting_director"], json={"name": "X"}).status_code == 403
    r = client.patch("/api/organization", headers=C["H"]["administrator"], json={
        "name": "Atlas AC", "short_name": "ATL", "country": "Morocco", "primary_language": "fr",
        "currency": "eur", "timezone": "Africa/Casablanca",
        "settings": {"home_league": "Botola Pro", "report_footer": "Confidential — Atlas AC", "accent_color": "#1a7f37"}})
    assert r.status_code == 200, r.text
    o = r.json()
    assert (o["name"], o["short_name"], o["primary_language"], o["currency"]) == ("Atlas AC", "ATL", "fr", "EUR")
    assert o["settings"] == {"home_league": "Botola Pro", "report_footer": "Confidential — Atlas AC", "accent_color": "#1a7f37"}
    # clearing a setting removes it
    o = client.patch("/api/organization", headers=C["H"]["administrator"], json={"settings": {"accent_color": ""}}).json()
    assert "accent_color" not in o["settings"] and o["settings"]["home_league"] == "Botola Pro"


@pytest.mark.parametrize("body", [
    {"currency": "XYZ"}, {"primary_language": "de"}, {"timezone": "Mars/Base"},
    {"settings": {"unknown": "x"}}, {"settings": {"accent_color": "red"}}, {"name": ""},
])
def test_invalid_updates_rejected(client, C, body):
    assert client.patch("/api/organization", headers=C["H"]["administrator"], json=body).status_code == 422


def test_logo_upload_validates_content(client, C):
    h = C["H"]["administrator"]
    up = lambda data, ctype: client.post("/api/organization/logo", headers=h, files={"file": ("logo", data, ctype)})  # noqa: E731
    assert up(SVG, "image/svg+xml").status_code == 422
    assert up(SVG, "image/png").status_code == 422          # spoofed content type
    assert up(PNG + b"\0" * (256 * 1024), "image/png").status_code == 413
    assert client.post("/api/organization/logo", headers=C["H"]["sporting_director"],
                       files={"file": ("l.png", PNG, "image/png")}).status_code == 403
    r = up(PNG, "image/png")
    assert r.status_code == 200 and r.json()["logo_data_url"].startswith("data:image/png;base64,")
    assert client.delete("/api/organization/logo", headers=h).status_code == 204
    assert client.get("/api/organization", headers=h).json()["logo_data_url"] is None


def test_branding_is_per_organization(client, H, C):
    client.patch("/api/organization", headers=C["H"]["administrator"], json={"name": "Atlas Renamed"})
    assert client.get("/api/organization", headers=H["video_scout"]).json()["name"] == "Demo FC (fictional)"
    logs = client.get("/api/admin/audit-logs?action=organization.", headers=H["administrator"]).json()
    assert not any(l["entity_id"] == C["id"] for l in logs)


def test_currency_and_home_league_flow_into_outputs(client, C):
    h = C["H"]["head_of_scouting"]
    client.patch("/api/organization", headers=C["H"]["administrator"], json={
        "currency": "MAD", "settings": {"home_league": "Botola Pro", "report_footer": "Atlas confidential"}})
    src = client.post("/api/data-sources", headers=h, json={"name": "Atlas feed", "source_type": "manual",
                                                             "license_notes": "own"}).json()
    p = client.post("/api/players", headers=h, json={"full_name": "Atlas Target", "nationality": "Mali",
                                                       "primary_position": "ST", "estimated_fee": 3_000_000,
                                                       "data_source_id": src["id"]}).json()
    assert p["currency"] == "MAD" and p["estimated_fee"] == 3_000_000
    client.post(f"/api/players/{p['id']}/stats", headers=h, json=stat_line(src["id"], minutes=500))
    rep = client.post("/api/reports/generate", headers=h, json={"player_id": p["id"]}).json()
    risk = rep["sections"]["potential_risk"]["items"][0]["text"]
    assert "Botola Pro" in risk or "league strength" not in risk
    md = client.get(f"/api/reports/{rep['id']}/export.md", headers=h).text
    assert "Atlas" in md and "Atlas confidential" in md and "independent software" in md
    d = client.get("/api/dashboard", headers=C["H"]["sporting_director"]).json()
    assert d["budget"]["currency"] == "MAD"


def test_product_does_not_present_itself_as_a_club(client):
    desc = client.get("/openapi.json").json()["info"]["description"]
    assert "not affiliated with or endorsed by Raja Club Athletic" in desc
    assert "platform for Raja Club Athletic" not in desc
    js = client.get("/static/app.js").text
    assert "Raja holds a licence" not in js and "data Raja is licensed" not in js
    assert "not affiliated with, endorsed or sponsored by Raja Club Athletic" in js
