# Installation

## Requirements

* Python **3.11+** (tested on 3.13)
* PostgreSQL **14+** (tested on 16)
* Any modern browser. The frontend has no build step and loads no external scripts or fonts,
  so it works on an isolated club network.

## 1. Create the database

```bash
sudo -u postgres psql <<'SQL'
CREATE USER raja WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE raja_scout OWNER raja;
SQL
```

## 2. Install the backend

```bash
git clone https://github.com/xexino/football-scouting.git
cd football-scouting/backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt      # requirements-dev.txt adds pytest
```

## 3. Configure

Copy `.env.example` (repository root) and export the variables, or set them in your process
manager. The important ones:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://raja:raja@localhost:5432/raja_scout` | SQLAlchemy URL |
| `RAJA_ENV` | `development` | `production` enforces a SECRET_KEY and blocks demo data |
| `SECRET_KEY` | random per start (dev) | JWT signing key — **required** in production, ≥32 chars |
| `DEPLOYMENT_MODE` | `demo` (dev) / `customer` (production) | `demo`: fictional demo organization + demo accounts; refuses customer data. `customer`: real clubs; never loads demo data |
| `PUBLIC_BASE_URL` | request URL | Base URL used in invitation and password-reset links |
| `TRUSTED_PROXY_HOPS` | `0` | Reverse proxies you control in front of the app; the client IP is taken from that position in `X-Forwarded-For` (never the client-supplied left-most entry) |
| `EXPOSE_API_DOCS` | on in development, off in production | Serve `/docs`, `/redoc`, `/openapi.json` |
| `DEMO_PASSWORD` | `RajaDemo2026!` | Demo account password |
| `TOKEN_EXPIRE_MINUTES` | `480` | Session length |
| `MIN_MINUTES_RELIABLE` | `900` | Below this, per-90 figures are flagged as a small sample |
| `MIN_MINUTES_POOL` | `450` | Minimum minutes to enter percentile reference pools |
| `CORS_ORIGINS` | empty | Only needed if the UI is hosted on a different origin |

In development, without `SECRET_KEY`, a random key is generated at each start (users must
log in again after a restart).

## 4. Initialise

Demo mode (fictional data):
```bash
uvicorn app.main:app --reload
```

Real deployment (no demo data):
```bash
export DEPLOYMENT_MODE=customer
python -m app.cli init-db                                   # runs Alembic migrations
python -m app.cli create-user ops@yourcompany.com "Platform Operator" platform_admin
python -m app.cli create-org atlas-fc "Atlas FC" Morocco MAD fr
python -m app.cli create-user admin@atlasfc.ma "Club Administrator" administrator atlas-fc
# the club administrator then invites colleagues from Administration → Invite member
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Roles: `administrator`, `sporting_director`, `head_of_scouting`, `data_analyst`,
`video_scout`, `regional_scout`. Further users can be created in **Administration**.

## 5. Verify

```bash
curl http://localhost:8000/api/health     # {"status":"ok",...}
pytest -q                                 # from backend/
```

Open `http://localhost:8000` and log in.
