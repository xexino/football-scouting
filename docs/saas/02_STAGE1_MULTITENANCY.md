# Stage 1 — Multi-tenant core (P0)

## What changed

**Tenant model**
* `organizations` (tenant boundary) and `memberships` (user ↔ organization, with the
  organization-specific `role` and `region`). Users are global identities; a consultant can
  belong to several clubs with different roles.
* `users.is_platform_admin` (SaaS operator, no tenant data access) and `users.token_version`
  (session revocation).
* `player_assessments`: one organization's private view of a player (tactical role, physical
  notes, fee estimate, salary expectation, availability, agent, notes). These fields were
  removed from `players`, which now holds identity only.

**Ownership** (see the audit for the full table)
* Strictly private (`organization_id NOT NULL`): assessments, videos, observations, match
  reports, scouting reports, pipeline entries & events, budgets; audit logs (NULL only for
  platform events).
* Shared-or-private (`NULL` = platform reference): players, stats, data sources, leagues, clubs.

**Enforcement, in depth**
1. `app/tenancy.py`: a SQLAlchemy `do_orm_execute` hook adds organization criteria to *every*
   ORM SELECT/UPDATE/DELETE, including relationship and eager loads, joins, `select_from`,
   subqueries and aggregates. It is fail-closed: a statement touching a tenant table with no
   tenant context raises; Core SQL is refused inside a tenant context.
2. A `before_flush` guard stamps new rows with the tenant and rejects any write to another
   organization's rows or to shared reference rows.
3. Database constraints: per-organization unique constraints (partial unique indexes for
   shared rows); composite foreign keys `(video_id, organization_id)` and
   `(entry_id, organization_id)` so child rows cannot point to another organization's parent.
4. Auth: JWT carries `org` + `ver`; every request re-loads the live membership. A forged or
   stale organization claim gets 403; password change revokes all tokens.
5. Explicit route checks remain as defence in depth (e.g. shared players cannot be edited or
   deleted; stats must be recorded under the organization's own data source; join ON clauses
   carry the organization id).
6. Cross-tenant requests return **404** (no existence disclosure); guard violations return 403.

**Shared vs private in practice**
* A club sees shared reference players plus its own; its valuation and opinions about a
  shared player live in its own assessment, invisible to other clubs.
* Statistics a club imports are always private to it, even for shared players. Percentile
  pools, dashboards and comparisons are computed only over data visible to the club.
* Shared reference data can only be written in the SYSTEM context (platform operations).

**Migrations**: Alembic. `0001_legacy` is the exact pre-SaaS schema; `0002_multitenant`
migrates a populated single-club database into one "legacy organization" (all rows
private to it, roles → memberships, private player fields → assessments, budget columns
renamed). PostgreSQL deployments run `alembic upgrade head` at startup; pre-Alembic
databases are detected and stamped `0001_legacy` first.

**Account management**: organization admins manage *memberships*. Adding an existing
account only adds a membership; an admin cannot change the password or name of an account
that also belongs to another organization (prevents cross-tenant account takeover).

**API changes** (breaking, pre-1.0): money fields are currency-neutral
(`estimated_fee`, `salary_expectation`, `transfer_budget`, `wage_budget`, plus `currency`);
`POST /api/auth/token` returns `organization_id` instead of the user (call `/api/auth/me`);
new `POST /api/auth/switch-organization`; `/api/admin/export` now exports only the
caller's organization; player search adds `scope=shared|private`.

## Tests

| Suite | Result |
|---|---|
| Existing 41 tests (adapted to renamed fields) | pass (SQLite + PostgreSQL) |
| `test_tenancy.py` — 14 cross-tenant tests: private players, shared players with private assessments, private stats on shared players, percentile pool isolation, video/report/pipeline isolation, audit/budget/member isolation, account-hijack prevention, org switching, forged org claim, token revocation, fail-closed sessions, write guard, composite FK, import into shared player | pass |
| Mutation check: tenant filter disabled → 9/14 isolation tests fail (the other 5 cover independent layers) | confirmed |
| `test_migrations.py` — empty→head == models, legacy data → head → downgrade | pass (PostgreSQL) |
| Browser end-to-end workflow on PostgreSQL with migrations | pass, no page errors |

Totals: SQLite 55 passed / 2 skipped (PostgreSQL-only migration tests); PostgreSQL 57 passed.

## Remaining risks (carried forward)

* PostgreSQL Row-Level Security is not yet enabled; isolation relies on the ORM layer +
  constraints. RLS is recommended as a further layer once the schema stabilizes.
* Leagues/clubs created by a club are private to it, so two clubs may hold duplicate
  names for the same real club; a platform-curated shared catalogue is the long-term fix.
* No platform-side workflow yet to curate shared reference players (SYSTEM import only).
* Branding, deployment modes, DB-backed throttling, invitations, tenant deletion and
  subscriptions follow in stages 2–4.
