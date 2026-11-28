"""Stage 3: deployment modes, production configuration, DB-backed login throttling."""
import pytest
from sqlalchemy import delete, func, select

from app import main as app_main
from app.config import Settings, settings
from app.models import LoginAttempt, Organization
from conftest import _sys, demo_only_database


def test_public_config_shows_demo_accounts_only_in_demo_mode(client, monkeypatch):
    assert "demo_accounts" in client.get("/api/public/config").json()
    monkeypatch.setattr(settings, "deployment_mode", "customer")
    cfg = client.get("/api/public/config").json()
    assert cfg["deployment_mode"] == "customer" and "demo_accounts" not in cfg
    assert "not affiliated" in cfg["notice"].lower()


def test_customer_deployment_refuses_demo_data(client, monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "customer")
    with pytest.raises(RuntimeError, match="contains demo organizations"):
        app_main.check_environment_separation()
    from app.seed import seed
    with _sys() as db, pytest.raises(RuntimeError, match="DEPLOYMENT_MODE=demo"):
        seed(db)


def test_demo_deployment_refuses_customer_data(client):
    with demo_only_database():
        _check_refuses_customer_data()


def _check_refuses_customer_data():
    with _sys() as db:
        org = Organization(slug="real-customer", name="Real Customer", settings={}, is_demo=False)
        db.add(org)
        db.commit()
        try:
            with pytest.raises(RuntimeError, match="must never be exposed in a demo environment"):
                app_main.check_environment_separation()
        finally:
            db.delete(org)
            db.commit()
    app_main.check_environment_separation()  # clean again


@pytest.mark.parametrize("env, msg", [
    ({"RAJA_ENV": "production", "SECRET_KEY": ""}, "SECRET_KEY must be set"),
    ({"RAJA_ENV": "production", "SECRET_KEY": "short"}, "at least 32"),
    ({"RAJA_ENV": "production", "SECRET_KEY": "x" * 40, "DATABASE_URL": "sqlite:///x.db"}, "SQLite is not supported"),
    ({"DEPLOYMENT_MODE": "staging"}, "DEPLOYMENT_MODE must be"),
])
def test_production_configuration_is_enforced(monkeypatch, env, msg):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(RuntimeError, match=msg):
        Settings()


def test_production_defaults_to_customer_mode(monkeypatch):
    monkeypatch.setenv("RAJA_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
    s = Settings()
    assert s.deployment_mode == "customer" and s.database_url.startswith("postgresql+psycopg://")


def test_security_headers(client, monkeypatch):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" not in r.headers
    monkeypatch.setattr(settings, "env", "production")
    assert "max-age" in client.get("/api/health").headers["strict-transport-security"]


def test_login_throttle_is_stored_in_database(client):
    email = "throttle-db@example.com"
    for _ in range(3):
        client.post("/api/auth/token", data={"username": email, "password": "wrong"})
    with _sys() as db:
        n = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.key == f"account:{email}"))
    assert n == 3  # shared by every app instance, survives restarts


def test_login_throttle_per_ip(client, monkeypatch):
    def clear_ip_counters():
        with _sys() as db:
            db.execute(delete(LoginAttempt).where(LoginAttempt.key.like("ip:%")))
            db.commit()

    clear_ip_counters()  # earlier tests share the same test-client IP
    monkeypatch.setattr(settings, "max_login_attempts_per_ip", 4)
    try:
        for i in range(4):  # different accounts, same client IP
            assert client.post("/api/auth/token", data={"username": f"spray{i}@example.com", "password": "x"}).status_code == 401
        r = client.post("/api/auth/token", data={"username": "director@raja-scout.local", "password": "RajaDemo2026!"})
        assert r.status_code == 429  # even correct credentials are refused from a sprayed IP
    finally:
        clear_ip_counters()
