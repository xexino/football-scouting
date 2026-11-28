"""The public static demo export: file naming contract with frontend/static-demo.js and the
safety guarantee that only fictional demo data is exported."""
from pathlib import Path

from tools.export_static import file_name

JS = (Path(__file__).resolve().parents[2] / "frontend" / "static-demo.js").read_text()


def test_file_name_contract():
    assert file_name("auth/me") == "auth__me.json"
    assert file_name("players/12/analytics", {"season": "2024-25"}) == "players__12__analytics__season=2024-25.json"
    assert file_name("admin/audit-logs", {"limit": 150}) == "admin__audit-logs__limit=150.json"
    assert file_name("videos", {"player_id": 7}) == "videos__player_id=7.json"
    # parameters are sorted, as in the JS implementation
    assert file_name("x", {"b": 1, "a": 2}) == "x__a=2&b=1.json"


def test_static_shim_refuses_writes_and_never_holds_keys():
    assert "if (method !== 'GET') return json(READ_ONLY, 403);" in JS
    assert "fileFor" in JS and "search_index.json" in JS
    for forbidden in ("x-apisports-key", "X-Auth-Token", "api_token", "SECRET"):
        assert forbidden not in JS


def test_export_refuses_non_demo_data():
    src = (Path(__file__).resolve().parents[1] / "tools" / "export_static.py").read_text()
    assert 'Refusing to export: not a demo organization' in src
    assert 'Refusing to export: non-fictional players present' in src
