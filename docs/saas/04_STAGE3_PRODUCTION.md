# Stage 3 — Production readiness (P0)

## What changed

**Separation of demo and customer environments** — `DEPLOYMENT_MODE`
| | `demo` | `customer` |
|---|---|---|
| Default | development | `RAJA_ENV=production` |
| Demo organization & accounts | seeded | never (seeding raises) |
| Startup guard | refuses to start if any **non-demo** organization exists | refuses to start if a **demo** organization exists |
| Login page | lists demo accounts (`/api/public/config`) | no demo hints |

The rule "never expose real customer data in a public demo" is enforced by the application
at startup, not left to configuration discipline. Use separate databases for demo and
customer deployments. The Render blueprint is a demo deployment.

**Secure production configuration** — `RAJA_ENV=production` requires a ≥32-character
`SECRET_KEY`, refuses SQLite, adds HSTS; `EXPOSE_API_DOCS=false` hides `/docs`;
`Permissions-Policy`, `X-Frame-Options`, `nosniff`, `Referrer-Policy` on all responses.

**Login throttling for multiple instances** — failed attempts are stored in
`login_attempts` (PostgreSQL), so limits hold across workers/instances and restarts:
`MAX_LOGIN_ATTEMPTS` per account and `MAX_LOGIN_ATTEMPTS_PER_IP` per client IP within
`LOGIN_LOCKOUT_SECONDS`. Old rows are pruned on write. (Behind a proxy, run uvicorn with
`--proxy-headers` and a trusted `--forwarded-allow-ips` so the real client IP is used.)

**Individual account provisioning**
* Invitations: an organization admin invites by e-mail and role; the invitee opens a
  single-use link (256-bit token, stored as SHA-256 hash, 7-day expiry, revocable, one live
  invitation per address) and chooses their own password. If the e-mail already has an
  account, accepting requires that account's **current password**, so a leaked link cannot
  attach someone else's account.
* Password reset links: issued by the organization admin, single use, 24 h, revoke all
  sessions when used; refused for accounts that also belong to another organization or are
  platform operators (prevents cross-tenant takeover).
* No e-mail provider is integrated yet: links are shown once to the admin (`send_link` hook
  in `app/accounts.py` for a future provider).
* CLI for a new customer: `create-org`, `create-user … administrator <slug>`,
  `create-user … platform_admin`.

**Tenant data export and deletion**
* Export: `GET /api/admin/export` (org admin) or `python -m app.cli export-org SLUG FILE` —
  all of the organization's private rows + shared rows it uses, members without password
  hashes.
* Deletion (`app/lifecycle.py`, `python -m app.cli delete-org SLUG`), two-step:
  1. *schedule* → status `pending_deletion`: all members lose access immediately, data kept;
  2. *purge* → only when scheduled and the slug is typed again; deletes the organization and,
     through `ON DELETE CASCADE`, every tenant row; removes accounts that belong to no other
     organization; keeps a platform-level audit record with row counts only.
  Shared reference data and other organizations are untouched (tested).

**Backup and restore verification** — `scripts/backup.sh` writes a row-count manifest next
to each dump; `scripts/verify_backup.sh` restores the dump into a temporary database,
compares every table's row count with the manifest, checks the Alembic revision and always
drops the temporary database. Verified on PostgreSQL here, including a negative test
(tampered manifest → "BACKUP VERIFICATION FAILED").

**Migration** `0003_accounts`: `login_attempts`, `invitations` (tenant-private, auto-isolated),
`password_reset_tokens`.

**Frontend** — demo hint only in demo mode; public pages `#/invite/<token>` and
`#/reset/<token>`; Administration: invite member, pending invitations with revoke, reset link
per member. A navigation race was found by the browser test and fixed: a slow view could
overwrite a newer page after quick navigation. Every API call now carries a route sequence
number and stale responses are discarded.

## Tests

* `test_production.py` (12): demo accounts only in demo mode; customer mode refuses demo data
  and seeding; demo mode refuses customer organizations; four production-config failures;
  production defaults; security headers incl. HSTS; DB-stored throttle; per-IP throttle.
* `test_accounts.py` (6): full invitation flow (hash-only storage, single use, role/org),
  revoked/expired/unknown links, re-invite revokes old link, existing-account ownership proof,
  invitation isolation between organizations, reset link flow + session revocation, reset
  refused for multi-organization accounts.
* `test_lifecycle.py` (2): two-step deletion removes all 12 kinds of tenant rows and only
  those; consultant account in another org kept; audit record; SYSTEM-context requirement.
* Migration tests now cover `0001 → 0003`.
* Browser: invitation → acceptance in a separate browser → reset link → login → reuse refused;
  full scouting workflow and branding re-run after the navigation fix — no page errors.
* CLI customer provisioning on a fresh PostgreSQL database; demo mode refused on it.

Totals: SQLite 86 passed / 2 skipped; PostgreSQL 88 passed.

## Remaining risks

* No transactional e-mail yet (links are copied manually); add a provider (e.g. SES,
  Postmark, Brevo) before self-service "forgot password".
* No MFA yet; recommended for sporting directors and administrators.
* PostgreSQL Row-Level Security not yet enabled (defence-in-depth candidate).
* Deletion is immediate after the second step; a retention grace period (e.g. 30 days
  between schedule and purge) should be agreed contractually and automated.
* Backups are logical (`pg_dump`); for large customers consider point-in-time recovery
  (managed PostgreSQL / WAL archiving) and encrypted off-site copies.
