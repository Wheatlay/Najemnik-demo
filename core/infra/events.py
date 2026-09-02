"""Product event recording (SPEC §15). Best-effort: a logging failure must
never break the action that triggered it."""
import logging

from sqlmodel import Session

from core.infra.db import get_engine
from core.models import ProductEvent

logger = logging.getLogger("najemnik.events")

# The deliberately small set SPEC §15 calls out - steering, not vanity.
EVENTS = {"registered", "first_import", "import", "enrich", "viewing_scheduled", "export"}


def record_event(user_id: str | None, event: str, **props) -> None:
    if event not in EVENTS:
        raise ValueError(f"unknown product event {event!r} - add it to core.infra.events.EVENTS first")
    try:
        with Session(get_engine()) as session:
            session.add(ProductEvent(user_id=user_id, event=event, props=props))
            session.commit()
    except Exception:
        logger.exception("failed to record product event %s", event)
