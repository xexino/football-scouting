# Stage 0 — Architecture audit & multi-tenant design

Audited commit: `f660731` (default branch `claude/raja-scout-intelligence-tuu0bo`).

## 1. Current architecture

```
Browser SPA (frontend/, vanilla JS, no build)  ──HTTP/JSON + Bearer JWT──►  FastAPI (backend/app)
                                                                             │ routers/ (11 modules, ~70 query sites)
                                                                             │ analytics.py, report_generator.py, importers.py
                                                                             ▼
                                                                   SQLAlchemy 2 ORM ─► PostgreSQL (SQLite in tests)
```

* One process serves API + static frontend. Stateless except for the **in-memory login
  throttle** (`security._failed_logins`).
* Schema is created with `Base.metadata.create_all()` at startup. **No migrations.**
* Demo data seeded at startup when `SEED_SAMPLE_DATA=true`; production guard via `RAJA_ENV`.
* 41 automated tests (SQLite + PostgreSQL).

## 2. Database model assessment

| Table | Purpose | Tenant problem |
|---|---|---|
| `users` | identity **and** role | role is global — one club only |
| `audit_logs` | audit trail | no owner; any admin sees all |
| `data_sources` | provenance | global; one club's licence notes visible to all |
| `leagues`, `clubs` | reference | global unique `(name,country)` |
| `players` | identity **+ private valuation** (fee, salary, agent, availability, notes, tactical role, physical notes) | mixes public identity with confidential club opinion |
| `player_season_stats` | stats | global; a club's *licensed* provider data would leak to other clubs |
| `match_videos`, `video_observations`, `match_reports`, `scouting_reports` | scouting work | global |
| `pipeline_entries` | recruitment pipeline | `UNIQUE(player_id)` — only one club could track a player |
| `pipeline_events` | decision history | global |
| `recruitment_budgets` | budget | `UNIQUE(season)` — one club only |

Strengths to keep: provenance columns, nullable stats (no zero-filling), immutable pipeline
events, evidence-tagged reports, clean router/service split.

## 3. Authentication & authorization assessment

* bcrypt (cost 12) + HS256 JWT (`sub`, `role`, `exp`). Good basis.
* RBAC via `ROLE_PERMISSIONS` and `require(*perms)` dependency — good, but **role is a
  user attribute**, so a user cannot have different roles in different clubs.
* JWT has no organization claim and no revocation (password change / deactivation does not
  invalidate issued tokens until expiry, up to 8 h).
* Login throttle is per-process memory → ineffective with several workers/instances and
  reset on restart.
* No self-service or invitation flow: an admin types the user's password.
* No platform operator concept (founder/support) distinct from club administrators.

## 4. Entities requiring tenant ownership

**Strictly private** (`organization_id NOT NULL`, visible only to the owning organization):
`player_assessments` (new: fee estimate, salary expectation, agent, availability view,
tactical role, physical notes, private notes), `match_videos`, `video_observations`,
`match_reports`, `scouting_reports`, `pipeline_entries`, `pipeline_events`,
`recruitment_budgets`, `audit_logs` (NULL only for platform-level events, never visible to
tenants), `invitations`, `subscriptions`.

**Shared-or-private** (`organization_id NULL` = shared reference curated by the platform;
set = private to that organization): `players` (identity only), `player_season_stats`,
`data_sources`, `leagues`, `clubs`.

**Global**: `organizations`, `users` (identity), `memberships`, `login_attempts`.

### Shared reference data vs. private scouting information

| | Shared reference | Private club data |
|---|---|---|
| Examples | player identity (name, DOB, nationality, club, positions, height, foot, contract expiry), league/club names, statistics the **platform** is licensed to redistribute | everything a club creates or pays for: its own players, its imported provider stats, valuations, salaries, agents, notes, video, reports, pipeline, budgets |
| Owner | platform (`organization_id IS NULL`) | the organization |
| Who writes | platform operators only (system context) | members of the organization |
| Who reads | every organization | that organization only |
| Licensing | only data with redistribution rights | data under the club's own licence never becomes shared |

A club can scout a shared player: its opinions live in its own private rows that reference
the shared player. A club **cannot modify** a shared row. Statistics a club imports are
always private to that club, even for shared players. Percentile pools and dashboards are
computed only over data visible to the requesting organization, so aggregates cannot leak
other clubs' private data.

## 5. Security risks (current → mitigation)

| # | Risk | Severity | Mitigation in this sprint |
|---|---|---|---|
| R1 | No tenant isolation: any user reads all clubs' data | Critical | `organization_id` + automatic ORM tenant filter + write guard + composite FKs + isolation tests |
| R2 | Forgotten filter in one of ~70 query sites | Critical | Filter is applied **globally** in a SQLAlchemy `do_orm_execute` hook (fail-closed: queries on tenant tables without a tenant context raise) instead of per-query code |
| R3 | Indirect leaks via aggregates (percentile pools, dashboard counts, pool sizes) | High | Same global filter applies to aggregate queries; tests assert counts |
| R4 | Cross-tenant writes (attach own report to other club's video/pipeline) | High | `before_flush` guard; composite FKs `(parent_id, organization_id)` |
| R5 | Tokens not revocable | Medium | `token_version` on user, org claim checked against live membership on every request |
| R6 | Throttle bypass with multiple instances | Medium | DB-backed `login_attempts` (per account and per IP) |
| R7 | Schema drift / no upgrade path | High | Alembic; legacy baseline + data migration |
| R8 | Demo data/accounts mixed with customer data | High | `DEPLOYMENT_MODE=demo|customer`; demo mode refuses non-demo organizations, customer mode refuses demo seeding |
| R9 | Admin-chosen passwords; no individual provisioning | Medium | Invitation tokens (hashed, expiring, single use) |
| R10 | Platform staff browsing club secrets | High (trust) | Platform admin can manage organizations/subscriptions but has no tenant data access |
| R11 | Brand/legal: UI says "for Raja Club Athletic" | High (legal) | Remove; configurable org identity; non-affiliation notice |
| R12 | Core-SQL (`table.select()`) in export bypasses ORM filters | High | Tenant export rewritten with ORM; Core statements on tenant tables blocked in tenant context |
| R13 | Logo upload as XSS vector | Medium | PNG/JPEG/WebP only (no SVG), size limit, served as data URL in `<img>` |

## 6. Migration strategy

1. **Alembic baseline `0001_legacy`** = exact single-tenant schema of `f660731`.
   Existing databases created by `create_all()` are adopted with `alembic stamp 0001_legacy`
   (automated in `app.cli migrate`: an un-versioned DB that already has `players` is stamped).
2. **`0002_multitenant`** (schema + data migration, PostgreSQL):
   * create `organizations`, `memberships`, `player_assessments`, …;
   * create one organization ("Legacy organization", editable later) and assign **all**
     existing rows to it, so nothing becomes shared accidentally;
   * move `users.role/region` into memberships; move private player columns into
     `player_assessments`; rename money columns to currency-neutral names;
   * replace global unique constraints with per-organization ones.
3. New installations simply run `alembic upgrade head`.
4. Tests verify: upgrade on empty DB, legacy → head data migration, and that migrated
   schema == ORM models (no autogenerate diff).

## 7. Ordered implementation plan

| Stage | Content | Gate |
|---|---|---|
| 1 | Organizations, memberships, tenant columns, assessment split, global tenant filter + write guard, composite FKs, tenant-aware routers/analytics/imports, Alembic (0001 + 0002), isolation tests | all existing tests adapted + isolation tests green on SQLite and PostgreSQL |
| 2 | Organization identity & branding (name, logo, country, language, currency, settings), org switcher, remove customer=Raja assumptions, non-affiliation notice | tests + UI check |
| 3 | Production readiness: deployment modes, DB login throttle, token revocation, invitations/provisioning, tenant export & deletion, backup verification script | tests |
| 4 | SaaS foundations: plans (Scout / Club Pro / Enterprise), subscription status, trial, limits & seats, suspension (read-only), billing-provider interface (manual provider only), platform admin, billing options proposal | tests; **no paid provider integrated** |

Payment integration is explicitly out of scope until the founder chooses a provider.
