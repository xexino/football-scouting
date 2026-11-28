"""Build the public, read-only static demo for GitHub Pages.

Boots the real application in DEPLOYMENT_MODE=demo on a throwaway SQLite database (fictional
seed data only), signs in as the demo Sporting Director and saves every API response the
frontend needs as JSON. ``frontend/static-demo.js`` then serves those files in the browser
(including search, filters, sorting and comparison) and refuses every write.

Safety: the export aborts unless the organization is a demo organization and every exported
player is fictional — the site is public.

Usage (from backend/):  python -m tools.export_static ../site
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def file_name(path: str, params: dict | None = None) -> str:
    """Must match ``fileFor`` in frontend/static-demo.js."""
    q = "&".join(f"{k}={v}" for k, v in sorted((k, str(v)) for k, v in (params or {}).items()))
    name = path.replace("/", "__") + (f"__{q}" if q else "")
    return re.sub(r"[^A-Za-z0-9_=&.-]", "_", name) + ".json"


def build(out_dir: Path) -> dict:
    tmp = tempfile.mkdtemp(prefix="rsi-static-")
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/demo.db"
    os.environ["DEPLOYMENT_MODE"] = "demo"
    os.environ["RAJA_ENV"] = "development"
    os.environ.setdefault("DEMO_PASSWORD", "RajaDemo2026!")
    from fastapi.testclient import TestClient

    from app.main import app

    if out_dir.exists():
        shutil.rmtree(out_dir)
    data = out_dir / "data"
    data.mkdir(parents=True)
    count = 0

    with TestClient(app) as c:
        tok = c.post("/api/auth/token", data={"username": "director@raja-scout.local",
                                              "password": os.environ["DEMO_PASSWORD"]})
        tok.raise_for_status()
        h = {"Authorization": f"Bearer {tok.json()['access_token']}"}

        def save(path: str, params: dict | None = None):
            nonlocal count
            r = c.get(f"/api/{path}", params=params, headers=h)
            if r.status_code != 200:
                raise RuntimeError(f"/api/{path} {params} -> {r.status_code}: {r.text[:200]}")
            body = r.json()
            (data / file_name(path, params)).write_text(json.dumps(body, ensure_ascii=False, default=str),
                                                        encoding="utf-8")
            count += 1
            return body

        me = save("auth/me")
        if not (me.get("organization") or {}).get("is_demo"):
            raise RuntimeError("Refusing to export: not a demo organization")
        for p in ("meta", "subscription", "organization", "public/config", "dashboard", "leagues", "clubs",
                  "data-sources", "videos", "match-reports", "reports", "budgets", "users/roles",
                  "users/directory"):  # the demo director cannot manage members, so the UI never asks
            save(p)
        save("admin/audit-logs", {"limit": 150})
        save("pipeline/events", {"limit": 15})
        board = save("pipeline")

        players = c.get("/api/players", params={"page_size": 200}, headers=h).json()
        if players["total"] > 200:
            raise RuntimeError("Static export supports at most 200 players")
        if not all(p["is_fictional"] for p in players["items"]):
            raise RuntimeError("Refusing to export: non-fictional players present")
        search_index = []
        for p in players["items"]:
            pid = p["id"]
            detail = save(f"players/{pid}")
            latest = save(f"players/{pid}/analytics")
            for season in sorted({s["season"] for s in detail.get("stats", [])}) + ["all"]:
                save(f"players/{pid}/analytics", {"season": season})
            save("videos", {"player_id": pid})
            save("match-reports", {"player_id": pid})
            save("reports", {"player_id": pid})
            save(f"pipeline/player/{pid}")
            search_index.append({**p, "_metrics": latest.get("all_metrics") or {},
                                 "_minutes": latest.get("minutes")})
        (data / "search_index.json").write_text(json.dumps(search_index, ensure_ascii=False, default=str),
                                                encoding="utf-8")
        for col in board["columns"].values():
            for e in col:
                save(f"pipeline/{e['id']}")
        for rep in c.get("/api/reports", headers=h).json():
            save(f"reports/{rep['id']}")

    # Frontend: relative asset paths (GitHub Pages serves the site under /<repo>/)
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/styles.css"', 'href="styles.css"')
    html = html.replace('<script src="/static/app.js"></script>',
                        '<script src="static-demo.js"></script>\n  <script src="app.js"></script>')
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    for f in ("styles.css", "app.js", "static-demo.js"):
        shutil.copy(FRONTEND / f, out_dir / f)
    (out_dir / ".nojekyll").write_text("")
    shutil.rmtree(tmp, ignore_errors=True)
    return {"files": count + 1, "players": len(search_index)}


if __name__ == "__main__":
    result = build(Path(sys.argv[1] if len(sys.argv) > 1 else "../site").resolve())
    print(f"static demo built: {result}")
