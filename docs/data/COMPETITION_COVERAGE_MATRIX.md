# Competition coverage matrix (tested)

**Probe date:** 2026-11-28 · **Method:** real API responses, reproducible with
`cd backend && python -m tools.coverage_probe ../docs/data/evidence/coverage_probe.json`
(raw evidence in `docs/data/evidence/`). Only sources reachable **without a key** were tested;
API-Football and Sportmonks keys were not provided, so they are **NOT TESTED** (§3).

Legend: ✅ tested & present · ⚠️ present but limited (see note) · ❌ tested & absent ·
— not applicable · **NT** not tested.

## 1. Target competitions

| # | Competition | football-data.org (catalogue) | TheSportsDB (free key 123) — league / players in squads | OpenFootball (public domain) | StatsBomb open (non-commercial) | API-Football | Sportmonks |
|---|---|---|---|---|---|---|---|
| 1 | Morocco Botola Pro | ❌ not listed | ⚠️ league ✅ (id 4520, season 2026-2027); **19 players across 10 clubs**, 3 clubs empty, 1 player born ≥2003 | ❌ no file | ❌ | NT | NT |
| 2 | Morocco Botola 2 | ❌ | ⚠️ league ✅ (4657); **2 players across 10 clubs** | ❌ | ❌ | NT | NT |
| 3 | Tunisia Ligue 1 | ❌ | ⚠️ league ✅ (4828); 23 players / 10 clubs, 5 empty | ❌ | ❌ | NT | NT |
| 4 | Egypt Premier League | ❌ | ✅ league (4829); 20 players in 2 clubs sampled, DOB/nat 100 %, position 95 % | ❌ | ❌ | NT | NT |
| 5 | Senegal Ligue 1 | ❌ | ⚠️ league ✅ (4754); 8 players / 10 clubs (all born ≥2003) | ❌ | ❌ | NT | NT |
| 6 | Nigeria NPFL | ❌ | ⚠️ league ✅ (4827); **0 players across 10 clubs** | ❌ | ❌ | NT | NT |
| 7 | Ghana Premier League | ❌ | ⚠️ league ✅ (4974); 4 players / 10 clubs | ❌ | ❌ | NT | NT |
| 8 | South Africa Premiership | ⚠️ listed, TIER_FOUR (most expensive), last updated 2021-04-17 | ✅ league (4802); 20 players sampled, fields 100 % | ❌ | ❌ | NT | NT |
| 9 | English Premier League | ✅ TIER_ONE (free plan) | ✅ (4328); 20 sampled, DOB/nat/pos 100 % | ✅ 2025-26, 380 matches | ⚠️ 2 historic seasons (latest 2015/16) | NT | NT |
| 10 | French Ligue 1 | ✅ TIER_ONE | ✅ (4334); 100 % | ✅ 306 matches | ⚠️ 3 seasons (latest 2022/23) | NT | NT |
| 11 | Portuguese Primeira Liga | ✅ TIER_ONE | ✅ (4344); position 95 % | ✅ 306 matches | ❌ | NT | NT |
| 12 | Belgian Pro League | ⚠️ TIER_TWO (paid) | ✅ (4338); 100 % | ✅ 240 matches | ❌ | NT | NT |
| 13 | Dutch Eredivisie | ✅ TIER_ONE | ✅ (4337); 100 % | ✅ 306 matches | ❌ | NT | NT |
| 14 | Brazilian Serie A | ✅ TIER_ONE | ✅ (4351); 100 % | ✅ 2025, 380 matches | ❌ | NT | NT |
| 15 | Argentine Primera División | ⚠️ TIER_TWO (paid) | ✅ (4406); position 95 % | ✅ 2025, 240 matches | ⚠️ 2 seasons (1997/98) | NT | NT |
| 16 | Uruguay Primera División | ⚠️ TIER_FOUR | ✅ (4432); 10 players sampled, 100 % | ❌ | ❌ | NT | NT |
| 17 | Colombia Primera A | ⚠️ TIER_FOUR | ✅ (4497); 10 sampled, 100 % (only 1 club returned) | ❌ | ❌ | NT | NT |

## 2. Player fields actually returned

| Field | football-data.org | TheSportsDB | OpenFootball | StatsBomb open | Wikidata (CC0) |
|---|---|---|---|---|---|
| Birth date / age | squads = paid add-on (403 without token) | ✅ `dateBorn` | ❌ no players | ❌ not in lineups | ✅ P569 (see §5) |
| Position | paid | ✅ `strPosition` (free text: "Attacker", "Right-Back") | ❌ | ✅ per match (event data) | ⚠️ P413 where entered |
| Nationality | paid | ✅ `strNationality` | ❌ | ✅ `country` | ✅ P27 |
| Club | paid | ✅ `strTeam` | — | ✅ per match | ✅ P54 (current = no end date) |
| Height / foot | — | height ✅, foot mostly empty | ❌ | ❌ | ⚠️ sparse |
| Appearances / minutes | ❌ | ❌ (no player stats endpoint) | ❌ | ✅ derivable from events (research only) | ❌ |
| Goals / assists | scorers = paid | ❌ | ❌ (goals per match in some files) | ✅ events (research only) | ❌ |
| Advanced (xG, progressive…) | ❌ | ❌ | ❌ | ✅ (research only) | ❌ |
| Cross-provider IDs | own ids | ✅ `idAPIfootball`, `idTransferMkt`, `idESPN` | — | own ids | ✅ many external IDs |
| Special-category data | — | ⚠️ `strEthnicity` present → **never import** | — | — | ⚠️ may hold sensitive properties → whitelist only |

## 3. Not tested — and why

* **API-Football** — every request needs a key (`HTTP 403 Missing application key`, tested);
  the free-key request was declined. Its website is behind a Cloudflare bot challenge, so its
  coverage list could not be read either. All API-Football coverage claims are **UNVERIFIED**.
* **Sportmonks** — every request needs a key (`HTTP 401 No token provided`, tested); website
  pages return 403 (bot protection). Secondary sources say the free plan covers only the Danish
  Superliga and Scottish Premiership — neither is a target competition.
* **Wyscout** — no free API; access through Hudl sales ("Contact Sales / Request a Demo").

## 4. Youth and reserve competitions

| Source | Result |
|---|---|
| football-data.org | ❌ none of 192 catalogue competitions is U17/U19/U20/U21/U23/reserve (tested) |
| TheSportsDB | ⚠️ not determinable with the free key: league lists are truncated (10 of all leagues, 5 per country) — UNVERIFIED |
| OpenFootball | ❌ no youth files found |
| StatsBomb open | ⚠️ only *FIFA U20 World Cup 1979* (research only) |
| Wyscout | advertises a "Youth Competitions Pack" (paid, not tested) |
| API-Football | NT |

**Conclusion:** no free, commercially usable source tested here provides youth-competition
data or player statistics for African leagues.

## 5. Wikidata (CC0)

See `docs/data/evidence/wikidata_young_players_sample.json` and §5 of the provider comparison.
The endpoint was enforcing an emergency limit of 1 request/minute and `Retry-After: 1000`
during testing (2026-11-28).

## 6. Free-key truncation observed (affects any "free" plan)

* TheSportsDB free key: ≤10 clubs per league search, ≤10 players per club, 5 leagues per
  country search, `all_leagues` returns 10 — the old key `3` is permanently disabled.
* football-data.org without token: competition list only (100 requests/24 h); registered free:
  10 requests/minute, delayed scores, no squads/scorers.
