"""
CSRF middleware (SPEC §6). SameSite=Lax already blocks cross-site
navigation-triggered submissions; this covers the remaining gap (embedded
cross-site forms/fetches with credentials) for every mutating request made
by an *authenticated* session. Anonymous mutating requests (register,
login - there's no session yet to protect) are deliberately exempt.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.accounts.auth import get_session_by_token
from core.infra.config import SESSION_COOKIE_NAME
from core.infra.db import new_session

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_HEADER_NAME = "X-CSRF-Token"
# Plain (non-htmx) <form method="post"> submissions in base.html/konto.html
# can't carry the header. /wyloguj* are harmless to force cross-site since
# SameSite=Lax already excludes the session cookie from cross-site POSTs
# (a no-op unauthenticated request). /konto/* routes carry their own
# hidden-field csrf_token instead, checked by core.infra.deps.verify_csrf_form
# (a normal FastAPI dependency, not this middleware) - reading the body
# here to check a form field would consume the request stream before that
# dependency's own Form(...) parsing gets a chance to run.
# The auth entry points are plain forms and are exempt by design (see the
# module docstring): there is normally no session yet to protect. They have
# to be listed explicitly rather than relying on "no session cookie", because
# a user who *still holds a valid session* and submits the login or register
# form - a stale tab, or just navigating back to /logowanie - was otherwise
# treated as an authenticated mutating request and got a raw JSON 403.
# SameSite=Lax already strips the session cookie from genuine cross-site
# POSTs, so these arrive anonymous in an actual attack anyway.
_EXEMPT_PATHS = {"/wyloguj", "/wyloguj-wszedzie", "/logowanie", "/rejestracja"}
# /reset-hasla is a prefix, not an exact path: the confirm step posts to
# /reset-hasla/{token}, and someone resetting their password while still
# holding a live session (the usual case - you reset it *because* you're
# logged in somewhere) would otherwise hit the same 403.
# /api is the browser extension (SPEC §21 1.5c) - it authenticates solely
# via core.infra.deps.current_user_api reading an Authorization: Bearer
# header, which this middleware never even inspects (it only ever checks
# the session-cookie path below). CSRF exists to stop a browser from
# attaching credentials to a request the user didn't intend - a header the
# browser never attaches on its own isn't that credential, so there's
# nothing here for CSRF to protect against on this prefix.
_EXEMPT_PREFIXES = ("/konto", "/admin", "/reset-hasla", "/api")


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        exempt = path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)
        if request.method in _UNSAFE_METHODS and not exempt:
            token = request.cookies.get(SESSION_COOKIE_NAME)
            if token:
                with new_session() as session:
                    auth_session = get_session_by_token(session, token)
                if auth_session is not None:
                    # Header only, never a form field: every mutating
                    # request in this app goes through htmx (hx-headers set
                    # once on <body>, see base.html) - reading the body here
                    # to fall back to a form field would consume the
                    # request stream before the route's own Form(...)
                    # parameters get a chance to parse it.
                    supplied = request.headers.get(_HEADER_NAME)
                    if supplied != auth_session.csrf_token:
                        return JSONResponse({"error": "invalid or missing CSRF token"}, status_code=403)
        return await call_next(request)
