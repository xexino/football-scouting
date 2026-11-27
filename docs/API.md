# API reference

The API is a REST/JSON API built with FastAPI. Interactive, always-current documentation is
served by the running application:

* **Swagger UI:** `http://<host>:8000/docs`
* **ReDoc:** `http://<host>:8000/redoc`
* **OpenAPI 3 spec:** `http://<host>:8000/openapi.json`

## Authentication

```bash
# 1. obtain a token (OAuth2 password flow, form-encoded)
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/token \
  -d 'username=director@raja-scout.local' -d 'password=RajaDemo2026!' | jq -r .access_token)

# 2. call the API
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/players?position=CB&age_max=25&stat_filters=aerial_pct>=60"
```

Tokens are JWT (HS256), valid for `TOKEN_EXPIRE_MINUTES` (default 8 h). Five failed logins
lock an account identifier for 15 minutes. Every endpoint checks role permissions
(see `GET /api/users/roles`); responses are `401` (not authenticated) or `403` (not permitted).

## Conventions

* `null` in statistics means **not provided by the source** — never zero.
* Financial fields (`estimated_fee_eur`, `salary_expectation_eur`, `fee_estimate_source`,
  `agent_name`) are returned as `null` with `financials_redacted: true` for roles without
  `financials:read`.
* Every record carries provenance (`data_source`, `is_fictional`, `last_updated`).
* Scouting reports contain `sections.<name>.items[]` each with an `evidence_type`:
  `verified_data`, `fictional_sample`, `scout_opinion`, `model_estimate`,
  `insufficient_evidence`, `scout_input_required`.
* Validation errors return `422` with details.

## Key query parameters — `GET /api/players`

| Parameter | Example | Notes |
|---|---|---|
| `q` | `diallo` | Name / known-as substring |
| `position` | `CB,DM` | Primary **or** secondary; add `primary_only=true` |
| `age_min`, `age_max` | `18`, `24` | |
| `nationality` | `Senegal,Mali` | Matches first or second nationality |
| `league_id`, `league_country`, `club_id` | | |
| `height_min`, `height_max`, `foot` | `185`, `left` | |
| `contract_expiry_before` | `2027-06-30` | |
| `fee_min`, `fee_max`, `salary_max` | `1500000` | Requires `financials:read` |
| `availability` | `available,contract_expiring` | |
| `pipeline_stage` | `shortlisted` or `none` | |
| `min_minutes` | `900` | Latest season |
| `stat_filters` | `prog_passes_p90>=4,pass_pct>=85` | Any metric key from `GET /api/meta` |
| `sort`, `order` | `metric:npxg_p90`, `desc` | Also `full_name`, `age`, `fee`, `contract_expiry`, `height`, `last_updated` |
| `page`, `page_size` | `1`, `25` | max 200 |

## Endpoints

### Auth

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/token` | Log in (OAuth2 password flow) and obtain a bearer token |
| GET | `/api/auth/me` | Current user and permissions |
| POST | `/api/auth/change-password` | Change Password |

### Users

| Method | Path | Description |
|---|---|---|
| GET | `/api/users/roles` | Roles and their permissions |
| GET | `/api/users/directory` | Minimal list of active users (for assignment pickers) |
| GET | `/api/users` | List Users |
| POST | `/api/users` | Create User |
| PATCH | `/api/users/{user_id}` | Update User |

### Reference

| Method | Path | Description |
|---|---|---|
| GET | `/api/meta` | Enumerations, metric catalogue and tactical roles used by the UI |
| GET | `/api/leagues` | Leagues |
| POST | `/api/leagues` | Create League |
| PATCH | `/api/leagues/{league_id}` | Update League |
| GET | `/api/clubs` | Clubs |
| POST | `/api/clubs` | Create Club |
| GET | `/api/data-sources` | Data Sources |
| POST | `/api/data-sources` | Create Data Source |

### Players

| Method | Path | Description |
|---|---|---|
| GET | `/api/players` | Advanced player search |
| POST | `/api/players` | Create Player |
| GET | `/api/players/export.csv` | Export the (filtered) player database as CSV |
| GET | `/api/players/{player_id}` | Get Player |
| PATCH | `/api/players/{player_id}` | Update Player |
| DELETE | `/api/players/{player_id}` | Delete Player |
| GET | `/api/players/{player_id}/stats` | List Stats |
| POST | `/api/players/{player_id}/stats` | Add or replace a season stat line (idempotent per player/season/league/source) |
| DELETE | `/api/players/{player_id}/stats/{stats_id}` | Delete Stats |
| GET | `/api/players/{player_id}/analytics` | Per-90, percentile, consistency and role-fit analysis |

### Comparison

| Method | Path | Description |
|---|---|---|
| POST | `/api/compare` | Compare 2–5 players |

### Video & Match Reports

| Method | Path | Description |
|---|---|---|
| GET | `/api/videos` | List Videos |
| POST | `/api/videos` | Register a link to licensed footage |
| GET | `/api/videos/{video_id}` | Get Video |
| DELETE | `/api/videos/{video_id}` | Delete Video |
| POST | `/api/videos/{video_id}/observations` | Add Observation |
| DELETE | `/api/videos/{video_id}/observations/{obs_id}` | Delete Observation |
| GET | `/api/match-reports` | List Match Reports |
| POST | `/api/match-reports` | Save an individual match report (video or live) |
| GET | `/api/match-reports/{report_id}` | Get Match Report |

### Scouting Reports

| Method | Path | Description |
|---|---|---|
| GET | `/api/reports` | List Reports |
| POST | `/api/reports/generate` | Draft a report from platform evidence (evidence-tagged) |
| GET | `/api/reports/{report_id}` | Get Report |
| PATCH | `/api/reports/{report_id}` | Update Report |
| DELETE | `/api/reports/{report_id}` | Delete Report |
| GET | `/api/reports/{report_id}/export.md` | Export report as Markdown |
| POST | `/api/reports/{report_id}/finalize` | Lock a report (requires recommendation) |

### Recruitment Pipeline

| Method | Path | Description |
|---|---|---|
| GET | `/api/pipeline` | Pipeline board grouped by stage |
| POST | `/api/pipeline` | Add a player to the pipeline (stage: Identified) |
| GET | `/api/pipeline/events` | Recent decisions across the pipeline |
| GET | `/api/pipeline/player/{player_id}` | By Player |
| GET | `/api/pipeline/{entry_id}` | Get Entry |
| PATCH | `/api/pipeline/{entry_id}` | Update |
| POST | `/api/pipeline/{entry_id}/move` | Move a player to another stage (rationale required) |

### Dashboard

| Method | Path | Description |
|---|---|---|
| GET | `/api/dashboard` | Executive dashboard summary |
| GET | `/api/budgets` | List Budgets |
| PUT | `/api/budgets` | Create or update the budget for a season |

### Data Import

| Method | Path | Description |
|---|---|---|
| GET | `/api/import/templates/{kind}.csv` | Template |
| POST | `/api/import/players` | Import player profiles from CSV |
| POST | `/api/import/stats` | Import season statistics from CSV |
| POST | `/api/import/json` | Import players and stats as JSON (for provider adapters / ETL jobs) |

### Administration

| Method | Path | Description |
|---|---|---|
| GET | `/api/admin/audit-logs` | Audit Logs |
| GET | `/api/admin/export` | Full logical backup as JSON (password hashes excluded) |

### System

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health |
