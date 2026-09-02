"""Hosted portfolio mode: automatic guests, isolation and safe controls."""

import re

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from core.models import Listing, User


def _enable_demo(monkeypatch):
    """Patch import-time flags for the shared test app.

    The deployment smoke test imports the application with DEMO_MODE=true;
    this unit test uses the already-imported normal-mode app, so all modules
    holding the immutable config value need the equivalent patch.
    """
    from core.infra import demo_session, templating
    from routers import pages

    monkeypatch.setattr(demo_session, "DEMO_MODE", True)
    monkeypatch.setattr(templating, "DEMO_MODE", True)
    monkeypatch.setitem(templating.templates.env.globals, "DEMO_MODE", True)
    monkeypatch.setattr(pages, "DEMO_MODE", True)


def _csrf(html: str) -> str:
    match = re.search(r'X-CSRF-Token&quot;: &quot;([^&]+)&quot;', html)
    if not match:
        match = re.search(r'X-CSRF-Token": "([^"]+)"', html)
    assert match, "demo page did not expose its CSRF header token"
    return match.group(1)


def test_demo_creates_signed_isolated_guest_sessions(db, monkeypatch):
    _enable_demo(monkeypatch)
    from main import app

    with TestClient(app) as browser_a, TestClient(app) as browser_b:
        page_a = browser_a.get("/galeria")
        page_b = browser_b.get("/galeria")

        assert page_a.status_code == page_b.status_code == 200
        assert "syntetyczne" in page_a.text.lower()
        cookie_a = browser_a.cookies.get("najemnik_session")
        cookie_b = browser_b.cookies.get("najemnik_session")
        assert cookie_a and cookie_b and cookie_a != cookie_b
        # itsdangerous serialized cookies have a payload/signature boundary;
        # the raw random session token stored only server-side does not.
        assert "." in cookie_a

        with Session(db.get_engine()) as session:
            guest_ids = session.exec(select(User.id).where(User.email.endswith("@demo.invalid"))).all()
            assert len(guest_ids) == 2
            counts = {
                guest_id: len(session.exec(select(Listing).where(Listing.user_id == guest_id)).all())
                for guest_id in guest_ids
            }
        assert set(counts.values()) == {3}


def test_demo_reset_is_scoped_and_production_integrations_are_disabled(db, monkeypatch):
    _enable_demo(monkeypatch)
    from main import app

    with TestClient(app) as browser_a, TestClient(app) as browser_b:
        page_a = browser_a.get("/galeria")
        browser_b.get("/galeria")

        from core.accounts.auth import get_session_by_token
        from core.infra import demo_session

        raw_a = demo_session._cookie_signer.loads(browser_a.cookies.get("najemnik_session"))
        with Session(db.get_engine()) as session:
            guest_ids = session.exec(select(User.id).where(User.email.endswith("@demo.invalid"))).all()
            browser_a_user_id = get_session_by_token(session, raw_a).user_id
            listing_a = session.exec(select(Listing).where(Listing.user_id == browser_a_user_id)).first()
            original_title = listing_a.title
            listing_a.title = "Edited only in browser A"
            session.add(listing_a)
            session.commit()

        browser_a.headers["X-CSRF-Token"] = _csrf(page_a.text)
        reset = browser_a.post("/demo/reset", follow_redirects=False)
        assert reset.status_code == 303

        with Session(db.get_engine()) as session:
            titles_a = session.exec(select(Listing.title).where(Listing.user_id == browser_a_user_id)).all()
            other_user_id = next(guest_id for guest_id in guest_ids if guest_id != browser_a_user_id)
            titles_b = session.exec(select(Listing.title).where(Listing.user_id == other_user_id)).all()
        assert original_title in titles_a
        assert "Edited only in browser A" not in titles_a
        assert len(titles_b) == 3

        for path in ("/ingest", "/ai/reenrich", "/import", "/compare/analyze"):
            response = browser_a.post(path)
            assert response.status_code == 403
            assert response.json()["detail"] == "demo_mode_disabled"


def test_portfolio_health_contract(anon_client):
    response = anon_client.get("/healthz")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "demo", "version"}
    assert response.json()["status"] == "ok"
