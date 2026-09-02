"""Disposable guest sessions for the public portfolio showcase."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.accounts.auth import create_session, get_session_by_token
from core.infra.config import COOKIE_SECURE, DEMO_MODE, SECRET_KEY, SESSION_COOKIE_NAME
from core.infra.db import new_session
from core.models import Settings, User
from core.pipeline.demo import load_demo_listings


_BLOCKED_PREFIXES = (
    "/admin",
    "/api",
    "/ai",
    "/compare/analyze",
    "/duplicates",
    "/import",
    "/ingest",
    "/konto",
    "/logowanie",
    "/ping",
    "/rejestracja",
    "/reset-hasla",
    "/rozszerzenie",
    "/udostepnij",
    "/ustawienia",
    "/weryfikacja",
    "/wyloguj",
)
_PASSTHROUGH_PREFIXES = ("/static", "/healthz", "/zdrowie")
_cookie_signer = URLSafeSerializer(SECRET_KEY, salt="najemnik-portfolio-demo-session")


def _is_blocked(path: str) -> bool:
    if any(path.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
        return True
    return path.startswith("/listings/") and (
        path.endswith("/reenrich") or path.endswith("/tags/suggest")
    )


def _validated_raw_token(signed_token: str | None) -> str | None:
    """Verify the browser cookie, then validate its opaque server session."""
    if not signed_token:
        return None
    try:
        token = _cookie_signer.loads(signed_token)
    except BadSignature:
        return None
    if not isinstance(token, str):
        return None
    with new_session() as session:
        row = get_session_by_token(session, token)
        if row is None:
            return None
        user = session.get(User, row.user_id)
        if user is None or user.deleted_at is not None or not user.email.endswith("@demo.invalid"):
            return None
        return token


def _new_demo_session(user_agent: str) -> str:
    with new_session() as session:
        user = User(
            email=f"guest-{uuid.uuid4()}@demo.invalid",
            password_hash="demo-login-disabled",
            display_name="Guest demo",
            email_verified_at=datetime.now(),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(Settings(user_id=user.id))
        session.commit()
        token, row = create_session(session, user, user_agent=user_agent[:500])
        row.expires_at = datetime.now() + timedelta(hours=24)
        session.add(row)
        session.commit()
        load_demo_listings(session, user.id)
        return token


def _inject_cookie(request, token: str) -> None:
    """Make a newly-created or decoded cookie visible to dependencies."""
    raw_headers = [(key, value) for key, value in request.scope["headers"] if key.lower() != b"cookie"]
    existing = request.headers.get("cookie", "")
    cookie_value = f"{existing}; {SESSION_COOKIE_NAME}={token}" if existing else f"{SESSION_COOKIE_NAME}={token}"
    raw_headers.append((b"cookie", cookie_value.encode("latin-1")))
    request.scope["headers"] = raw_headers
    if hasattr(request, "_cookies"):
        delattr(request, "_cookies")


class DemoSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not DEMO_MODE:
            return await call_next(request)

        path = request.url.path
        if _is_blocked(path):
            return JSONResponse(
                {"detail": "demo_mode_disabled", "feature": path},
                status_code=403,
            )

        created_token = None
        if not any(path.startswith(prefix) for prefix in _PASSTHROUGH_PREFIXES):
            signed_token = request.cookies.get(SESSION_COOKIE_NAME)
            token = _validated_raw_token(signed_token)
            if token is None:
                created_token = _new_demo_session(request.headers.get("user-agent", ""))
                token = created_token
            _inject_cookie(request, token)

        response = await call_next(request)
        if created_token:
            response.set_cookie(
                SESSION_COOKIE_NAME,
                _cookie_signer.dumps(created_token),
                httponly=True,
                secure=COOKIE_SECURE,
                samesite="lax",
                max_age=24 * 60 * 60,
            )
        return response
