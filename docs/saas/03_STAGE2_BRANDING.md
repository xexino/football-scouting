# Stage 2 — Independent commercial branding (P0)

## What changed

* **Organization identity** — `GET/PATCH /api/organization`: name, short name, country,
  primary language (`en`, `fr`, `ar`), currency (North African, African and common transfer
  currencies), IANA timezone, and whitelisted settings (`home_league`, `report_footer`,
  `accent_color`). Only the organization administrator (`org:manage`) can edit; every change is
  audit-logged.
* **Logo** — `POST/DELETE /api/organization/logo`. PNG/JPEG/WebP only, detected from the file
  signature (the client-declared type is ignored), max 256 KB, stored as a data URL. SVG is
  refused (script injection vector).
* **Customer identity in the product** — sidebar shows the customer's logo and name with
  "Raja Scout Intelligence" as the software brand; page title and `lang` follow the
  organization; optional accent colour; organization switcher for multi-club users; demo
  organizations show a persistent "fictional data" banner.
* **Currency** — fees, salaries and budgets display in the organization's currency.
* **Reports** — exports carry the organization name, its configurable footer and the
  independence notice; the risk note uses the organization's `home_league` instead of a
  hard-coded "Botola Pro".
* **No customer = Raja assumptions** — removed from API description, validation messages,
  analytics notes, report generator, frontend copy, HTML metadata and docs. The product mark
  changed from a crest-like shield to a neutral radar glyph to avoid suggesting a club badge.
* **Non-affiliation notice** — on the login page, organization page, API description, README
  and exported reports: *independent software, not affiliated with, endorsed or sponsored by
  Raja Club Athletic or any club using it*.

## Tests

`test_organization.py` (13 tests): member read access; admin-only updates; 6 invalid-input
cases; logo signature validation (SVG, spoofed type, oversize, permission); per-organization
isolation of branding and audit; currency and home league flowing into players, reports and
dashboard; product copy free of club-as-customer wording. A real bug was found and fixed
(clearing a setting was silently ignored).

Totals: SQLite 67 passed / 2 skipped; PostgreSQL 69 passed. Browser check: logo
upload, accent colour, title and sidebar branding verified with no page errors.

## Remaining risks

* **Trademark:** the software name itself contains "Raja". Even with notices, a club or
  federation could object. A trademark clearance search (OMPIC in Morocco, plus target
  markets) is recommended before commercial launch; consider a neutral product name.
* **Language** is stored and applied to `lang`, but the UI is not yet translated (FR/AR copy
  and RTL layout are a follow-up).
* Currency change does not convert existing amounts (documented in the UI).
* Login page still lists demo accounts in every environment → fixed in stage 3
  (deployment modes).
