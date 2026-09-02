from sqlmodel import Session, select

from core.infra.llm_usage import record_usage
from core.models import Listing, LLMUsage


def test_record_usage_writes_a_row(db, user):
    with Session(db.get_engine()) as session:
        listing = Listing(user_id=user.id, url="https://example.com/1")
        session.add(listing)
        session.commit()
        session.refresh(listing)
        lid = listing.id

    record_usage(user.id, lid, model="ollama")

    with Session(db.get_engine()) as session:
        rows = session.exec(select(LLMUsage).where(LLMUsage.listing_id == lid)).all()
    assert len(rows) == 1
    assert rows[0].user_id == user.id
    assert rows[0].model == "ollama"


def test_record_usage_never_raises_on_db_failure(db, user, monkeypatch):
    def _boom():
        raise RuntimeError("db is down")
    monkeypatch.setattr("core.infra.llm_usage.get_engine", _boom)
    record_usage(user.id, None)  # must not raise
