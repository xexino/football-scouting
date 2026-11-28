"""Competition coverage probe — reproducible evidence for docs/data/COMPETITION_COVERAGE_MATRIX.md.

Tests REAL responses from keyless sources only (no keys are read, stored or sent):
  * football-data.org  — public competition catalogue (plan tier per competition)
  * TheSportsDB        — public test key "123" (30 req/min; free key truncates lists)
  * OpenFootball       — public-domain fixtures (raw GitHub files)
  * StatsBomb open     — competition list (non-commercial licence: research only)

API-Football and Sportmonks need keys and are NOT probed here.

Usage (from backend/):  python -m tools.coverage_probe ../docs/data/evidence/coverage_probe.json
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "RajaScoutIntelligence-coverage-probe/0.1"
TSDB = "https://www.thesportsdb.com/api/v1/json/123"
FDO = "https://api.football-data.org/v4/competitions"
OPENFOOTBALL = "https://raw.githubusercontent.com/openfootball/football.json/master"
STATSBOMB = "https://raw.githubusercontent.com/statsbomb/open-data/master/data/competitions.json"

# name, country, TheSportsDB league id (verified by lookup), football-data code, OpenFootball file
TARGETS = [
    ("Botola Pro", "Morocco", "4520", None, None),
    ("Botola 2", "Morocco", "4657", None, None),
    ("Tunisia Ligue 1", "Tunisia", "4828", None, None),
    ("Egypt Premier League", "Egypt", "4829", None, None),
    ("Senegal Ligue 1", "Senegal", "4754", None, None),
    ("Nigeria NPFL", "Nigeria", "4827", None, None),
    ("Ghana Premier League", "Ghana", "4974", None, None),
    ("South Africa Premiership", "South Africa", "4802", None, None),
    ("English Premier League", "England", "4328", "PL", "2025-26/en.1.json"),
    ("French Ligue 1", "France", "4334", "FL1", "2025-26/fr.1.json"),
    ("Portuguese Primeira Liga", "Portugal", "4344", "PPL", "2025-26/pt.1.json"),
    ("Belgian Pro League", "Belgium", "4338", "BJL", "2025-26/be.1.json"),
    ("Dutch Eredivisie", "Netherlands", "4337", "DED", "2025-26/nl.1.json"),
    ("Brazilian Serie A", "Brazil", "4351", "BSA", "2025/br.1.json"),
    ("Argentine Primera Division", "Argentina", "4406", "ASL", "2025/ar.1.json"),
    ("Uruguay Primera Division", "Uruguay", "4432", "UPD", None),
    ("Colombia Primera A", "Colombia", "4497", "CLP", None),
]
YOUTH_QUERIES = ["U19", "U20", "U21", "U23", "Youth", "Premier League 2", "Primavera", "Reserve", "Juniors", "Jong"]
PLAYER_FIELDS = ["dateBorn", "strNationality", "strPosition", "strHeight", "strTeam", "strFoot",
                 "idAPIfootball", "idTransferMkt"]


class Limiter:
    def __init__(self, per_minute: int):
        self.gap = 60.0 / per_minute + 0.05
        self.last = 0.0

    def wait(self):
        d = time.monotonic() - self.last
        if d < self.gap:
            time.sleep(self.gap - d)
        self.last = time.monotonic()


TSDB_LIMIT = Limiter(28)  # documented free limit: 30 requests / minute


def get_json(url: str, limiter: Limiter | None = None, retries: int = 3):
    for attempt in range(retries):
        if limiter:
            limiter.wait()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(int(e.headers.get("Retry-After") or 61))
                continue
            return e.code, None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == retries - 1:
                return 0, {"error": str(e)}
            time.sleep(3)
    return 0, None


def probe_tsdb(league_id: str) -> dict:
    out = {"league_found": False}
    code, d = get_json(f"{TSDB}/lookupleague.php?id={league_id}", TSDB_LIMIT)
    if not d or not d.get("leagues"):
        return {**out, "http": code}
    lg = d["leagues"][0]
    out.update(league_found=True, league_name=lg.get("strLeague"), current_season=lg.get("strCurrentSeason"))
    code, d = get_json(f"{TSDB}/search_all_teams.php?l={urllib.parse.quote(lg['strLeague'])}", TSDB_LIMIT)
    teams = (d or {}).get("teams") or []
    out["teams_returned_free_key"] = len(teams)
    players = []
    for t in teams[:2]:
        code, d = get_json(f"{TSDB}/lookup_all_players.php?id={t['idTeam']}", TSDB_LIMIT)
        players += (d or {}).get("player") or []
    out["players_sampled"] = len(players)
    out["field_fill_rate"] = {f: round(sum(1 for p in players if p.get(f) not in (None, "", "0")) / len(players), 2)
                              for f in PLAYER_FIELDS} if players else {}
    out["season_stats_available"] = False  # TheSportsDB has no per-player season statistics endpoint
    return out


def main(path: str) -> None:
    started = datetime.now(timezone.utc).isoformat()
    _, fdo = get_json(FDO)
    fdo_by_code = {c.get("code"): c for c in (fdo or {}).get("competitions", [])}
    _, sb = get_json(STATSBOMB)
    sb_names = sorted({f"{c['country_name']} / {c['competition_name']}" for c in (sb or [])})
    rows = []
    for name, country, tsdb_id, fdo_code, of_file in TARGETS:
        print("probing", name, flush=True)
        c = fdo_by_code.get(fdo_code) if fdo_code else None
        of_status = None
        if of_file:
            of_status, of = get_json(f"{OPENFOOTBALL}/{of_file}")
            of_status = {"http": of_status, "matches": len((of or {}).get("matches", [])) if of else 0,
                         "has_players": False}
        rows.append({
            "competition": name, "country": country,
            "football_data_org": ({"listed": True, "plan": c["plan"], "seasons": c["numberOfAvailableSeasons"],
                                   "last_updated": c["lastUpdated"]} if c else {"listed": False}),
            "thesportsdb": probe_tsdb(tsdb_id),
            "openfootball": of_status or {"file": None},
            "statsbomb_open": [n for n in sb_names if country.split()[0] in n or name.split()[0] in n],
        })
    _, d = get_json(f"{TSDB}/all_leagues.php", TSDB_LIMIT)
    all_leagues = (d or {}).get("leagues") or []
    youth = {"all_leagues_total_free_key": len(all_leagues),
             "youth_or_reserve_leagues": sorted(l["strLeague"] for l in all_leagues
                                                if any(k.lower() in l["strLeague"].lower() for k in YOUTH_QUERIES))}
    fdo_youth = sorted(c["name"] for c in (fdo or {}).get("competitions", [])
                       if any(k in c["name"] for k in ("U17", "U19", "U20", "U21", "U23", "Youth", "Reserve")))
    result = {"probed_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
              "sources": {"football_data_org_competitions": len(fdo_by_code), "statsbomb_competition_seasons": len(sb or [])},
              "competitions": rows,
              "youth": {"thesportsdb": youth, "football_data_org": fdo_youth,
                        "statsbomb_open": [n for n in sb_names if "U20" in n or "U17" in n or "Youth" in n]}}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("written", path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "coverage_probe.json")
