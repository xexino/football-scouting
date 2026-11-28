# Security & tenant-isolation audit — Stages 1–4

**Scope:** every change from commit `b1f1c6c` (Stage 0) to `52c8edb` (Stage 4), plus the
deployment configuration. **Date:** 2026-11-28. **Method:** full code review of all 86 API
endpoints, every query path, the tenancy layer, exports, CLI/startup operations and deployment
files; exploit tests written *before* each fix (each failed against the audited code, then
passed after the fix); an automated cross-tenant crawler driven by the application's own route
table; a route-level access matrix; migration from a database created by the *actual*
previous application; live production-mode runs over HTTP; backup → verify → restore.

No new product features or payment integrations were added.

## 1. Result summary

| Severity | Found | Fixed | Open |
|---|---|---|---|
| Critical | 0 | — | 0 |
| High | 2 | 2 | 0 |
| Medium | 10 | 10 | 0 |
| Low | 5 | 5 | 0 |
| Accepted residual risks | — | — | listed in §6 |

No path was found through which one organization can read, modify, export or delete another
organization's private scouting data. The highest-severity findings concerned the boundary
*between* tenants at the account level (identity enumeration and a password-guessing oracle).

## 2. Findings and fixes

| ID | Severity | Finding | Fix | Regression test |
|---|---|---|---|---|
| F1 | **High** | `POST /api/users` with the e-mail of an existing account silently added that person (e.g. another club's sporting director) to the caller's organization and returned their full name → cross-tenant PII enumeration and non-consensual membership. | Existing accounts can only join through an invitation accepted with their own password; direct creation returns 409 without PII. | `test_f1_*`, `test_shared_account_cannot_be_hijacked` |
| F2 | **High** | Invitation acceptance for an existing account verified the account password **without throttling** → any org admin could invite a victim's e-mail and brute-force their password. | Same per-account and per-IP DB throttle as login. | `test_f2_*` |
| F3 | Medium | Pipeline `assigned_scout_id` accepted any user id (other organizations' staff); their name was then returned. | Must be an active member of the same organization. | `test_f3_*`, crawler pass 2 |
| F4 | Medium | Player update accepted another organization's `current_club_id` / `data_source_id` (cross-tenant reference; unknown ids caused HTTP 500 → existence oracle). | Tenant-scoped validation of both references (422). | `test_f4_*`, crawler pass 2 |
| F5 | Medium | Organization export bulk-exported **shared, platform-licensed** reference data (players, stats, sources). | Export contains only rows owned by the organization (references kept as ids). | `test_f5_*` |
| F6 | Medium | Player CSV export allowed spreadsheet formula injection (`=HYPERLINK(...)`). | Cells starting with `= + - @ \t \r` are prefixed with `'`. | `test_f6_*` |
| F7 | Medium | Client-supplied `X-Forwarded-For` was trusted (Dockerfile `--forwarded-allow-ips='*'` uses the left-most entry; audit log read the raw header) → per-IP login throttle bypass and forged audit IPs. | `app/netutil.client_ip` takes the address appended by our own proxy (`TRUSTED_PROXY_HOPS`), never the client-supplied one; Dockerfile trusts only `FORWARDED_ALLOW_IPS` (default 127.0.0.1); Render blueprint sets 1 hop. Verified live: spray with 31 spoofed IPs still blocked at 30. | `test_f7_*` (2) |
| F8 | Medium | No Content-Security-Policy; one inline `onclick` handler. | Strict CSP on app and API (`script-src 'self'`, no eval, `object-src 'none'`, `frame-ancestors 'none'`); inline handler removed. Browser suites re-run with CSP enforced: 0 violations. | `test_f8_*` |
| F9 | Medium | CLI `create-org` always created a *customer* organization, even in a demo deployment → mixed data and an outage at next restart (startup guard refuses). Slug not validated. | Organization type follows `DEPLOYMENT_MODE`; slug validated. | `test_f9_*` |
| F10 | Medium | `docker-compose.yml` defaulted `POSTGRES_PASSWORD` to `raja`. | Compose refuses to start without an explicit password. | config review |
| F15 | Medium | `POST /api/clubs` accepted another organization's `league_id` (found by the crawler, missed in manual review). | Tenant-scoped league validation. | crawler pass 2 |
| F18 | Medium | After migrating a pre-SaaS demo database, the demo seeder ran again and created a **second** demo organization (duplicated data; users landed in the wrong workspace). Affects the existing Render demo on upgrade. | Seed only an empty database. Verified on a database built by the real previous application. | `test_f18_*` |
| F11 | Low | Passwords > 72 bytes caused HTTP 500 (bcrypt limit). | Rejected with 422. | `test_f11_*` |
| F12 | Low | Older password-reset links stayed valid after a newer link, a reset or a password change. | All outstanding links invalidated on issue / use / change. | `test_f12_*` |
| F13 | Low | `CORS_ORIGINS=*` accepted in production. | Refused at startup. | `test_f13_f14_*` |
| F14 | Low | API docs exposed by default in production. | Hidden unless `EXPOSE_API_DOCS=true`. Verified live: 404. | `test_f13_f14_*` |
| F16 | Low | Login response time revealed whether an account exists. | Constant-cost dummy bcrypt check for unknown accounts. | code review |

## 3. Files changed

**Application**: `app/netutil.py` (new), `app/accounts.py`, `app/audit.py`, `app/cli.py`,
`app/config.py`, `app/exporting.py`, `app/main.py`, `app/migrate.py`, `app/security.py`,
`app/seed.py`, `app/routers/auth.py`, `app/routers/pipeline.py`, `app/routers/players.py`,
`app/routers/reference.py`, `app/routers/users.py`, `frontend/app.js`.
**Deployment**: `Dockerfile`, `docker-compose.yml`, `render.yaml`, `.env.example`,
`docs/DEPLOYMENT.md`, `docs/INSTALLATION.md`.
**Tests (new)**: `test_security_audit.py` (15), `test_isolation_crawler.py` (5),
`test_access_matrix.py` (4). **Tests (updated)**: `conftest.py`, `test_tenancy.py`,
`test_lifecycle.py` (consultants now join by invitation), `test_migrations.py` (+adoption,
+grandfathering), `test_production.py` (order-independent).

## 4. Verification performed (actual commands and results)

### 4.1 Automated test suites
```
$ cd backend && python3 -m pytest -q                       # SQLite
132 passed, 3 skipped in 80.89s          (3 skipped = PostgreSQL-only migration tests)

$ TEST_DATABASE_URL=postgresql+psycopg://raja:***@localhost:5432/raja_scout_test \
  MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://raja:***@localhost:5432/raja_mig \
  python3 -m pytest -q                                      # PostgreSQL 16, fresh databases
135 passed in 84.59s
```

### 4.2 Tenant isolation (items 2–3)
* **Route inventory** from the app itself: 86 endpoints = 64 organization-scoped, 10 platform,
  4 user-level, 8 public (all 8 expected: index, health, public config, login, invitation
  preview/accept, password reset, billing webhook).
* **Crawler** (`test_isolation_crawler.py`), two organizations with separate users, both
  directions: the attacker's *administrator* calls all 64 tenant routes × all methods with the
  victim's ids in paths and bodies → no response contains any victim marker, no request on a
  victim id succeeds, no 5xx, victim export byte-identical afterwards (nothing read, modified,
  exported or deleted). Pass 2: attacker edits its own records pointing at victim ids → no
  stored cross-tenant reference (this pass found F3, F4, F15).
* **Mutation checks:** with the ORM tenant filter disabled the crawler reports leaks on 12+
  routes and `test_tenancy.py` fails 9/14 → the tests do detect isolation failures.
* **Access matrix:** all 78 protected routes → 401 anonymous; all 10 platform routes → 403
  for an organization admin; all 64 tenant routes → 403 for a platform operator without
  membership.
* Existing `test_tenancy.py` (14) still passes: shared vs private data, percentile pools,
  composite FKs, write guard, fail-closed sessions, forged org claims.
* No background jobs exist; startup tasks (migration, seeding — F18) and CLI operations
  (F9, lifecycle in SYSTEM context) were reviewed and tested.

### 4.3 Accounts (item 4)
Organization switching, invitations (new and existing accounts, revoke, expiry, single use,
ownership proof, now throttled), password resets (single use, supersession, session
revocation, refused for multi-organization accounts), platform-admin separation — covered by
`test_accounts.py`, `test_tenancy.py`, `test_subscriptions.py`, `test_security_audit.py`;
browser flow re-run (invite → accept in a separate browser → reset → login → reuse refused).

### 4.4 Subscriptions (item 5)
`test_subscriptions.py` (22) + access matrix: all plans, seat limit (members + pending
invitations, revoke frees, reactivation counted), player limit (API and import), feature
gating, trial expiry, 14-day grace, suspended/canceled/expired/no-subscription → read-only;
**every one of the 34 write routes returns 402** in an expired workspace while all reads
return 200.

### 4.5 Migrations (item 6)
* Clean database → head; schema identical to models (`compare_metadata` empty); downgrade to
  base leaves no tables.
* Synthetic legacy data → head → downgrade (data restored).
* Pre-Alembic database adoption (no `alembic_version`) via the normal startup path, idempotent.
* **Real previous application:** commit `f660731` checked out separately, its own startup
  created and seeded a PostgreSQL database and its own API wrote a player with private fields
  and a budget; the current application then started on it unchanged:
  `alembic_version = 0004_subscriptions`, 1 organization, **identical row counts in all 14
  legacy tables**, 0 rows without organization, private fields (fee, salary, agent,
  availability, role, notes) moved to the assessment, legacy logins work, second startup
  idempotent, `alembic check` → no differences. (This run found F18.)

### 4.6 Production configuration (item 8) — live uvicorn, `RAJA_ENV=production`, customer mode
`/docs` and `/openapi.json` → 404; public config without demo accounts; headers present: CSP,
HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy; CORS preflight from a
foreign origin → no `Access-Control-Allow-Origin`; login spray with 31 spoofed
`X-Forwarded-For` values from one real client → 30× 401 then 429, other client unaffected,
audit log stores the real IP. Startup refuses: missing/short `SECRET_KEY`, SQLite, wildcard
CORS, demo data in customer mode, customer data in demo mode. Tokens: `alg:none`, wrong key,
expired, garbage → 401; validly signed token for a foreign organization → 403. Secrets scan of
working tree and full git history: no keys, tokens or real credentials.

### 4.7 Backup and restore (item 8)
`scripts/backup.sh` → `scripts/verify_backup.sh` ("BACKUP VERIFIED", schema `0004`; tampered
manifest detected in an earlier run) → `pg_restore` into a brand-new database → application
started in production customer mode on the restored database: login 200, organization and
subscription intact, writes accepted. No temporary databases left behind.

## 5. Not verified (be explicit)
* Real Docker / Render deployment (no container runtime in the audit environment); the
  Dockerfile command and Render settings were reviewed, not executed.
* Third-party penetration test, load/DoS testing, dependency CVE scan.
* E-mail delivery (not implemented). Mobile browsers.

## 6. Remaining risks (accepted for a pilot, to address before general availability)

| Risk | Level | Note / mitigation |
|---|---|---|
| No multi-factor authentication | Medium | Mandatory before GA for directors/admins. |
| No PostgreSQL Row-Level Security | Medium | Isolation relies on the ORM layer + composite FKs + tests; RLS is the recommended defence-in-depth. |
| Links shared manually (no e-mail provider) | Medium (operational) | Share invitation/reset links only via a trusted channel; they expire and are single-use. |
| Bearer token in `sessionStorage`, 8 h lifetime, no idle timeout | Low | CSP reduces XSS risk; consider shorter tokens + refresh. |
| Account lockout can be triggered by others (5 failures / 15 min) | Low | Standard trade-off; monitor audit log. |
| E-mail existence visible to org admins (409 on direct create; invitation preview flag) | Low | Inherent to invitation flows. |
| Invitation token appears in the preview request path (server access logs) | Low | Keep access logs private; tokens are hashed at rest, expire, single-use. |
| Plan limits are checked per request (concurrent requests could exceed by one) | Low | Acceptable for seats/players. |
| Backup scripts pass the DB URL on the command line (visible in `ps`) | Low | Use `PGPASSFILE` on shared hosts. |
| Unbounded JSON body sizes (report sections, JSON import) | Low | Put a request-size limit on the reverse proxy (e.g. nginx `client_max_body_size`). |
| Trademark ("Raja" in product name), data-protection compliance (Loi 09-08 / CNDP), contracts | Legal | Outside code scope; required before commercial launch. |

## 7. Recommendation

**GO — for a supervised pilot with one (at most two) real clubs**, subject to these conditions:

1. A dedicated **customer** deployment (`DEPLOYMENT_MODE=customer`, `RAJA_ENV=production`) with
   its own PostgreSQL database — **not** the public Render demo.
2. HTTPS, strong unique `SECRET_KEY` and `POSTGRES_PASSWORD`, correct `TRUSTED_PROXY_HOPS` /
   `FORWARDED_ALLOW_IPS` for the hosting setup, API docs hidden.
3. Daily backups with `backup.sh` and a weekly `verify_backup.sh` restore check.
4. Accounts provisioned by invitation; links handed over through a trusted channel.
5. A signed pilot agreement covering personal data (Loi 09-08 / CNDP) and confidentiality.

**NO-GO for general availability / self-service sales** until MFA, transactional e-mail and
an external penetration test are in place, and the legal items in §6 are resolved.

This recommendation is based only on the tests and checks listed in §4, which were actually
run and passed; items in §5 were not verified.
