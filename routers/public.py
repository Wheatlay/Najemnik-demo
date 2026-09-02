"""Explicit unauthenticated allowlist besides routers/auth.py - anything
mounted here is reachable without a session. Keep this list short and
deliberate (SPEC §6: "router-level dependencies so no route can be added
unprotected by accident")."""
from fastapi import APIRouter, Request

from core.infra.config import APP_VERSION, DEMO_MODE
from core.infra.templating import render

router = APIRouter()

@router.get("/zdrowie")
def health():
    from sqlmodel import text

    from core.infra.db import new_session
    try:
        with new_session() as session:
            session.exec(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.get("/healthz")
def portfolio_health():
    """Stable, public health contract consumed by the portfolio site."""
    from sqlmodel import text

    from core.infra.db import new_session
    try:
        with new_session() as session:
            session.exec(text("SELECT 1"))
        return {"status": "ok", "demo": DEMO_MODE, "version": APP_VERSION}
    except Exception:
        return {"status": "error", "demo": DEMO_MODE, "version": APP_VERSION}


@router.get("/pomoc")
def pomoc(request: Request):
    """FAQ. Public on purpose: half the questions ("is my data private?",
    "do you scrape portals?") are ones people want answered *before* they
    sign up, and the page contains nothing account-specific."""
    return render(request, "pomoc.html", {"view": "pomoc"})


