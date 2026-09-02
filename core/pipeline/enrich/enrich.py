from sqlmodel import Session

from core.infra.db import get_engine
from core.pipeline.enrich.llm import LLMBadOutput as BadModelOutput
from core.pipeline.enrich.llm import LLMUnavailable as OllamaUnavailable
from core.pipeline.enrich.llm import generate_json
from core.pipeline.enrich.ollama_client import is_online
from core.pipeline.enrich.pipeline import ProgressFn, run_enrichment
from core.pipeline.enrich.prompts import comparative, tags
from core.domain.fields import TAG_VOCABULARY
from core.models import Listing


def _get(session: Session, listing_id: str) -> Listing | None:
    return session.get(Listing, listing_id)


def enrich_listing(listing_id: str, progress: ProgressFn = None) -> bool:
    """Runs the per-field verify/extract pipeline (core/pipeline/enrich/pipeline.py)
    for one listing. Returns False (no-op) if Ollama is unreachable, or if
    the owning user is over their daily enrichment quota (SPEC §12) - never
    raises, never blocks ingestion."""
    from core.accounts.auth import bump_counter, get_counter
    from core.infra.config import QUOTA_ENRICH_PER_DAY
    from core.infra.db import new_session

    with new_session() as session:
        listing = _get(session, listing_id)
        if not listing:
            return False
        if get_counter(session, "enrich", listing.user_id) >= QUOTA_ENRICH_PER_DAY:
            return False
        bump_counter(session, "enrich", listing.user_id)
        user_id = listing.user_id

    ok = run_enrichment(listing_id, progress=progress)
    if ok:
        from core.infra.events import record_event
        record_event(user_id, "enrich", listing_id=listing_id)
    return ok


def suggest_tags(listing_id: str) -> list[str] | None:
    """Asks one strict yes/no question per TAG_VOCABULARY entry (see
    core/pipeline/enrich/prompts/tags.py) and returns the ones confirmed. Not
    auto-applied - the caller (an on-demand endpoint, or a re-enrich job)
    decides whether to save them; ingest no longer calls this at all, since
    running it there means a hallucinated tag could land in the database
    with no one looking. Returns None if Ollama is offline. A single bad/
    unparseable answer is treated as "nie" for that one tag rather than
    aborting the rest."""
    engine = get_engine()
    with Session(engine) as session:
        listing = _get(session, listing_id)
        if not listing:
            return None
        confirmed = []
        for tag in TAG_VOCABULARY:
            try:
                result = generate_json(tags.build_prompt(listing, tag))
            except OllamaUnavailable:
                return None
            except BadModelOutput:
                continue
            if result.get("answer") == "tak":
                confirmed.append(tag)
        return confirmed


def comparative_analysis(listing_ids: list[str]) -> dict[str, dict] | None:
    """SPEC §9.5: comparative pros/cons across the given (filtered) set.
    Writes `ai_comment` on each listing and returns the raw per-id result."""
    engine = get_engine()
    with Session(engine) as session:
        listings = [l for l in (_get(session, lid) for lid in listing_ids) if l]
        if not listings:
            return {}
        try:
            result = generate_json(comparative.build_prompt(listings))
        except OllamaUnavailable:
            return None
        for listing in listings:
            entry = result.get(listing.id)
            if entry:
                parts = [entry.get("porownanie", "")]
                parts += [f"+ {p}" for p in entry.get("plusy", [])]
                parts += [f"- {m}" for m in entry.get("minusy", [])]
                listing.ai_comment = "\n".join(p for p in parts if p)
                session.add(listing)
        session.commit()
        return result


def ai_health() -> bool:
    return is_online()
