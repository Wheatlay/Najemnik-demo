from datetime import date

from core.pipeline.enrich.callprep_bank import VIEWING_CHECKLIST, build_callprep
from core.models import Listing


def make_listing(**overrides) -> Listing:
    defaults = dict(url="https://example.com/1", title="2 pokoje")
    defaults.update(overrides)
    return Listing(**defaults)


def test_missing_fields_produce_their_questions():
    listing = make_listing(heating="", parking="", deposit="", notariusz="", prowizja="", pets_allowed=None)
    missing = " ".join(build_callprep(listing)["missing"])
    assert "ogrzewanie" in missing
    assert "parkingowe" in missing
    assert "kaucji" in missing
    assert "notariusz" in missing.lower() or "najem okazjonalny" in missing
    assert "prowizji" in missing
    assert "zwierzęta" in missing.lower()


def test_filled_fields_suppress_their_questions():
    listing = make_listing(
        heating="miejskie", parking={"status": "nie"},
        deposit={"status": "tak", "amount": 4500},
        notariusz={"status": "nie"}, prowizja={"status": "nie"},
        pets_allowed=True, available_from=None,
    )
    missing = " ".join(build_callprep(listing)["missing"])
    assert "kaucji" not in missing
    assert "prowizji" not in missing
    assert "zwierzęta" not in missing.lower()


def test_posrednik_question_appears_and_is_suppressed():
    # Otherwise-complete listing so posrednik isn't crowded out by the 8-cap.
    complete = dict(
        heating="miejskie", parking={"status": "nie"}, piwnica={"status": "nie"},
        deposit={"status": "tak", "amount": 4500}, notariusz={"status": "nie"},
        prowizja={"status": "nie"}, oc={"status": "nie"},
        pets_allowed=True, available_from=date(2026, 1, 1),
    )
    assert any("pośrednikiem" in q for q in build_callprep(make_listing(posrednik=None, **complete))["missing"])
    assert not any("pośrednikiem" in q for q in build_callprep(make_listing(posrednik=True, **complete))["missing"])


def test_always_group_holds_the_generic_questions():
    always = build_callprep(make_listing())["always"]
    assert any("wypowiedzenia" in q for q in always)
    assert any("protok" in q for q in always)


def test_missing_group_capped_at_eight():
    assert len(build_callprep(make_listing())["missing"]) <= 8  # everything missing


def test_viewing_checklist_is_static_and_nonempty():
    # Independent of listing data - same fixed list every time.
    assert build_callprep(make_listing())["viewing"] == VIEWING_CHECKLIST
    assert build_callprep(make_listing(pets_allowed=True, deposit="4500"))["viewing"] == VIEWING_CHECKLIST
    assert VIEWING_CHECKLIST
