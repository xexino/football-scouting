# Delivery status & roadmap

## Delivered

**MVP (functional with fictional sample data)** and the core of the **professional version**:

* PostgreSQL schema with provenance on all factual records; SQLite supported for tests.
* Authentication (bcrypt + JWT), 6 roles / 18 permissions, field-level financial redaction,
  login throttling, security headers, audit log, production safety checks.
* Player database, advanced search with statistical filters and metric sorting.
* Analytics: per-90, ratio thresholds, league adjustment, percentile pools, consistency,
  role fit, caveats.
* Comparison of 2–5 players with radar, tables, strengths/weaknesses, suitability,
  financial and scouting profiles.
* Video scouting with licence enforcement and highlight flagging; match reports.
* Evidence-tagged scouting reports with editing, finalisation/lock, Markdown export, print.
* Recruitment pipeline with role rules, evidence gates and immutable history.
* Executive dashboard incl. budget and scout productivity.
* CSV and JSON import with dry run; CSV/JSON export; `pg_dump` backup/restore scripts.
* Responsive dependency-free frontend; Docker/compose; CI on SQLite + PostgreSQL; docs.

## Recommended next steps

1. **Alembic migrations** before the first schema change in production.
2. **Provider adapters** once a data contract is signed (Wyscout, StatsBomb, Opta, InStat,
   or federation feeds) — scheduled ETL into `/api/import/json`.
3. **Real league coefficients** with a documented methodology.
4. **SSO** (Microsoft 365 / Google Workspace) and optional 2FA for directors.
5. **Region-scoped visibility** for regional scouts if required by club policy.
6. **Scouting assignments & calendar** (fixtures to cover, travel), and mobile-first live
   report entry with offline support.
7. **Medical / injury history** module with restricted access.
8. **LLM-assisted drafting** (optional): summarise scout notes into prose while preserving the
   evidence tags — never generating facts or ratings.
9. Persistent login throttling (Redis) when running multiple instances.
