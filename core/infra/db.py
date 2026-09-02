from sqlmodel import Session, SQLModel, create_engine

from core.infra.config import DB_URL, ensure_dirs

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        ensure_dirs()
        url = DB_URL
        # TestClient and the hosted demo use worker threads, so SQLite must
        # allow a connection to cross thread boundaries.
        if url.startswith("sqlite"):
            _engine = create_engine(url, connect_args={"check_same_thread": False})
        else:
            _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine so a changed DB_URL takes effect - used by
    tests that monkeypatch core.infra.db.DB_URL between runs."""
    global _engine
    _engine = None


def init_db() -> None:
    """Create the small showcase schema in its disposable SQLite database."""
    SQLModel.metadata.create_all(get_engine())


def new_session() -> Session:
    """Every router opens its own short-lived session with this rather than
    FastAPI's Depends(...) generator pattern, since none of them need
    request-scoped dependency injection - a plain context manager is enough."""
    return Session(get_engine())
