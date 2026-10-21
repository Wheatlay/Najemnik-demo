"""Explicit unauthenticated allowlist besides routers/auth.py - anything
mounted here is reachable without a session. Keep this list short and
deliberate (SPEC §6: "router-level dependencies so no route can be added
unprotected by accident")."""
import json

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

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




def _preview_listings() -> list:
    """Two synthetic listings built straight from the fixture file (never
    added to a session), so the landing page can show the real comparison
    partial without a guest session or any database access."""
    from core.infra.config import BASE_DIR
    from core.models import Listing

    data = json.loads((BASE_DIR / "fixtures" / "demo_listings.json").read_text(encoding="utf-8"))
    listings = []
    for n, entry in enumerate(data[:3]):
        entry = dict(entry)
        entry.pop("photos_src", None)
        entry.pop("termin_ogledzin_in_days", None)
        listings.append(Listing(id=f"preview-{n}", user_id="preview", is_demo=True, **entry))
    return listings


@router.get("/")
def root(request: Request):
    """Demo: calm landing page (no guest session is created here - that
    happens on /start). Non-demo: unchanged redirect into the app."""
    if not DEMO_MODE:
        return RedirectResponse(url="/galeria")
    from core.domain.costs import CostContext
    from routers.pages import best_per_field

    market = _preview_listings()
    shown = market[:2]
    return render(request, "landing.html", {
        "listings": shown,
        "best": best_per_field(shown),
        "cost_ctx": CostContext(market),
        "standalone": True,
    })
