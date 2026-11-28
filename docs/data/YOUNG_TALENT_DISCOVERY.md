# Young Talent Discovery — design proposal

**Status:** proposal for founder approval (2026-11-28). Nothing below is implemented yet; per
the brief, the provider comparison and coverage matrix come first and no unverified source is
implemented. Evidence: `GLOBAL_PROVIDER_COMPARISON.md`, `COMPETITION_COVERAGE_MATRIX.md`,
`DATA_LICENSING_REGISTER.md`.

## 1. What the evidence allows today

| Need | Legally usable source now | Gap |
|---|---|---|
| Young-player identity (name, DOB, nationality, position, club) | Wikidata (CC0 — coverage not yet measured, endpoint rate-limited during test); TheSportsDB data (Europe / S. America) | African squads sparse everywhere tested |
| Clubs, competitions, fixtures | OpenFootball (public domain), TheSportsDB metadata | Morocco not in OpenFootball |
| Minutes, appearances, goals, assists | **none verified** | needs API-Football test → written terms, or paid provider, or club-imported data |
| Youth competitions (U17–U23) | **none verified** | Wyscout youth pack (paid) — founder decision |

So the first release is an **identity-first discovery tool**: find and track 16–23-year-olds,
with statistics only where a club has imported them under its own licence.

## 2. Provider-independent architecture

```
Provider adapters (one per source, server-side only, keys via secret store)
   │  fetch → validate → whitelist fields → normalise
   ▼
Staging records (raw payload hash, provider, provider_id, fetched_at)
   │  identity matching + duplicate detection
   ▼
Global reference layer (shared, organization_id NULL — platform-curated)
   players · clubs · competitions · seasons · provider_identifiers · player_season_stats
   every row: source, source licence status, fetched_at, last_updated
   ▼
Tenant layer (existing, private per club)
   assessments · scout ratings · potential ratings · reports · pipeline
```

* New tables: `competitions`, `seasons`, `provider_identifiers (entity, entity_id, provider,
  external_id, UNIQUE(provider, external_id))`, `import_runs (provider, started, finished,
  requests_used, quota_remaining, errors, rows_new/updated/skipped)`.
* Reuses existing shared-or-private tenancy: imported reference data is shared
  (`organization_id IS NULL`), only from sources marked `VERIFIED-COMMERCIAL-OK`.
* Importers are SYSTEM-context CLI/scheduled jobs, never request handlers; per-provider
  token-bucket rate limiting, `Retry-After` handling, resumable cursors, quota recorded per run.
* Field whitelist enforced in code + test (e.g. `strEthnicity` can never be stored).

## 3. Identity matching & duplicates

1. Exact match on any shared external ID (Wikidata QID, TheSportsDB id, API-Football id).
2. Otherwise candidate match: normalised name (accents, Arabic/French transliteration
   variants) + date of birth (exact) + nationality → auto-link only when all three agree.
3. Partial agreement → `possible duplicate` queue for human review; never auto-merge on name only.
4. Merges are reversible and audit-logged.

## 4. Young Talent Discovery page

Filters: age 16–23 (computed from DOB at a reference date), region/country, competition,
club, position, minutes & appearances, goals & assists, scout rating, potential rating.

* **Two visually separate blocks per player:** *Data* (each figure with source + date, or
  "no data from a licensed source") and *Scouting* (ratings and notes by named scouts of the
  club). Filters on data and on scouting opinion are labelled separately.
* Coverage warnings: when a filter depends on statistics that a competition lacks, the player
  is shown as "not evaluable" rather than silently excluded.

## 5. AI-assisted discovery — rules

* Input: the club's recruitment profile (position, age band, physical/technical needs, budget)
  + only data stored in the platform.
* Output per suggestion: *why it matched* (each criterion with the field and source used),
  *missing data* (criteria that could not be evaluated), *confidence = data coverage*, never a
  quality verdict.
* Never invents statistics or observations; never labels a player a "guaranteed future star"
  (enforced by output validation + test).
* Scouts can **accept** (→ pipeline "Identified"), **reject** (with reason) or **flag** (data
  problem); decisions are audit-logged and used to tune the profile, not the data.

## 6. Proposed delivery order (after approval)

1. Reference schema + Wikidata identity importer + matching + data-quality tests.
2. Discovery page on identity data; club-imported statistics shown with provenance.
3. AI-assisted matching with explanations and accept/reject/flag.
4. Statistics provider — only after the founder approves terms in writing.
