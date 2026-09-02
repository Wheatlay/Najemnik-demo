"""
Auth primitives (SPEC §6): password hashing, session tokens, signed
single-use tokens for email verify/reset, and the per-day counters backing
the quotas. Hand-rolled and minimal - no auth framework, no OAuth (Phase 2).
"""
import hashlib
import secrets
from datetime import date, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlmodel import Session, select

from core.infra.config import SECRET_KEY, SESSION_TTL_DAYS
from core.models import ApiToken, AuthSession, UsageCounter, User

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="najemnik-email-token")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        # Malformed/legacy hash - treat as a failed login rather than 500ing.
        return False


def _new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(session: Session, user: User, user_agent: str = "") -> tuple[str, AuthSession]:
    """Returns (raw_token_for_cookie, AuthSession_row). Only the row's
    token_hash is ever persisted - the raw token exists only long enough to
    set the cookie."""
    token = _new_token()
    row = AuthSession(
        token_hash=_token_hash(token),
        user_id=user.id,
        expires_at=datetime.now() + timedelta(days=SESSION_TTL_DAYS),
        user_agent=user_agent,
    )
    session.add(row)
    session.commit()
    return token, row


def get_session_by_token(session: Session, token: str) -> AuthSession | None:
    row = session.get(AuthSession, _token_hash(token))
    if row is None or row.expires_at < datetime.now():
        return None
    return row


def touch_session(session: Session, row: AuthSession) -> None:
    """Sliding expiry - called on every authenticated request."""
    row.expires_at = datetime.now() + timedelta(days=SESSION_TTL_DAYS)
    session.add(row)
    session.commit()


def delete_session(session: Session, token: str) -> None:
    row = session.get(AuthSession, _token_hash(token))
    if row:
        session.delete(row)
        session.commit()


def delete_all_sessions(session: Session, user_id: str) -> None:
    for row in session.exec(select(AuthSession).where(AuthSession.user_id == user_id)):
        session.delete(row)
    session.commit()


# --- API tokens (browser extension, SPEC §21 1.5c) ---

def create_api_token(session: Session, user: User, label: str = "", *, mark_used: bool = False) -> tuple[str, ApiToken]:
    """Returns (raw_token_shown_once, ApiToken_row) - same one-time-reveal
    shape as create_session's cookie value; only the hash is ever stored.

    mark_used=True is for the one-click pairing flow only: the injected
    script already proved it can reach this account (session cookie + CSRF
    from the page), so the round-trip that "extension actually works" is
    meant to certify has, in effect, already happened - a manually
    generated token from /ustawienia hasn't been pasted anywhere yet, so it
    stays unused until the extension really calls the API with it."""
    token = _new_token()
    row = ApiToken(token_hash=_token_hash(token), user_id=user.id, label=label)
    if mark_used:
        row.last_used_at = datetime.now()
    session.add(row)
    session.commit()
    return token, row


def get_user_by_api_token(session: Session, token: str) -> User | None:
    row = session.get(ApiToken, _token_hash(token))
    if row is None:
        return None
    row.last_used_at = datetime.now()
    session.add(row)
    session.commit()
    return session.get(User, row.user_id)


def delete_api_token(session: Session, user_id: str, token_hash: str) -> None:
    row = session.get(ApiToken, token_hash)
    if row and row.user_id == user_id:  # ownership check, not just existence
        session.delete(row)
        session.commit()


# How long a token can go unused before the UI stops calling it "working".
# There's no live handshake to catch "just updated and broke" - this is the
# cheap alternative: a token that hasn't proven itself recently stops being
# trusted, so a break eventually surfaces instead of showing a permanently
# green checkmark. The app's origin is a fixed zrok domain now (PLAN.md §9),
# so the real fix - a content script matched on our own origin, pinging the
# page on load (SPEC §21 1.5c follow-up) - is buildable; this just hasn't
# been swapped in yet.
EXTENSION_STALE_AFTER = timedelta(hours=48)


def extension_status(session: Session, user_id: str) -> tuple[str, datetime | None]:
    """("ok" | "stale" | "never", last_used_at) for this user's extension.

    "stale" is the state the plain last-used boolean couldn't express: a
    token that worked once but hasn't been seen in EXTENSION_STALE_AFTER -
    which is the "user is on the app, extension is silently broken" case
    this exists to catch."""
    last_used = extension_last_used(session, user_id)
    if last_used is None:
        return "never", None
    if datetime.now() - last_used > EXTENSION_STALE_AFTER:
        return "stale", last_used
    return "ok", last_used


def extension_last_used(session: Session, user_id: str) -> datetime | None:
    """When this user's browser extension last called the API - or paired
    successfully - or None if neither ever happened.

    A token that has actually round-tripped through the extension (pairing
    counts; see create_api_token's mark_used) is the only honest "the
    extension is installed and working" signal the server has - one merely
    generated on /ustawienia proves nothing until it's pasted somewhere.
    Every promotion of the extension in the UI keys off this, so it
    disappears for people who already have it rather than nagging them
    forever."""
    rows = session.exec(
        select(ApiToken.last_used_at).where(ApiToken.user_id == user_id)
    ).all()
    used = [ts for ts in rows if ts is not None]
    return max(used) if used else None


# --- Signed single-use tokens (email verify / password reset) ---

def make_email_token(user_id: str, purpose: str) -> str:
    return _serializer.dumps({"uid": user_id, "purpose": purpose})


def read_email_token(token: str, purpose: str, max_age_hours: int) -> str | None:
    """Returns the user_id if valid, else None (expired/tampered/wrong purpose)."""
    try:
        data = _serializer.loads(token, max_age=max_age_hours * 3600)
    except (BadSignature, SignatureExpired):
        return None
    if data.get("purpose") != purpose:
        return None
    return data.get("uid")


# --- Counters (login throttling + quotas, SPEC §12) ---

def bump_counter(session: Session, scope: str, key: str = "", day: date | None = None, amount: int = 1) -> int:
    """Increments today's counter for `scope` by `amount` and returns the new count."""
    day = day or date.today()
    row = session.exec(
        select(UsageCounter).where(
            UsageCounter.scope == scope, UsageCounter.key == key, UsageCounter.day == day
        )
    ).first()
    if row is None:
        row = UsageCounter(scope=scope, key=key, day=day, count=0)
    row.count += amount
    session.add(row)
    session.commit()
    return row.count


def get_counter(session: Session, scope: str, key: str = "", day: date | None = None) -> int:
    day = day or date.today()
    row = session.exec(
        select(UsageCounter).where(
            UsageCounter.scope == scope, UsageCounter.key == key, UsageCounter.day == day
        )
    ).first()
    return row.count if row else 0


# Login lockout was removed deliberately (2026-08-06). It counted failures
# per day rather than over the 15-minute window it advertised, so ten
# fumbled attempts locked an account until midnight - and with
# EMAIL_MODE=console the reset link lands in the founder's log, not the
# tester's inbox, making the founder the only way back in. Argon2 already
# makes each attempt cost real CPU, which is the actual brake on online
# guessing at beta scale. Reinstate a real sliding window before public
# launch, when password resets can be self-served.
