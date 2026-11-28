# Stage 4 — SaaS commercial foundations (P1)

Started only after tenant isolation was implemented and tested (stages 1–3).

## What changed

**Plans** (`app/subscriptions.py`) — Scout, Club Pro, Enterprise with seat limits, private-player
limits and features. Prices are not in code (founder decision, see `06_BILLING_OPTIONS.md`).

**Subscription per organization** (`subscriptions` table, migration `0004`): plan, status
(`trialing`, `active`, `past_due`, `suspended`, `canceled`, `expired`), trial end, paid-until
date, seat/player overrides, billing provider ids, notes. Migration grandfathers existing
customer organizations on an active Enterprise plan (no lock-out on upgrade).

**Effective status** — trial past its end → `expired`; active but past the paid-until date →
`past_due` for a 14-day grace period, then `expired`.

**Enforcement (backend, fail-closed)**
* Read-only mode: when the effective status is not `trialing`/`active`/`past_due` — or no
  subscription exists — every non-GET tenant request returns **402**; reading and data export
  continue to work (customers can always retrieve their data). Applied centrally in
  `security.get_ctx`, plus invitation acceptance.
* Seat limit: active members + pending invitations, checked on direct creation, invitation,
  and member reactivation.
* Private-player limit: checked on player creation and on each new player in CSV/JSON import
  (row-level error, other rows unaffected).
* Feature gating: JSON/API import requires Club Pro or Enterprise.
* Demo organizations are exempt (demo deployments only).

**Trial** — new customer organizations (CLI `create-org`, platform console) start a 30-day
Club Pro trial by default (configurable per organization).

**Platform operator console** (`/api/platform/*`, UI `#/platform`, `is_platform_admin`
accounts without tenant membership):
* list organizations with plan, effective status, usage counts — **no scouting data**;
* create an organization (+ trial + first-administrator invitation link); in a demo
  deployment new organizations are demo organizations;
* edit subscription (plan, status, trial end, paid-until, overrides), suspend, reactivate;
* schedule deletion, cancel, purge (slug confirmation);
* platform-level audit log (tenants never see platform events; platform never sees tenant
  events through this API).
* CLI equivalent for manual billing: `python -m app.cli set-plan SLUG PLAN [STATUS] [YYYY-MM-DD]`.

**Billing provider interface** (`app/billing/`) — `BillingProvider` (checkout URL, cancel,
webhook parsing → `BillingEvent`), `ManualBillingProvider` implemented, selected by
`BILLING_PROVIDER`; webhook route `/api/billing/webhook/{provider}` returns 404 for the manual
provider. **No paid provider integrated**, as instructed.

**UI** — subscription banner (trial ending, overdue, read-only), plan & usage card on the
Organization page, platform console.

## Tests

`test_subscriptions.py` (22): effective-status rules (8 cases); trial → expiry → read-only →
renewal; suspended/canceled/expired read-only; grace period; missing subscription fails
closed; demo unlimited; seat limit incl. pending invitations, revocation and reactivation;
player limit via API and import; feature gating; platform admin has no tenant access and the
organization list leaks no scouting data; full onboarding (create org → invitation →
admin) and subscription management, suspend/reactivate, platform vs tenant audit separation,
two-step purge via API; demo-deployment orgs are demo; manual provider has no webhooks.

Mutation checks: disabling the read-only check fails 6 tests; disabling the seat check fails
the seat test. Browser: operator console onboarding; expired customer workspace shows the
read-only banner, write attempt explained (402), plan card; earlier browser suites re-run
with no page errors.

Totals: SQLite 108 passed / 2 skipped; PostgreSQL 110 passed (incl. migrations 0001→0004).

## Remaining risks / next steps

* Prices, contract terms, invoicing (numbering, VAT/TVA in Morocco) are business decisions
  still open; manual billing needs an operator routine (weekly check of overdue accounts).
* Choose and integrate a payment provider only after the legal-entity decision (see
  `06_BILLING_OPTIONS.md`).
* No automated e-mails for trial ending / overdue yet (needs an e-mail provider).
* Usage limits are checked per request; two simultaneous creations could exceed a limit by
  one (acceptable for seats/players; use row locks if limits become billing-critical).
