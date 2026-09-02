"""Cached accessor for the per-user Settings row (core.models.Settings).

Read on every cost calculation for every listing on every render (via
core.domain.costs), so it's cached in-process per user_id rather than re-queried
each time - call invalidate_cache(user_id) after any write so the next
read picks it up.
"""
from sqlmodel import Session, select

from core.infra.db import get_engine
from core.models import Settings

_cache: dict[str, Settings] = {}


def get_settings(user_id: str) -> Settings:
    if user_id in _cache:
        return _cache[user_id]
    with Session(get_engine()) as session:
        row = session.exec(select(Settings).where(Settings.user_id == user_id)).first()
        if row is None:
            row = Settings(user_id=user_id)
            session.add(row)
            session.commit()
            session.refresh(row)
        session.expunge(row)
    _cache[user_id] = row
    return row


def invalidate_cache(user_id: str) -> None:
    _cache.pop(user_id, None)
