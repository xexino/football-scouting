# Deployment

The application is a single stateless Python service (API + static frontend) in front of
PostgreSQL. It scales horizontally: run several app instances behind a load balancer,
all pointing at the same database.

## Option A — Docker Compose (single server)

```bash
cp .env.example .env
# edit .env:
#   RAJA_ENV=production
#   SECRET_KEY=<python -c "import secrets;print(secrets.token_urlsafe(48))">
#   POSTGRES_PASSWORD=<strong password>
#   DEPLOYMENT_MODE=customer
docker compose up -d --build
docker compose exec app python -m app.cli create-org my-club "My Club" Morocco MAD
docker compose exec app python -m app.cli create-user admin@club.ma "Administrator" administrator my-club
```

The database is stored in the `pgdata` volume. Do not expose port 5432 publicly.

## Option B — Linux server (systemd)

1. Install Python 3.11+, PostgreSQL and nginx. Follow [INSTALLATION.md](INSTALLATION.md).
2. `/etc/systemd/system/raja-scout.service`:

```ini
[Unit]
Description=Raja Scout Intelligence
After=network.target postgresql.service

[Service]
User=raja
WorkingDirectory=/srv/football-scouting/backend
EnvironmentFile=/srv/football-scouting/.env
ExecStart=/srv/football-scouting/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4 --proxy-headers
Restart=always

[Install]
WantedBy=multi-user.target
```

3. nginx with TLS (e.g. Let's Encrypt):

```nginx
server {
    listen 443 ssl http2;
    server_name scout.rajaclubathletic.ma;
    ssl_certificate     /etc/letsencrypt/live/scout.rajaclubathletic.ma/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/scout.rajaclubathletic.ma/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;
    client_max_body_size 12m;      # CSV uploads (app limit is 10 MB)
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Option C — managed cloud

Any container platform works (AWS ECS/Fargate, Azure Container Apps, Google Cloud Run,
Render, Fly.io) with a managed PostgreSQL (RDS, Azure Database, Cloud SQL). Build the
`Dockerfile`, set the environment variables, and run `python -m app.cli init-db` and
`create-user` once as a one-off task. Consider hosting in a region compatible with Moroccan
data-protection law (Loi 09-08, CNDP) since the database contains personal data.

## Production checklist

- [ ] `RAJA_ENV=production`, strong unique `SECRET_KEY`, `DEPLOYMENT_MODE=customer`, `PUBLIC_BASE_URL` set
- [ ] Demo and customer deployments use **separate databases** (the app refuses to mix them)
- [ ] Client IP behind proxies: `TRUSTED_PROXY_HOPS` = number of proxies you control (1 on most PaaS, 1 behind a single nginx), `FORWARDED_ALLOW_IPS` = proxy address (or `*` only together with `TRUSTED_PROXY_HOPS≥1`) — otherwise login throttling and audit IPs can be spoofed
- [ ] `POSTGRES_PASSWORD` set (docker compose refuses to start without it); `EXPOSE_API_DOCS` left unset (hidden in production)
- [ ] Every backup verified with `scripts/verify_backup.sh` (at least weekly)
- [ ] HTTPS only; database not reachable from the internet
- [ ] Demo accounts absent; every staff member has a personal account with the least-privileged role
- [ ] Automated backups scheduled and a restore tested
- [ ] Data sources registered with their licence terms before any import
- [ ] Log retention defined for the audit log

## Backups

Full physical backups with `pg_dump` (custom format, compressed, 30-day retention):

```bash
DATABASE_URL=postgresql://raja:PW@localhost:5432/raja_scout scripts/backup.sh /var/backups/raja-scout
```

Schedule it daily, e.g. `crontab -e`:
```
15 2 * * * DATABASE_URL=postgresql://raja:PW@localhost:5432/raja_scout /srv/football-scouting/scripts/backup.sh /var/backups/raja-scout >> /var/log/raja-backup.log 2>&1
```
Copy backups off-site (encrypted). Restore with `scripts/restore.sh <file>` (asks for
confirmation; destructive).

Logical exports are also available in the UI (**Administration → Download full export**,
JSON of every table without password hashes) and as `GET /api/admin/export`.

## Upgrades

```bash
git pull
pip install -r backend/requirements.txt
systemctl restart raja-scout
```

Schema changes are Alembic migrations, applied automatically at startup
(`alembic upgrade head`); a database created before migrations existed is detected and
adopted. Always take (and verify) a backup before upgrading.
