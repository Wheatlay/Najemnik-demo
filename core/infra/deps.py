"""
current_user dependency (SPEC §6) - applied router-level on every router
that touches per-user data, so a route can only be unauthenticated by
being registered on the explicit public allowlist (routers/public.py,
routers/auth.py). Also the shared get_owned_listing() helper every listing
route uses instead of a bare session.get(Listing, id), so "not mine" and
"doesn't exist" are indistinguishable (404, never 200/403) from the
outside - see SPEC §17 isolation suite.
"""
from fastapi import Form, Request
from starlette.exceptions import HTTPException
from sqlmodel import Session

from core.accounts.auth import get_session_by_token, get_user_by_api_token, touch_session
from core.infra.config import SESSION_COOKIE_NAME
from core.infra.db import new_session
from core.models import Listing, User


class RedirectToLogin(Exception):
    """Raised by current_user for page routes so a 303 can be returned
    instead of FastAPI's default 401 JSON body."""


def _load_user(request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    with new_session() as session:
        auth_session = get_session_by_token(session, token)
        if auth_session is None:
            return None
        user = session.get(User, auth_session.user_id)
        if user is None or user.deleted_at is not None:
            return None
        touch_session(session, auth_session)  # commits, which expires `user` too
        session.refresh(user)
        session.expunge(user)
        request.state.csrf_token = auth_session.csrf_token
        return user


def current_user(request: Request) -> User:
    """Page routes: redirect to /logowanie. API/htmx routes: 401 JSON.
    Distinguished by the presence of the HX-Request header or an
    Accept: application/json - htmx fragment endpoints and the JSON API
    both want a body they can react to, not a full-page redirect."""
    user = _load_user(request)
    if user is None:
        is_api_like = request.headers.get("HX-Request") == "true" \
            or "application/json" in request.headers.get("accept", "")
        if is_api_like:
            raise HTTPException(status_code=401, detail="not authenticated")
        raise RedirectToLogin()
    request.state.user = user
    return user


def current_user_optional(request: Request) -> User | None:
    """For routes that render differently when logged in vs anonymous
    (currently unused in Phase 1's page set, kept for the landing-page
    router in a later phase)."""
    return _load_user(request)


def current_user_api(request: Request) -> User:
    """Auth for /api/* (the browser extension, SPEC §21 1.5c) - reads
    Authorization: Bearer <token> ONLY, never the session cookie. That's
    deliberate, not an oversight: a cross-origin request from the extension
    can't carry the session cookie anyway (SameSite=Lax), and keeping cookie
    auth out of this path entirely is what makes CSRFMiddleware's /api
    exemption safe - CSRF defends against a browser attaching credentials
    the user didn't mean to send, which a header the browser never attaches
    on its own can't be tricked into doing.

    Always 401 JSON, never RedirectToLogin - there's no browser navigation
    to redirect."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth_header.removeprefix("Bearer ").strip()
    with new_session() as session:
        user = get_user_by_api_token(session, token)
        if user is None or user.deleted_at is not None:
            raise HTTPException(status_code=401, detail="invalid token")
        session.expunge(user)
    return user


def verify_csrf_form(request: Request, csrf_token: str = Form(...)) -> None:
    """CSRF check for plain (non-htmx) <form> POSTs, e.g. templates/konto.html
    - CSRFMiddleware exempts these paths and defers to this dependency
    instead, since checking a form field in the middleware would consume
    the request body before FastAPI's own Form(...) parsing gets to it."""
    expected = getattr(request.state, "csrf_token", None)
    if not expected or csrf_token != expected:
        raise HTTPException(status_code=403, detail="invalid or missing CSRF token")


def get_owned_listing(session: Session, user_id: str, listing_id: str) -> Listing | None:
    listing = session.get(Listing, listing_id)
    if listing is None or listing.user_id != user_id:
        return None
    return listing
