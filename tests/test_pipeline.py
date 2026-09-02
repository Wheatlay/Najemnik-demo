from unittest.mock import patch

from sqlmodel import Session

from core.pipeline.enrich.ollama_client import OllamaUnavailable
from core.pipeline.enrich.pipeline import run_enrichment
from core.models import Listing


def _save(db, user_id, **overrides) -> str:
    defaults = dict(
        url="https://example.com/1", title="2 pokoje Koszutka", city="Katowice", district="Koszutka",
        rent_owner=2100, czynsz_admin=1045, deposit="4500",
        raw_text="2 pokoje Koszutka. Czynsz do właściciela 2100 zł, opłata administracyjna 1045 zł. "
                 "Ogrzewanie miejskie wliczone w czynsz. Kaucja 4500 zł.",
    )
    defaults.update(overrides)
    with Session(db.get_engine()) as session:
        listing = Listing(user_id=user_id, **defaults)
        session.add(listing)
        session.commit()
        session.refresh(listing)
        return listing.id


def _get(db, listing_id) -> Listing:
    with Session(db.get_engine()) as session:
        return session.get(Listing, listing_id)


def _always_yes_and_valid_extracts(prompt: str, timeout=None) -> dict:
    """Scripted responder: verify questions get "tak" (confirmed); extract/
    utility questions get a generic valid-but-empty answer so validation
    passes without asserting on exact field content."""
    if '"answer": "tak"}' in prompt and '{"answer": "nie"}' in prompt and "kwota" not in prompt:
        return {"answer": "tak"}
    if "status" in prompt and "kwota" in prompt and "w_czynszu" in prompt:
        return {"status": "brak_informacji"}
    if "status" in prompt and "kwota" in prompt:
        return {"status": "brak informacji"}
    if "wartosc" in prompt:
        return {"wartosc": None}
    if "answer" in prompt:
        return {"answer": "brak informacji"}
    return {}


def test_verify_yes_keeps_scraped_value(db, user):
    lid = _save(db, user.id)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=_always_yes_and_valid_extracts):
        assert run_enrichment(lid) is True

    listing = _get(db, lid)
    assert listing.rent_owner == 2100
    assert listing.czynsz_admin == 1045
    assert listing.deposit == "4500"
    assert listing.enriched_at is not None
    assert listing.cost_breakdown is not None


def test_verify_field_with_a_scraped_value_is_never_touched(db, user):
    """verify mode no longer cross-checks - it only fills a gap. A scraped
    value stands even when the ad text would support a different one, and
    (unlike extract mode) no model call is spent on it."""
    lid = _save(db, user.id, czynsz_admin=67354)

    asked = []

    def responder(prompt, timeout=None):
        asked.append(prompt)
        return _always_yes_and_valid_extracts(prompt, timeout)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        assert run_enrichment(lid) is True

    listing = _get(db, lid)
    assert listing.czynsz_admin == 67354
    # Match the question line, not the bare label: the label also appears in
    # every prompt's shared context, because the fixture's ad text mentions it.
    assert not any("jaka jest kwota (w zł) dla: opłata administracyjna" in p for p in asked)


def test_verify_field_is_filled_when_scraping_left_it_empty(db, user):
    lid = _save(db, user.id, czynsz_admin=None)

    def responder(prompt, timeout=None):
        if "opłata administracyjna" in prompt and "kwota" in prompt and "status" not in prompt:
            return {"kwota": 673}
        return _always_yes_and_valid_extracts(prompt, timeout)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        assert run_enrichment(lid) is True

    assert _get(db, lid).czynsz_admin == 673


def test_mid_run_ollama_unavailable_commits_partial_and_returns_false(db, user):
    lid = _save(db, user.id)

    calls = {"n": 0}

    def responder(prompt, timeout=None):
        calls["n"] += 1
        if calls["n"] > 2:
            raise OllamaUnavailable("offline")
        return _always_yes_and_valid_extracts(prompt, timeout)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        assert run_enrichment(lid) is False

    listing = _get(db, lid)
    assert listing.enriched_at is not None  # partial result still committed


def test_bad_model_output_treated_as_missing_and_pipeline_continues(db, user):
    from core.pipeline.enrich.ollama_client import BadModelOutput

    lid = _save(db, user.id)

    def responder(prompt, timeout=None):
        if "rodzaj ogrzewania" in prompt:  # only the heating field's own question, not the ad text
            raise BadModelOutput("garbage")
        return _always_yes_and_valid_extracts(prompt, timeout)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        assert run_enrichment(lid) is True

    listing = _get(db, lid)
    from core.domain.costs import MISSING_INFO
    assert listing.heating == MISSING_INFO


def test_no_raw_text_returns_false(db, user):
    lid = _save(db, user.id, raw_text="")
    assert run_enrichment(lid) is False


def test_concurrent_user_edit_survives_enrichment(db, user):
    """The slow AI run must not clobber an edit the user makes to a non-AI
    field (status, ratings, notes, ...) while it's in flight - the pipeline
    merges only its own fields back onto a freshly-reloaded row."""
    from core.models import Status

    lid = _save(db, user.id)

    edited = {"done": False}

    def responder(prompt, timeout=None):
        # Simulate the user setting a status + rating partway through the run,
        # committed from a separate session while the pipeline works on its
        # detached snapshot.
        if not edited["done"]:
            edited["done"] = True
            with Session(db.get_engine()) as s:
                row = s.get(Listing, lid)
                row.status = Status.POTENCJALNE
                row.ocena_wygladu = 5
                s.add(row)
                s.commit()
        return _always_yes_and_valid_extracts(prompt, timeout)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        assert run_enrichment(lid) is True

    listing = _get(db, lid)
    # User's concurrent edits preserved...
    assert listing.status == Status.POTENCJALNE
    assert listing.ocena_wygladu == 5
    # ...and the AI still wrote its own fields.
    assert listing.enriched_at is not None
    assert listing.cost_breakdown is not None


def test_validate_with_listing_receives_the_listing_through_the_pipeline(db, user):
    """posrednik's evidence-first validation needs raw_text to check the
    model's claimed quote - this confirms _run_extract_field actually
    threads the listing through to validate_with_listing, not just the raw
    answer dict (field_specs.py's spec.validate_with_listing hook)."""
    lid = _save(db, user.id, raw_text=(
        "2 pokoje Koszutka. Czynsz do właściciela 2100 zł, opłata administracyjna 1045 zł. "
        "Ogrzewanie miejskie wliczone w czynsz. Kaucja 4500 zł. "
        "Wynagrodzenie pośrednika: 100% czynszu."
    ))

    def responder(prompt, timeout=None):
        if "cytat" in prompt and "agencja" in prompt:
            return {"cytat": "Wynagrodzenie pośrednika: 100% czynszu.", "status": "agencja"}
        return _always_yes_and_valid_extracts(prompt, timeout)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        assert run_enrichment(lid) is True

    listing = _get(db, lid)
    assert listing.posrednik is True


def test_validate_with_listing_rejects_a_fabricated_quote_through_the_pipeline(db, user):
    lid = _save(db, user.id)  # default raw_text has no agency language at all

    def responder(prompt, timeout=None):
        if "cytat" in prompt and "agencja" in prompt:
            return {"cytat": "Biuro nieruchomości poleca tę ofertę.", "status": "agencja"}
        return _always_yes_and_valid_extracts(prompt, timeout)

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        assert run_enrichment(lid) is True

    listing = _get(db, lid)
    assert listing.posrednik is None
