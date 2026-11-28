# Raja Scout MCP tools

The server is `backend/app/mcp`. Tools are read-only unless marked otherwise. Every call is
authenticated, scoped to the caller's organization, checked against the caller's role, rate
limited and audited (see `MCP_ARCHITECTURE.md`).

Common behaviour:
- **Private assessment is opt-in.** Your club's tactical opinion, availability, notes,
  valuation, salary and agent are left out unless the call sets `include_private_assessment=true`
  (`search_players`, `get_player_profile`). When included, they sit under `organisation_private`
  with a "do not send to external tools" notice. Financial fields still need `financials:read`.
- **Errors** come back as `{"error": code, "message": ...}`. The codes are `unauthenticated`,
  `forbidden`, `not_found`, `invalid_input`, `conflict`, `rate_limited`,
  `subscription_read_only`, `internal_error` and (write tools) `declined`. Another club's record
  is always `not_found`, never `forbidden`, so its existence isn't revealed.
- **Statistics carry an evidence notice:** recorded past output only, not a prediction, and not a
  substitute for live or video scouting.

## Read-only tools

| Tool | Permission | Arguments (validated) | Wraps |
|---|---|---|---|
| `search_players` | `players:read` | `query` ≤80 chars; `positions` (GK/CB/FB/DM/CM/AM/W/ST); `primary_only`; `age_min`/`age_max` 14–45; `nationality`; `league_country`; `min_minutes` 0–10000; `stat_filters` (`metric>=value,...`, strict pattern); `sort` (`full_name/age/contract_expiry/last_updated/height/metric:<key>`); `order`; `page`; `page_size` ≤50; `include_private_assessment` | `GET /api/players` |
| `get_player_profile` | `players:read` | `player_id`; `include_private_assessment` | `GET /api/players/{id}` |
| `get_player_statistics` | `players:read` | `player_id`; `season` (`2025-26` / `2025` / `all`) | `GET /api/players/{id}/stats` + `/analytics` |
| `find_young_talents` | `players:read` | `max_age` 14–23 (default 21); `positions`; `metric` (one of 33 metric keys); `min_minutes` (default 450); `nationality`; `league_country`; `limit` ≤50 | `GET /api/players` sorted by the metric (direction-aware) |
| `compare_players` | `players:read` | `player_ids` 2–5; `season`; `tactical_role`; `allow_mixed_positions` | `POST /api/compare` (read-only) |
| `get_club_requirements` | `pipeline:read` (budgets also need `financials:read`) | — | Derived from `GET /api/pipeline` (open target positions × priority) + `GET /api/budgets` |
| `get_recruitment_pipeline` | `pipeline:read` | `stage`; `priority`; `position`; `assigned_to_me`; or `player_id` for one entry's history | `GET /api/pipeline`, `/api/pipeline/player/{id}` |
| `get_scouting_reports` | `players:read` | `player_id` (list) or `report_id` (full report) | `GET /api/reports`, `/api/reports/{id}` |
| `generate_shortlist` | `players:read` | `position`; `metrics` 1–4; `max_age`; `min_minutes` (default 900); `exclude_in_pipeline` (default true); `limit` ≤20 | Candidates from `GET /api/players`, metrics from `app.analytics` |

Notes:
- **`get_club_requirements`:** there is no separate "requirements" record. The tool says what it
  was derived from, and a dedicated requirements model is a possible later feature.
- **`generate_shortlist`:**
  - It **saves nothing** (`"saved": false`).
  - Score = the mean of per-metric percentile ranks *within the candidate pool* (latest season),
    respecting each metric's direction.
  - A player missing a requested metric is left unranked, not guessed.
  - Results are a starting list for scouting, never a verdict on potential. The tools never call
    anyone a "future star".

## Write tools (implemented, **disabled by default**)

They are registered only with `MCP_WRITE_TOOLS_ENABLED=true`. Until then they aren't even listed
to clients.

| Tool | Permission | Arguments | Wraps |
|---|---|---|---|
| `create_scouting_report` | `reports:write` | `player_id`; `season`; `tactical_role` | `POST /api/reports/generate` (draft, evidence-tagged) |
| `add_video_observation` | `video:write` | `video_id`; `timestamp_seconds` 0–14400; `category`; `assessment`; `phase`; comments ≤2000 chars | `POST /api/videos/{id}/observations` |
| `update_recruitment_status` | `pipeline:move` (+ `pipeline:approve` / `pipeline:negotiate` for those stages, enforced by the pipeline rules) | `entry_id`; `to_stage`; `note` 3–2000 chars (rationale) | `POST /api/pipeline/{id}/move` |

Each write call works like this:
1. **Preview.** The server authenticates and authorises the call, then describes the change
   (e.g. "Move X from 'identified' to 'under_observation'…", including any transition
   warnings). If the call isn't allowed it stops here, and no human is asked.
2. **Human approval.** The server asks through MCP elicitation; the client shows the person a
   confirmation dialog. A client that can't show one is refused. The model can't approve its own
   action, because approval is not a tool argument.
3. **Execute.** Authentication and authorisation are checked again, and the normal endpoint runs
   with all business rules and its own audit entry. The MCP audit row records
   `approval: human_elicitation`. Declines are audited as `mcp.write_declined`.

## Not provided, on purpose

- No SQL, raw query, export or bulk-download tool.
- No tool returns another organization's private data, user lists, credentials or audit logs.
- No delete tools.
- No tool calls an external data provider (see `app/providers`).
