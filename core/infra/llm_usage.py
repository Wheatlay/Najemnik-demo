"""Per-call LLM usage logging (SPEC §8) - feeds the M6 admin metrics page
(cost monitoring) and, later, a per-user enrichment quota. Best-effort:
failing to log a usage row must never break enrichment itself."""
import logging

from sqlmodel import Session

from core.infra.db import get_engine
from core.models import LLMUsage

logger = logging.getLogger("najemnik.llm_usage")


def record_usage(user_id: str | None, listing_id: str | None, model: str = "ollama") -> None:
    try:
        with Session(get_engine()) as session:
            session.add(LLMUsage(user_id=user_id, listing_id=listing_id, model=model))
            session.commit()
    except Exception:
        logger.exception("failed to record llm_usage row")
