# Data governance & licensing

## Provenance

* Every player profile and stat line references a **data source** (name, type, URL,
  licence notes) and carries `last_updated`. Imports without a registered source are refused.
* Fictional demo data uses the source `FICTIONAL SAMPLE DATA` and `is_fictional = true`
  on players, stats, leagues and clubs. The UI badges it everywhere; reports and analytics
  repeat the warning; the API refuses to finalise a *sign* recommendation for a fictional player.
* Scout opinions (match reports, observations, report items) are stored separately from
  data and always attributed to their author.

## No fabricated statistics

The platform never generates or imputes statistics for real players. Empty values remain
`null`. The only generated numbers are the clearly marked fictional demo set.

## Licensed data and footage

* Import only data your organization has a licence to use (provider contract, federation data, own
  collection). Record the contract reference in the source's licence notes.
* **No unauthorised scraping.** The platform contains no scrapers. Do not import data
  scraped from websites whose terms forbid it.
* **No redistribution.** Exports are for internal club use; do not share provider data
  outside the terms of the licence.
* Video is **linked, never hosted**. Registering footage requires the rights holder and an
  explicit licence confirmation by the user, which is audit-logged.

## Personal data (Loi 09-08 / GDPR)

Player records are personal data. Recommended practices:
* Keep data minimal and relevant to recruitment; avoid health data unless handled by medical
  staff under proper controls.
* Restrict accounts to staff who need them (least-privileged roles); deactivate leavers.
* Host in an appropriate jurisdiction; encrypt backups; define a retention period for
  players no longer of interest.
* The audit log records who viewed exports and changed data.

## Integrating a licensed provider

Write an adapter that maps the provider's feed to the CSV/JSON column names
(`docs/API.md`, `GET /api/import/templates/*.csv`) and posts to `POST /api/import/json`
under a dedicated data source. Keep the provider's IDs in `source_reference` so updates
match the same player.
