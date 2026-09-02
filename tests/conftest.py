"""
Shared fixtures (SPEC.md M1): a fresh temp-SQLite DB per test, and two
seeded users (A/B) for the cross-tenant isolation suite. Every DB-touching
test in this repo used to duplicate a `_fresh_test_db(tmp_path, monkeypatch)`
helper inline - this consolidates that plus adds the auth layer the old
single-user tests never needed.
"""
import pytest
from sqlmodel import Session

from core.infra.config import SESSION_COOKIE_NAME


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """core.domain.settings caches per user_id at module level (by design - it's
    read on every cost calc for every listing on every render) - without
    this, a test that dirties the cache could leak a stale Settings object
    into whichever test runs next, regardless of which temp DB it set up."""
    import core.domain.settings as settings_module
    settings_module._cache.clear()
    yield
    settings_module._cache.clear()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Fresh temp-SQLite DB for one test. Returns the core.infra.db module so
    callers can do `Session(db.get_engine())` etc., matching the old
    per-file `_fresh_test_db` helpers this replaces."""
    from core.infra import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(config, "PHOTOS_DIR", tmp_path / "photos")

    from core.infra import db as db_module
    monkeypatch.setattr(db_module, "DB_URL", config.DB_URL)
    db_module.reset_engine()
    db_module.init_db()
    return db_module


def _make_user(db_module, email: str):
    from core.accounts.auth import hash_password
    from core.models import Settings, User

    with Session(db_module.get_engine()) as session:
        user = User(email=email, password_hash=hash_password("a-strong-password-1"),
                    email_verified_at=None)
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(Settings(user_id=user.id))
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


@pytest.fixture
def user_a(db):
    return _make_user(db, "alice@example.com")


@pytest.fixture
def user_b(db):
    return _make_user(db, "bob@example.com")


# Backwards-compatible alias for tests that only need one user and don't
# care about the isolation angle.
@pytest.fixture
def user(user_a):
    return user_a


def _login_client(db_module, user):
    from fastapi.testclient import TestClient

    from core.accounts.auth import create_session
    from main import app

    with Session(db_module.get_engine()) as session:
        token, auth_session = create_session(session, user)
        csrf_token = auth_session.csrf_token  # read before the session (and its commit-expiry) closes
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    # Mirrors base.html's hx-headers, which a real browser sends on every
    # htmx request - TestClient doesn't execute JS, so tests need this set
    # explicitly or every mutating request would 403 on the CSRF check.
    client.headers["X-CSRF-Token"] = csrf_token
    return client


@pytest.fixture
def client(db, user_a, monkeypatch):
    """Legacy authenticated client for unit-testing preserved domain routes."""
    from core.infra import demo_session
    monkeypatch.setattr(demo_session, "DEMO_MODE", False)
    with _login_client(db, user_a) as c:
        yield c


@pytest.fixture
def client_b(db, user_b, monkeypatch):
    """Second authenticated client used by selected ownership tests."""
    from core.infra import demo_session
    monkeypatch.setattr(demo_session, "DEMO_MODE", False)
    with _login_client(db, user_b) as c:
        yield c


@pytest.fixture
def anon_client(db):
    """TestClient with no session cookie at all."""
    from fastapi.testclient import TestClient

    from main import app
    with TestClient(app) as c:
        yield c
