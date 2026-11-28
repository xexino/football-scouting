# Global football data provider comparison

**Date:** 2026-11-28 · **Goal:** a legally usable data foundation for young-player (16–23)
discovery in Africa, Europe and South America. Companion documents:
`COMPETITION_COVERAGE_MATRIX.md` (tested per competition), `DATA_LICENSING_REGISTER.md`.

**Evidence levels** used below: **TESTED** = real API responses from this environment
(`docs/data/evidence/`) · **OFFICIAL** = read on the provider's own page (quoted) ·
**SECONDARY** = search results / third-party pages only · **UNVERIFIED** = could not be confirmed.
No keys were used; no purchases were made.

## 1. Summary

| Provider | Access tested | Free limits | Commercial use | Morocco Botola Pro / 2 | South America (BRA/ARG/URU/COL) | Player DOB · pos · nat | Minutes / goals / advanced | Youth comps | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **API-Football** | ❌ key required (TESTED 403); site behind Cloudflare challenge | 100 req/day, all endpoints (SECONDARY) | **UNVERIFIED** | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | Most promising *candidate* for African leagues — **must be tested with a free key** before any decision |
| **Sportmonks** | ❌ key required (TESTED 401); site 403 | free: Danish Superliga + Scottish Premiership only, ~180 calls/h (SECONDARY) | **UNVERIFIED** | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | UNVERIFIED | Free plan useless for targets; paid evaluation only |
| **Wyscout (Hudl)** | ❌ no free API (OFFICIAL: "Contact Sales") | none | contract only | UNVERIFIED (claims 1000+ competitions) | UNVERIFIED | UNVERIFIED | UNVERIFIED | "Youth Competitions Pack" (OFFICIAL, paid) | Best-known pro scouting source; founder decision (paid) |
| **StatsBomb Open Data** | ✅ TESTED (80 competition-seasons) | GitHub, no key | **❌ VERIFIED NO** — licence §1.2.2 "may not… commercially exploit the data or any analysis derived" | ❌ | Copa América 2024; Argentina 1997/98 only | nationality ✅, **no DOB** | ✅ event-level (research only) | U20 WC 1979 only | **Research/methodology only — never in the product** |
| **OpenFootball** | ✅ TESTED | GitHub, no key | ✅ public domain (OFFICIAL README) | ❌ | ✅ BRA, ARG (fixtures) | ❌ no players | ❌ (match scores only) | ❌ | Use for fixtures / club & competition reference data |
| **football-data.org** | ✅ TESTED (catalogue, 192 comps) | no token: 100 req/24 h, lists only; free account: 10 req/min, delayed scores (OFFICIAL) | **UNVERIFIED** (no terms page found; 404) | ❌ not listed | BRA ✅ free; ARG paid tier; URU/COL top tier | squads = paid add-on €29+/month (OFFICIAL) | scorers = paid | ❌ none | No African club leagues → not suitable for the core goal |
| **TheSportsDB** | ✅ TESTED (17 leagues, squads) | key `123`, 30 req/min (OFFICIAL); lists truncated | ✅ data: "You may publicly display API data and monetise projects… on both the free tier and paid plans" (OFFICIAL); images: per-image licence | ✅ leagues, ⚠️ **19 players / 10 clubs**; Botola 2: 2 | ✅ leagues, ~10 players per club | ✅ DOB, nationality, position, height | ❌ no player statistics | UNVERIFIED (free list truncated) | Usable for *identity & cross-IDs* in Europe/S. America; too sparse in Africa |
| **Wikidata** (added) | ⚠️ reachable, **queries refused (429, outage rule)** — coverage NOT MEASURED (§5) | SPARQL; emergency limit 1 req/min, Retry-After 1000 s during test | expected CC0 — licence page to be archived (UNVERIFIED) | NOT MEASURED | NOT MEASURED | data model has DOB, citizenship, position, club | ❌ | ❌ | Best legally clean **identity** source *in principle*; coverage still to be measured |

## 2. Findings that change the plan

1. **No tested free source covers African players with statistics.** football-data.org lists
   none of the seven African target leagues; TheSportsDB lists them but holds almost no squads
   (Nigeria NPFL: 0 players across 10 clubs).
2. **StatsBomb open data is legally excluded** from a commercial SaaS (licence verified).
3. **Statistics (minutes, goals, assists) for Botola and other African leagues** can only come
   from a keyed/paid provider (API-Football — to be tested; Wyscout — paid) or from the club's
   own scouting/match data.
4. **Free tiers truncate silently** (TheSportsDB: ≤10 clubs, ≤10 players; football-data.org:
   delayed data, no squads). Any import must record coverage gaps instead of treating missing
   rows as "no players".
5. **Personal-data hazard:** TheSportsDB returns `strEthnicity`; Wikidata can hold sensitive
   properties. Importers must use a field whitelist.
6. **Data quality:** football-data.org files the *AFC* (Asian) Champions League under area
   "Africa" — provider data needs validation, not blind trust.

## 3. Provider details

### API-Football (api-sports.io)
* TESTED: `GET https://v3.football.api-sports.io/status` → 403 "Missing application key".
* SECONDARY (search results quoting api-football.com): free plan "access to the entire API",
  100 requests/day reset 00:00 UTC; paid Pro 7,500/day, Ultra 75,000/day. Per-minute limit
  sources disagree (10 vs 30). No confirmed free-plan season restriction.
* OFFICIAL pages (`/terms`, `/pricing`, `/coverage`) returned a Cloudflare challenge
  (`cf-mitigated: challenge`); not bypassed by policy → terms and Botola coverage **UNVERIFIED**.
* TheSportsDB player records carry `idAPIfootball`, so API-Football ids could be linked later.

### Sportmonks
* TESTED: `GET https://api.sportmonks.com/v3/football/leagues` → 401 "No token provided".
* SECONDARY: free plan = Danish Superliga (id 271) + Scottish Premiership (id 501), "180 API
  calls per hour/entity"; other leagues need a paid plan (14-day trial).
* OFFICIAL terms/pricing/coverage pages exist (sitemap) but return 403 → **UNVERIFIED**.

### Wyscout (Hudl)
* OFFICIAL (hudl.com/products/wyscout): "Comprehensive soccer data API for performance,
  scouting and recruitment analysis"; "We collect data and video from more than 1000
  competitions worldwide"; "Youth Competitions Pack"; access via "Contact Sales / Request a Demo".
* No free tier; nothing tested. Requires founder approval before any contact or purchase.

### StatsBomb Open Data
* TESTED: 80 competition-seasons; recent senior internationals (AFCON 2023 — 52 matches,
  Copa América 2024, Euro 2024), Ligue 1 up to 2022/23; lineups contain name, nationality,
  jersey, positions — **no birth date**.
* OFFICIAL licence (`LICENSE.pdf`, "StatsBomb Public Data User Agreement"): user may not
  "distribute, reproduce, sell or in any way provide the data to any external or third party"
  (§1.2.1) nor "commercially exploit the data or any analysis derived from the use of the
  Service" (§1.2.2). README asks for attribution + logo when publishing research.

### OpenFootball
* TESTED: 2025-26 files for England (380 matches), France, Portugal, Netherlands (306),
  Belgium (240), 2025 Brazil (380) and Argentina (240); no Morocco file (404).
  Match objects contain only `date, round, score, team1, team2, time`.
* OFFICIAL README: "Free open public domain football (match fixtures & results) data".

### football-data.org
* TESTED: catalogue of 192 competitions with plan tier per competition. Free (`TIER_ONE`):
  Premier League, Championship, Bundesliga, Serie A, LaLiga, Ligue 1, Eredivisie, Primeira Liga,
  Brasileirão Série A, Champions League, Euro, World Cup. Belgium and Argentina = TIER_TWO;
  Uruguay, Colombia, South Africa = TIER_FOUR; **no Moroccan, Tunisian, Egyptian, Senegalese,
  Nigerian or Ghanaian league**. `/competitions/PL/teams` without token → 403.
* OFFICIAL (pricing): "Free Plan is Free Forever"; free = scores & schedules delayed; squads
  and goal scorers in paid packages (e.g. "Free + Deep Data" €29/month). OFFICIAL (policies):
  "Registered clients are allowed for 10 requests/minute in the free plan"; anonymous clients
  "100 requests per 24 hours and can only access the area and competition list resources".
* Terms of use page not found (`/terms` → 404) → commercial use **UNVERIFIED**.

### TheSportsDB
* TESTED: test key `123` works (old key `3` → 403 "permanently disabled"); all 17 target
  leagues found; squads sparse for African leagues (matrix §1).
* OFFICIAL (docs_api_guide): "Free users 30 requests per minute. Premium 100 per minute";
  V2 API premium-only. OFFICIAL (docs_terms_of_use.php): data may be displayed and monetised
  on the free tier; "Please do not scrape our website"; "You cannot publish apps to an appstore
  unless you are a paid subscriber"; artwork under per-image Creative Commons — images with
  unknown licence "must not be used… publicly".

### Wikidata (additional source)
* CC0 (public domain) structured data with birth date (P569), citizenship (P27), position
  (P413), club membership (P54 with start/end dates) and many external identifiers.
* TESTED from this environment: see §5.

### Considered and excluded
Transfermarkt, FBref/Sports-Reference, WhoScored, SofaScore, FotMob, Flashscore and unofficial
"hidden" mobile/web APIs: access would require scraping websites or undocumented endpoints,
which the project rules forbid — not evaluated further. Kaggle/GitHub datasets derived from
such sites: provenance and licence **UNVERIFIED** → excluded. football-data.co.uk (results &
odds CSV): no player data → out of scope.

## 4. Recommendation (founder decision)

| Step | Proposal | Cost |
|---|---|---|
| 1 | Register **free** API-Football (and optionally football-data.org) keys yourself and save them via the secure credential form, so their real coverage of Botola Pro/2 and the African/South American leagues can be tested | €0 |
| 2 | Build the provider-independent model now, designed for **Wikidata (CC0)** identities (coverage to be measured first — §5), **OpenFootball** for clubs/fixtures and **TheSportsDB** for identity cross-IDs (Europe/South America) | €0 |
| 3 | Keep statistics limited to data each club imports under its own licence (already supported, tenant-private) until a statistics provider's commercial terms are verified in writing | €0 |
| 4 | Only if step 1 confirms coverage: request a written quote/terms from API-Football (and Wyscout for youth) — **no purchase without approval** | quote only |

## 5. Wikidata test results

Tested 2026-11-28 from this environment: `query.wikidata.org` was reachable but enforcing an
emergency rule — `HTTP 429 "Aggressively rate-limiting to 1 req / min - this rule was created
during active wdqs outage"` — then `Retry-After: 1000` on two consecutive attempts (~35 min).
No query completed, so **the number of young African/South American players in Wikidata and
the fill rate of position/club fields are NOT MEASURED**. What is established: licence (CC0)
and the data model (P569 birth date, P27 citizenship, P413 position, P54 club with start/end
dates, external IDs). Next test: retry when the outage rule is lifted, or use the weekly
Wikidata JSON dumps (no rate limit) for a batch import design.
