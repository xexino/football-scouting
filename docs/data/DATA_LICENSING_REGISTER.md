# Data licensing register

Authoritative list of what each data source may be used for. Maintained by the
`data-licensing-officer` council agent; changes to a status require founder approval.

**Statuses**
* `VERIFIED-COMMERCIAL-OK` — provider's own terms quoted below permit use in the paid product.
* `VERIFIED-NON-COMMERCIAL` — terms verified; research/internal use only, never in customer data.
* `UNVERIFIED` — terms not readable or ambiguous → **must not be used in production**.
* `PAID-CONTRACT` — only under a signed agreement (founder approval).
* `EXCLUDED` — would require scraping or has unknown provenance.

**Rule zero:** free access does not mean commercial redistribution permission.

| Source | Status | Permitted use | Basis (quoted / checked 2026-11-28) | Conditions |
|---|---|---|---|---|
| Wikidata | UNVERIFIED (expected CC0 — quote & archive licence page to verify) | Player/club identity (name, DOB, nationality, position, clubs, external IDs) | Wikidata project licence: structured data under CC0 (well established; licence page not fetched in this session — archive a copy before first import) | Respect WDQS rate limits + descriptive User-Agent; whitelist fields (no sensitive properties) |
| OpenFootball (football.json) | VERIFIED-COMMERCIAL-OK | Fixtures, results, club & competition names | README: "Free open public domain football (match fixtures & results) data" | Raw GitHub files; record commit/date |
| TheSportsDB — data | VERIFIED-COMMERCIAL-OK (data only) | Identity fields, cross-provider IDs, league/club metadata | Terms: "You may publicly display API data and monetise projects that use it … on both the free tier and paid plans"; "Please do not scrape our website" | Official API only; free key 30 req/min; **never import `strEthnicity`**; app-store publishing needs paid tier |
| TheSportsDB — images | UNVERIFIED per image | Only images whose `strCreativeCommons` = Yes **and** whose individual licence was checked | Terms: artwork under per-image Creative Commons; unknown licence "must not be used … publicly" | Default: do not import images |
| StatsBomb Open Data | VERIFIED-NON-COMMERCIAL | Internal methodology research only | Licence §1.2.1 may not "provide the data to any external or third party"; §1.2.2 may not "commercially exploit the data or any analysis derived" | Never imported into customer databases or shown in the product |
| football-data.org | UNVERIFIED | — (testing only) | Pricing/policies read; no terms page found (`/terms` → 404); commercial use not stated | Ask provider in writing before any production use |
| API-Football | UNVERIFIED | — (testing only, once a free key exists) | Official pages behind Cloudflare challenge; not bypassed | Obtain and archive terms before production use |
| Sportmonks | UNVERIFIED | — | Official pages return 403; secondary sources only | — |
| SportAPI (sportapi.ai) | UNVERIFIED | — | Site unreachable from the evaluation environment (2026-11-28); nothing verified | Founder to read & archive terms/pricing before any use |
| Wyscout (Hudl) | PAID-CONTRACT | — | Official: access via "Contact Sales" | Founder approval required |
| Club-imported data (CSV/JSON) | Customer's own licence | That customer only (tenant-private) | Platform rule: imports private to the importing organization | Customer warrants its rights at import (UI notice) |
| Transfermarkt, FBref, WhoScored, SofaScore, FotMob, Flashscore, unofficial APIs, scraped Kaggle sets | EXCLUDED | — | Would require scraping / unknown provenance | — |

## Personal-data rules (Loi 09-08 / CNDP, GDPR)
* Import only fields on the whitelist: name, known-as, date of birth, nationality, position(s),
  height, preferred foot, current club, external IDs, statistics.
* Never store special-category data (ethnicity, religion, health outside the medical module).
* Players are minors from 16: keep data minimal, record the source and date of every field,
  and support deletion on request.
