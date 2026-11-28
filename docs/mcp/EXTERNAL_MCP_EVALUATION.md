# External football MCP servers — evaluation

Date: 2026-11-28. Reviewer: engineering (Claude Code session). Scope: development agents only.
**Nothing here is approved for production or for customer data.** Data licences are governed
by `docs/data/DATA_LICENSING_REGISTER.md`; using an MCP server does not change a provider's
licence status.

Method:
1. Read-only clone of each repository. Read the licence, dependencies, every outbound host,
   file and process access, and how secrets are handled.
2. `npm audit` on the published package.
3. Run in an isolated sandbox: the pinned npm version, installed with `--ignore-scripts`, driven
   by a real MCP client (Python `mcp` 2.3.0, stdio).
4. Test against the live provider wherever that was possible without a paid key.

No paid key was used: none exists, and the founder declined to create API-Football and
football-data.org keys during this project.

## Summary

| Server | Verdict for dev agents | Licence (code) | Key needed | Live-tested here | Main concerns |
|---|---|---|---|---|---|
| **Football Docs** (`withqwerty/football-docs`) | **PASS — enabled** | MIT (package.json + README; no LICENSE file in repo) | No | **Yes**: 17 tools, searches answered offline | Self-update downloads a new docs index (signed); we pin the version and force `FOOTBALL_DOCS_DATA=bundled` |
| **Sportmonks** (`SportMonks/MCP`) | **PASS with conditions — configured, inactive without token** | MIT (official, Sportmonks staff are npm maintainers) | Yes (`SPORTMONKS_API_TOKEN`) | Partly: reaches the API, rejects an invalid token cleanly; 159/159 of its own tests pass | Token goes in the URL query (`api_token`), by provider design; BETA; data licence **UNVERIFIED** |
| **API-Football** (`yalmeidarj/mcp-football-server`) | **FAIL — not configured** | **None** (no LICENSE; package.json says ISC) | Yes (RapidAPI key) | Built and listed 24 tools; no key to go further | No licence, unmaintained since 2025-06-28 (9 commits, 4 ★), **high-severity advisories** in its locked dependencies, no tests, no rate-limit handling |
| **SportAPI** (`sportapi.ai/mcp-server`) | **NOT EVALUATED — UNVERIFIED** | Unknown | Unknown | **No**: host refused by this environment's network policy (proxy 403 / DNS) | Nothing verifiable; marketing claims not accepted without evidence |

## 1. Football Docs MCP — `withqwerty/football-docs`

- **What it is:** a searchable index of public documentation for 32 football-data providers and
  libraries. It covers API-Football, Sportmonks, StatsBomb, Opta, Wyscout, SkillCorner, kloppy,
  socceraction, mplsoccer, soccerdata, TheSportsDB, Transfermarkt and others. It returns no
  match or player data: it answers "how does provider X model Y" questions for developers.
- **Repository:** an organization account, 236 ★, 394 commits, active (last commit 2026-11-28).
  Listed in the official MCP registry as `io.github.withqwerty/football-docs`, transport stdio.
- **Install:** `npx -y football-docs@0.17.10`. It needs Node ≥ 22.13 and uses Node's built-in
  SQLite, so no native build. The npm maintainer is one individual.
- **Tools (17, verified live):**
  - `search_docs`, `resolve_provider_id`, `get_provider_docs`, `list_providers`, `compare_providers`;
  - `request_update`, `get_metric`, `list_metrics`, `resolve_entity`;
  - `search_papers`, `get_paper`, `get_web_source`, `read_paper`, `match_quote`;
  - `add_local_paper`, `forget_paper`, `purge_cache`.
- **Security review:**
  - No API key. The bundled index is an 8.5 MB SQLite file.
  - Outbound: in `auto` mode it checks GitHub releases for a newer index at most once a day.
    Manifests are **ed25519-signed**, and the public key is pinned in `src/data-signing.ts`.
    It also has an optional REEP dataset link.
  - `FOOTBALL_DOCS_DATA=bundled` turns all of that off. We set it, and verified the server wrote no
    cache directory.
  - `get_web_source` / `add_local_paper` can fetch or read user-named sources on request. That's
    acceptable for a dev agent; Claude Code's per-tool permission prompts still apply.
  - `npm audit` on the published package: **0 vulnerabilities** (134 packages).
- **Live test results:**
  - `list_providers` returned the index.
  - `search_docs("Sportmonks player statistics endpoint")` returned the Sportmonks v3 docs, with
    source URLs and web.archive.org snapshots.
  - `search_docs("API-Football free plan requests per day")` returned **Free: 100/day, 10/min;
    Pro 7,500/day; Ultra 75,000/day; Mega 150,000/day** (curated from api-football.com, checked
    2026-10-15). This is useful evidence for our licensing register, but it's second-hand, so it
    stays UNVERIFIED until the provider's own page is quoted.
  - `search_docs("Botola Morocco league coverage")` → *"No indexed doc mentions 'botola',
    'morocco'"*. It states honestly that coverage is not indexed; it doesn't invent any.
- **Rate limits / cost:** none (local).
- **Verdict:** PASS for development agents. It reduces hallucinated provider facts, which matches
  our "never invent" rule.

## 2. Sportmonks Football MCP — `SportMonks/MCP` (`@sportmonks/football-mcp-server`)

- **What it is:** the official MCP server for Sportmonks Football API 3.0, marked BETA: *"companion
  tool for AI-assisted exploration … not a production API client"*.
- **Repository:** the Sportmonks organization, MIT. npm maintainers are three `@sportmonks.com`
  accounts. Version 1.5.0, last change 2026-07-15. 4.8k lines of TypeScript plus 3.4k lines of
  tests. Its 159 tests pass (`vitest`, run here). Its only runtime dependency is
  `@modelcontextprotocol/sdk`.
- **Tools (from source; 29 entries):**
  - search and lookups: `search`, `get_player`, `get_team`, `get_league`, `get_coach`,
    `get_referee`, `get_venue`, `get_squad`, `get_transfers`, `get_rivals`;
  - fixtures and seasons: `get_matches`, `get_fixture_details`, `get_fixture_lineup_stats`,
    `get_standings`, `get_historic_seasons`, `get_season_stats`, `get_topscorers`, `get_totw`;
  - match content: `get_commentaries`, `get_fixture_news`, `get_match_facts`, `get_match_preview`
    / `match_preview`, `get_pressure_index`, `get_odds`;
  - overviews: `team_overview`, `league_overview`.
  - Every tool has typed schemas and runtime validation, and errors return a `how_to_fix` field.
- **Security review:**
  - Outbound hosts: `api.sportmonks.com`, plus an OpenAPI spec fetched from
    `vercel-eight-cyan-93.vercel.app` (a third-party-looking host, contacted without the token).
  - Logging: it appends a local tool-call log by default, in the OS temp directory. We set
    `SPORTMONKS_LOG_FILE=off`.
  - The token is read from the environment and redacted in its debug log. Sportmonks
    authenticates with an `api_token` **query parameter**, so the token can show up in proxy or
    access logs on the provider's side.
  - No child processes, no `eval`. `npm audit` on the published package: **0 vulnerabilities**.
    Note that the repository's lockfile pins SDK 1.29.0, which has a known ReDoS advisory; npm
    installs a fixed version.
- **Live test:**
  - Without a token it refuses to start ("SPORTMONKS_API_TOKEN environment variable is required").
  - With an invalid token, the startup reference-data load gets `401 Invalid token provided` and
    the server exits with an `authentication_error`.
  - It **cannot list tools without a valid token**, which is why the tool list above comes from
    the source code.
- **Rate limits / coverage:** plan-dependent; enforced by Sportmonks. It handles 429 as a typed
  `rate_limit_error`. Competition coverage — including Botola Pro and youth leagues — is
  **NOT MEASURED** without a key. The licensing register lists Sportmonks as **UNVERIFIED**.
- **Verdict:** PASS with conditions, for development exploration only:
  - pin `@1.5.0`, set the token through the environment only, and keep logging off;
  - no customer or private data in prompts that also use this server;
  - no production use until the founder approves a plan and the terms are verified.

## 3. API-Football MCP — `yalmeidarj/mcp-football-server`

- **What it is:** a community server wrapping API-Football v3 **through RapidAPI**
  (`api-football-v1.p.rapidapi.com`), with `RAPIDAPI_KEY` / `RAPIDAPI_HOST` in the environment
  (dotenv).
- **Repository:** an individual, 4 ★, 9 commits, last commit 2025-06-28. **No licence file**, so
  all rights are reserved by default; no tests.
- **Tools (24, verified by building and listing locally):**
  - `get-fixtures-by-date`, `get-team`, `get-standings`, `list-countries`, `list-seasons`,
    `list-leagues`, `list-teams`, `get-team-statistics`;
  - `get-squad`, `get-player`, `get-player-stats`;
  - `get-fixtures-by-team`, `get-fixtures-by-league`, `get-fixture-details`, `get-fixture-events`,
    `get-fixture-lineups`, `get-fixture-statistics`;
  - `get-head-to-head`, `get-injuries`, `get-transfers`, and more.
- **Security review:**
  - Raw upstream error bodies are passed back to the model.
  - No retry or 429 handling.
  - `npm audit` on its lockfile: **high severity**. That covers `@modelcontextprotocol/sdk ≤ 1.31.0`
    (GHSA-8r9q-7v3j-jr4g, ReDoS) and `body-parser` 2.0.0–2.3.0 (three DoS advisories).
- **Rate limits:** API-Football Free is 100 requests/day and 10/minute (via football-docs, see
  above; UNVERIFIED). This server does nothing to respect them.
- **Verdict:** FAIL. If API-Football is approved later, use the provider's own API from our
  server-side `app/providers` boundary, or an official server; never this repository.

## 4. SportAPI MCP — `sportapi.ai/mcp-server`

- **Result:** the page could not be fetched from this environment. The egress proxy refused
  `sportapi.ai:443` (HTTP 403), and a separate fetch attempt failed DNS resolution.
- **Not verified:** operator, tools, authentication, prices, quotas, coverage and terms.
- **Status:** UNVERIFIED. To evaluate it, the founder (or a session whose network allows
  `sportapi.ai`) must read and archive the terms and pricing pages. Marketing claims alone are
  not accepted.

## What we configured (`/.mcp.json`)

- `football-docs` — pinned `0.17.10`, `FOOTBALL_DOCS_DATA=bundled` (no self-update).
- `sportmonks-football` — pinned `1.5.0`, token from `${SPORTMONKS_API_TOKEN}`, logging off.
  It won't start without a token.
- `raja-scout` — our own server (see `RAJA_SCOUT_TOOLS.md`). Read-only; the token comes from the
  environment.
- Not configured: API-Football (failed review) and SportAPI (unverified).

Claude Code asks each user to approve project MCP servers before they run. Approve
`football-docs` and `raja-scout`, and approve `sportmonks-football` only once you have your own
key.

## Rules for agents using external MCP servers

1. Never paste player assessments, scouting notes, report text, valuations or salaries into a
   prompt or tool call meant for an external server. Our server labels such fields
   `organisation_private`.
2. Provider data from an external MCP server is **exploration only**. It is never written into
   the platform unless the provider is `VERIFIED-COMMERCIAL-OK` in the licensing register and the
   data comes in through the import path with its source recorded.
3. Keys live in each developer's environment or a secret manager. They are never committed, never
   placed in `frontend/`, and never sent to our MCP clients.
