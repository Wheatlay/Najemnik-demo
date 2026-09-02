"""
Per-field AI enrichment pipeline - replaces the old single monolithic-prompt
approach (core/pipeline/enrich/prompts/enrich.py, deleted) with one short question per
field. Each field is either:

- verify-mode (scraping usually already filled it): fill the field only if
  scraping left it empty, otherwise leave the scraped value entirely alone.
  This mode used to also cross-check the scraped value against the ad text,
  but its sole output was a mismatch note on the now-removed "Uwagi (AI)"
  field, so the check was dropped with it (see field_specs.py).
- extract-mode (AI-only fields): a single strict-schema extraction call.

Every raw model answer is validated by its FieldSpec's schema
(core/pipeline/enrich/field_specs.py) before being stored - invalid/garbage output
becomes the canonical MISSING_INFO marker (or None for nullable fields),
never raw model text.
"""
from collections.abc import Callable
from datetime import datetime
from typing import Optional

from sqlmodel import Session

from core.domain.breakdown import LABELS_PL_NOM, UTILITIES, fees_note_from_breakdown, validate_breakdown
from core.infra.db import get_engine
from core.pipeline.enrich.field_specs import (
    grounded_quote,
    FIELD_SPECS,
    UtilityStatus,
    build_extract_prompt,
    build_utility_prompt,
)
from core.pipeline.enrich.llm import LLMBadOutput as BadModelOutput
from core.pipeline.enrich.llm import LLMUnavailable as OllamaUnavailable
from core.pipeline.enrich.llm import generate_json, run_with_enrichment_queue
from core.models import Listing
from core.domain.normalize import normalize_title_case

ProgressFn = Optional[Callable[[str, int, int], None]]

def _call(listing: Listing, prompt: str, timeout: int) -> dict | None:
    """Returns the parsed answer dict, or None if the model produced
    unusable output (BadModelOutput) - the field is then treated as missing
    and the pipeline continues. OllamaUnavailable propagates - the server
    itself being down means every subsequent call will fail too."""
    try:
        result = generate_json(prompt, timeout=timeout)
    except BadModelOutput:
        result = None
    from core.infra.llm_usage import record_usage
    record_usage(listing.user_id, listing.id)
    return result


def _run_verify_field(listing: Listing, spec, timeout: int, authored: dict) -> None:
    """Runs one ai_verify field. Fills the field only when scraping left it
    empty; a scraped value that the ad text contradicts is left alone.

    Gap-filling counts as AI authorship and is recorded as such - a kaucja
    reading "wymagana, kwota nie podana" was written by the model, not the
    portal, and has to be badged that way."""
    if getattr(listing, spec.key):
        return
    value, quote = _run_extract_field(listing, spec, timeout)
    if value is not None:
        setattr(listing, spec.key, value)
        authored[spec.key] = quote


def _run_extract_field(listing, spec, timeout: int):
    """Runs one extract call and validates it. Returns
    (canonical value, grounded quote or None).

    The value may be MISSING_INFO / None per schema semantics. Fields whose
    validation needs the listing itself (grounding a claimed quote against
    raw_text - see field_specs.py's evidence-first prompts) set
    validate_with_listing instead of relying on the plain schema.

    The quote is returned rather than recorded here so the caller can tie it
    to whether the value was actually stored: a quote for a value we threw
    away would be a receipt for nothing."""
    answer = _call(listing, build_extract_prompt(listing, spec), timeout)
    quote = grounded_quote(answer or {}, listing)
    if spec.validate_with_listing is not None:
        return spec.validate_with_listing(answer or {}, listing), quote
    return spec.schema.validate(answer or {}), quote


def _run_utility(listing, utility: str, timeout: int) -> dict:
    answer = _call(listing, build_utility_prompt(listing, utility, LABELS_PL_NOM[utility]), timeout)
    return UtilityStatus().validate(answer or {})


# Fields the pipeline is allowed to write, merged back onto a freshly-loaded
# row at the end of a run (see run_enrichment). enriched_at and ai_evidence
# are handled separately.
_AI_WRITABLE_FIELDS = [s.key for s in FIELD_SPECS] + ["cost_breakdown", "fees_note"]


def run_enrichment(listing_id: str, progress: ProgressFn = None) -> bool:
    """Runs the full per-field pipeline for one listing, holding the single
    global enrichment queue slot for its duration (SPEC §8: one local GPU
    serves one enrichment run at a time). If another run is already using
    it, reports "w kolejce…" through `progress` once, then waits."""
    def _on_queued():
        if progress:
            progress("w kolejce…", 0, 1)

    return run_with_enrichment_queue(lambda: _run_enrichment(listing_id, progress), on_queued=_on_queued)


def _run_enrichment(listing_id: str, progress: ProgressFn = None) -> bool:
    """Runs the full per-field pipeline for one listing. Returns True if it
    completed (even if some individual fields came back as "no info"),
    False if Ollama itself was unreachable. Partial progress is committed
    even when aborted partway through, since earlier fields were already
    validated and are safe to keep.

    The ~18 sequential Ollama calls can take many minutes, during which the
    user is typically still editing this very listing in the drawer. So the
    slow work runs against a *detached* snapshot with no DB session held, and
    only the AI-owned fields (_AI_WRITABLE_FIELDS) are merged back onto a
    freshly-reloaded row at the very end - any edits the user made to other
    fields meanwhile survive instead of being clobbered by a stale commit."""
    from core.infra.config import OLLAMA_FIELD_TIMEOUT

    engine = get_engine()
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if not listing or not (listing.raw_text or "").strip():
            return False
        # Detach: keep working on this object in memory, but hold no session
        # or transaction open across the slow model calls below.
        session.expunge(listing)

    total_steps = len(FIELD_SPECS) + len(UTILITIES)
    step = 0
    # {field_key: quote or None} for every field this run actually wrote.
    # Presence is the authorship claim; the value is the receipt, if any.
    authored: dict[str, str | None] = {}
    completed = True

    try:
        for spec in FIELD_SPECS:
            step += 1
            if progress:
                progress(f"AI ({step}/{total_steps}): {spec.label_pl}", step, total_steps)

            current = getattr(listing, spec.key)
            # `current not in (None, "")` rather than plain truthiness:
            # posrednik is Optional[bool], and False ("prywatnie") is a
            # legitimate answered state that a truthiness check would
            # wrongly treat as "still empty" and re-extract forever.
            if spec.only_if_empty and current not in (None, ""):
                continue

            if spec.mode == "verify":
                _run_verify_field(listing, spec, OLLAMA_FIELD_TIMEOUT, authored)
            else:
                value, quote = _run_extract_field(listing, spec, OLLAMA_FIELD_TIMEOUT)
                if value is None:
                    continue
                if spec.key == "district" and value:
                    value = normalize_title_case(value)
                setattr(listing, spec.key, value)
                authored[spec.key] = quote

        utilities = {}
        for u in UTILITIES:
            step += 1
            if progress:
                progress(f"AI ({step}/{total_steps}): koszt - {LABELS_PL_NOM[u]}", step, total_steps)
            utilities[u] = _run_utility(listing, u, OLLAMA_FIELD_TIMEOUT)

        breakdown = validate_breakdown(
            {"utilities": utilities}, czynsz_admin=listing.czynsz_admin, rent_owner=listing.rent_owner,
            heating=listing.heating,
        )
        listing.cost_breakdown = breakdown
        from core.domain.settings import get_settings
        s = get_settings(listing.user_id)
        listing.fees_note = fees_note_from_breakdown(
            breakdown, heating=listing.heating,
            utility_costs={
                "woda": s.woda_cost, "ogrzewanie": s.ogrzewanie_cost, "smieci": s.smieci_cost,
                "prad": s.prad_cost, "gaz": s.gaz_cost, "internet": s.internet_cost,
            },
            heating_costs={
                "gazowe": s.heating_gazowe_cost, "elektryczne": s.heating_elektryczne_cost,
                "kominkowe": s.heating_kominkowe_cost, "inne": s.heating_inne_cost,
            },
        )

    except OllamaUnavailable:
        completed = False

    # Merge only the AI-owned fields back onto a fresh row, so concurrent
    # user edits to everything else (status, ratings, rank, notes, ...) are
    # preserved. Committed on both success and mid-run abort - partial fields
    # were already validated and are safe to keep.
    with Session(engine) as session:
        fresh = session.get(Listing, listing_id)
        if fresh is None:
            return completed
        # A field the user has edited by hand is theirs - re-enrichment must
        # not quietly take it back, and its receipt stays dropped.
        for key in _AI_WRITABLE_FIELDS:
            if key in fresh.edited_fields:
                continue
            setattr(fresh, key, getattr(listing, key))
        fresh.ai_evidence = {
            **{k: v for k, v in fresh.ai_evidence.items() if k not in authored},
            **{k: v for k, v in authored.items() if k not in fresh.edited_fields},
        }
        fresh.enriched_at = datetime.now()
        session.add(fresh)
        session.commit()
    return completed
