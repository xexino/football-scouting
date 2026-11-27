# Raja Scout Intelligence

A football scouting and recruitment-intelligence platform built for **Raja Club Athletic**
(Casablanca). It gives the club an independent, evidence-based international recruitment
capability: a central player database, position-specific analytics, comparison, licensed
video scouting, evidence-tagged scouting reports and a governed recruitment pipeline with
full decision history.

> **Sample data notice.** On first start the platform loads ~96 **fictional** players, clubs,
> leagues, statistics and reports so the workflow can be explored. Everything fictional is
> flagged `is_fictional`, carries the source `FICTIONAL SAMPLE DATA`, has names ending in
> `-Fict` / `(fictional)` and is shown with a **FICTIONAL** badge. It is randomly generated
> and must never inform a real decision. Disable it with `SEED_SAMPLE_DATA=false`.

## Features

| Module | What it does |
|---|---|
| **Player database** | Identity, club/league, positions, physical profile, contract, fee & salary estimates, season statistics — every record with data source and `last_updated`. |
| **Advanced search** | Position (primary/secondary), tactical role, age, nationality, league, club, height, foot, contract expiry, fee/salary, availability, pipeline stage, minutes and *any* statistical indicator (`prog_passes_p90>=4`). Sort by any metric. |
| **Analytics** | Per-90 normalisation, ratio metrics with minimum-attempt thresholds, optional documented league-strength adjustment, percentile vs. position pool, consistency across seasons, model-based tactical role fit, and explicit caveats (sample size, pool size, correlation ≠ quality). |
| **Comparison** | 2–5 players, same position: radar chart, metric table, data-derived strengths/weaknesses, role suitability, financial profile, scouting assessments. |
| **Video scouting** | Link licensed footage (never hosted), licence confirmation, timestamped categorised observations, match reports. Highlights are flagged and can never count as full-match analysis. |
| **Scouting reports** | Draft generator assembling profile, statistics, technical/tactical/physical/mental, video, potential & risk, recommendation — each line tagged DATA / SCOUT / MODEL / NO EVIDENCE / INPUT REQUIRED. Finalise & lock, Markdown export, print. |
| **Recruitment pipeline** | Identified → Under Observation → Data Analysis → Video Analysis → Shortlisted → Live Scouting → Approved → Negotiation → Signed / Rejected, with role rules, evidence gates and immutable history. |
| **Executive dashboard** | Database size, players by position/nationality, priority targets, under observation, shortlist, budget (committed/pending/remaining), weekly scouting activity and scout productivity. |
| **Security** | bcrypt passwords, JWT, 6 roles with fine-grained permissions, field-level redaction of financials, login throttling, audit log of every change. |
| **Data operations** | CSV import (players & stats) with dry run and per-row errors, JSON import endpoint for provider/ETL integration, CSV/JSON export, `pg_dump` backup/restore scripts. |

## Quick start (local)

Requirements: Python 3.11+ and PostgreSQL 14+.

```bash
# 1. Database
sudo -u postgres psql -c "CREATE USER raja WITH PASSWORD 'raja' CREATEDB;"
sudo -u postgres createdb -O raja raja_scout

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload            # tables + fictional demo data created on first start

# 3. Open http://localhost:8000  (API docs: http://localhost:8000/docs)
```

Or with Docker: `docker compose up --build`.

### Demo accounts (fictional demo mode only)

Password for all: `RajaDemo2026!` (override with `DEMO_PASSWORD`).

| Email | Role |
|---|---|
| `director@raja-scout.local` | Sporting Director |
| `head.scouting@raja-scout.local` | Head of Scouting |
| `analyst@raja-scout.local` | Data Analyst |
| `video@raja-scout.local` | Video Scout |
| `scout.westafrica@raja-scout.local` / `scout.europe@raja-scout.local` | Regional Scout |
| `admin@raja-scout.local` | Administrator |

Demo accounts are refused when `RAJA_ENV=production`.

## Tests

```bash
cd backend
pytest -q                                                   # SQLite, fast
TEST_DATABASE_URL=postgresql+psycopg://raja:raja@localhost:5432/raja_scout_test pytest -q
```

41 tests cover the analytics maths, authentication & permissions, financial redaction,
search filters, stats validation, CSV/JSON import, video licensing rules, report evidence
tagging, the full pipeline lifecycle with its gates, comparison and the dashboard. CI runs
both databases (`.github/workflows/tests.yml`).

## Repository layout

```
backend/app/
  main.py              FastAPI app, static frontend, startup
  models.py            SQLAlchemy models (PostgreSQL schema)
  analytics.py         per-90, percentiles, league adjustment, role fit, consistency
  report_generator.py  evidence-tagged report drafting
  importers.py         CSV / JSON import logic
  security.py          auth, roles & permissions
  routers/             one module per API area
  seed.py              fictional demo data
  cli.py               init-db, seed-demo, create-user, schema-sql
backend/tests/         pytest suite
frontend/              dependency-free SPA (HTML/CSS/JS, inline SVG charts)
docs/                  installation, deployment, user guide, API, analytics, governance, schema.sql
scripts/               backup.sh / restore.sh
```

## Documentation

* [Installation](docs/INSTALLATION.md) · [Deployment](docs/DEPLOYMENT.md)
* [User guide](docs/USER_GUIDE.md) — workflows for each role
* [API reference](docs/API.md) — plus live OpenAPI at `/docs`
* [Analytics methodology](docs/ANALYTICS.md)
* [Data governance & licensing](docs/DATA_GOVERNANCE.md)
* [Database schema](docs/schema.sql) · [Roadmap](docs/ROADMAP.md)
