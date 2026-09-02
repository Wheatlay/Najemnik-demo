"""FetchCache read-through (SPEC §7): reuse a successful fetch of the same
normalized URL from any user, newer than 6 hours, before hitting the
network again."""
from datetime import datetime, timedelta

from sqlmodel import Session, select

from core.infra.db import get_engine
from core.models import FetchCache

CACHE_TTL = timedelta(hours=6)


def get_cached(url_normalized: str) -> dict | None:
    cutoff = datetime.now() - CACHE_TTL
    with Session(get_engine()) as session:
        row = session.exec(
            select(FetchCache)
            .where(
                FetchCache.url_normalized == url_normalized,
                FetchCache.http_status == 200,
                FetchCache.fetched_at >= cutoff,
            )
            .order_by(FetchCache.fetched_at.desc())
        ).first()
        return dict(row.raw_payload) if row and row.raw_payload else None


def record_fetch(url_normalized: str, http_status: int, site: str = "",
                  title: str = "", price_seen: int | None = None,
                  raw_payload: dict | None = None) -> None:
    with Session(get_engine()) as session:
        session.add(FetchCache(
            url_normalized=url_normalized, http_status=http_status, site=site,
            title=title, price_seen=price_seen, raw_payload=raw_payload,
        ))
        session.commit()
