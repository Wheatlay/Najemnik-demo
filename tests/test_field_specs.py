from core.domain.costs import MISSING_INFO
from core.pipeline.enrich import field_specs as fs
from core.models import Listing


def make_listing(**overrides) -> Listing:
    defaults = dict(
        url="https://example.com/1", title="2 pokoje Koszutka", city="Katowice", district="Koszutka",
        rent_owner=2100, czynsz_admin=1045, raw_text="2 pokoje, ogrzewanie miejskie wliczone w czynsz.",
    )
    defaults.update(overrides)
    return Listing(**defaults)


# --- schema validators -------------------------------------------------

def test_int_pln_valid_and_out_of_range():
    schema = fs.IntPLN(min_value=1, max_value=5000)
    assert schema.validate({"kwota": 1045}) == 1045
    assert schema.validate({"kwota": 999999}) is None
    assert schema.validate({"kwota": None}) is None
    assert schema.validate({}) is None
    assert schema.validate("garbage") is None


def test_tristate_money_keeps_the_models_structure():
    """The model already answers {status, kwota}; this used to flatten it
    into a Polish sentence that every consumer parsed back."""
    schema = fs.TriStateMoney("prowizja")
    assert schema.validate({"status": "tak", "kwota": 800}) == {"status": "tak", "amount": 800}
    assert schema.validate({"status": "tak", "kwota": None}) == {"status": "tak"}
    assert schema.validate({"status": "nie"}) == {"status": "nie"}
    for bad in ({"status": "brak informacji"}, {"status": "garbage"}, {}, "garbage"):
        assert schema.validate(bad) == {"status": "brak_informacji"}


def test_tristate_money_applies_its_own_fields_clamp():
    """The clamps live in money_field, so the AI path and a hand-typed edit
    are held to the same range - piwnica tops out far below prowizja."""
    assert fs.TriStateMoney("prowizja").validate({"status": "tak", "kwota": 900})["amount"] == 900
    assert "amount" not in fs.TriStateMoney("piwnica").validate({"status": "tak", "kwota": 900})


def test_tristate_bool():
    schema = fs.TriStateBool()
    assert schema.validate({"answer": "tak"}) is True
    assert schema.validate({"answer": "nie"}) is False
    assert schema.validate({"answer": "brak informacji"}) is None
    assert schema.validate({}) is None
    assert schema.validate("garbage") is None


def test_enum_pl_rejects_unknown_value():
    schema = fs.EnumPL(values=("miejskie", "gazowe", MISSING_INFO))
    assert schema.validate({"wartosc": "miejskie"}) == "miejskie"
    assert schema.validate({"wartosc": "coś dziwnego"}) == MISSING_INFO
    assert schema.validate({}) == MISSING_INFO


def test_short_text_trims_and_rejects_empty():
    schema = fs.ShortText(max_len=10)
    assert schema.validate({"wartosc": "  Koszutka  "}) == "Koszutka"
    assert schema.validate({"wartosc": ""}) is None
    assert schema.validate({"wartosc": None}) is None
    assert schema.validate({}) is None


def test_short_text_rejects_junk_literals():
    """qwen2.5 returned the bare word "Null" for district on one benchmark
    listing, which then passed the "non-empty string" check and got stored
    as a real district name."""
    schema = fs.ShortText()
    assert schema.validate({"wartosc": "Null"}) is None
    assert schema.validate({"wartosc": "brak informacji"}) is None
    assert schema.validate({"wartosc": "  BRAK  "}) is None
    assert schema.validate({"wartosc": "Koszutka"}) == "Koszutka"


def test_agency_status_covers_all_three_states():
    schema = fs.AgencyStatus()
    assert schema.validate({"status": "agencja"}) is True
    assert schema.validate({"status": "prywatnie"}) is False
    assert schema.validate({"status": "brak informacji"}) is None
    assert schema.validate({}) is None
    assert schema.validate("garbage") is None


def test_date_pl_parses_iso_date():
    from datetime import date
    schema = fs.DatePL()
    assert schema.validate({"data": "2026-08-01"}) == date(2026, 8, 1)


def test_date_pl_rejects_garbage_and_null():
    schema = fs.DatePL()
    assert schema.validate({"data": None}) is None
    assert schema.validate({"data": "od zaraz"}) is None  # not ISO - model should've returned null instead
    assert schema.validate({}) is None
    assert schema.validate("garbage") is None


def test_available_from_prompt_includes_reference_date():
    """A bare month name ("od lipca") is ambiguous without an anchor date -
    the model hallucinated a wrong (past) year for it until this was added."""
    from datetime import datetime
    listing = make_listing(available_from=None)
    listing.created_at = datetime(2026, 7, 2)
    spec = fs.FIELD_SPECS_BY_KEY["available_from"]
    prompt = fs.build_extract_prompt(listing, spec)
    assert "2026-07-02" in prompt


def test_utility_status_clamps_bad_amount():
    schema = fs.UtilityStatus()
    assert schema.validate({"status": "osobno", "kwota": 200}) == {"status": "osobno", "amount": 200}
    assert schema.validate({"status": "osobno", "kwota": 999999}) == {"status": "osobno_bez_kwoty"}
    assert schema.validate({"status": "nonsense"}) == {"status": "brak_informacji"}
    assert schema.validate({}) == {"status": "brak_informacji"}


# --- prompt no-leak guarantee -------------------------------------------

def test_extract_prompt_never_leaks_current_value():
    """The extract prompt fired after a "nie" answer must not mention the
    old (rejected) value anywhere - otherwise the model could just parrot
    it back instead of genuinely re-reading the ad text."""
    listing = make_listing(czynsz_admin=1045)
    spec = fs.FIELD_SPECS_BY_KEY["czynsz_admin"]
    prompt = fs.build_extract_prompt(listing, spec)
    assert "1045" not in prompt


def test_every_extract_mode_schema_has_a_prompt_builder():
    listing = make_listing()
    for spec in fs.FIELD_SPECS:
        if spec.mode == "extract":
            prompt = fs.build_extract_prompt(listing, spec)
            assert prompt


def test_custom_prompt_specs_still_include_raw_text():
    """Fields with a custom_prompt (posrednik, parking, prowizja, district)
    must not accidentally drop build_context()'s raw_text inclusion."""
    listing = make_listing(raw_text="UNIKALNY-FRAGMENT-OGLOSZENIA-XYZ")
    for key in ("posrednik", "parking", "prowizja", "district"):
        spec = fs.FIELD_SPECS_BY_KEY[key]
        assert spec.custom_prompt is not None
        assert "UNIKALNY-FRAGMENT-OGLOSZENIA-XYZ" in fs.build_extract_prompt(listing, spec)


def test_posrednik_prompt_asks_for_a_quote():
    listing = make_listing()
    spec = fs.FIELD_SPECS_BY_KEY["posrednik"]
    prompt = fs.build_extract_prompt(listing, spec)
    assert "cytat" in prompt


# --- evidence-first grounding (posrednik, parking) ----------------------


def test_validate_posrednik_accepts_a_grounded_quote():
    listing = make_listing(raw_text="Ogłoszenie. Wynagrodzenie pośrednika: 100% czynszu. Koniec.")
    raw = {"cytat": "Wynagrodzenie pośrednika: 100% czynszu.", "status": "agencja"}
    assert fs.validate_posrednik(raw, listing) is True


def test_validate_posrednik_rejects_a_fabricated_quote():
    """The model claiming a status but citing text that isn't actually in
    the ad must not be trusted - falls back to "brak informacji" (None)."""
    listing = make_listing(raw_text="2 pokoje, ogrzewanie miejskie wliczone w czynsz.")
    raw = {"cytat": "Biuro nieruchomości poleca tę ofertę.", "status": "agencja"}
    assert fs.validate_posrednik(raw, listing) is None


def test_validate_posrednik_tolerates_trailing_ellipsis_and_punctuation_spacing():
    """Two real benchmark false-negatives: the model appending "..." to a
    quote, and a spacing mismatch ("biura ." in the ad vs "biura." in the
    quote) - both must still match after normalization."""
    listing = make_listing(raw_text="Kontakt. Wymagana prowizja dla biura . Dziękujemy.")
    raw = {"cytat": "Wymagana prowizja dla biura...", "status": "agencja"}
    assert fs.validate_posrednik(raw, listing) is True


def test_validate_posrednik_rejects_missing_or_null_quote():
    listing = make_listing()
    assert fs.validate_posrednik({"cytat": None, "status": "agencja"}, listing) is None
    assert fs.validate_posrednik({"status": "brak informacji"}, listing) is None
    assert fs.validate_posrednik("garbage", listing) is None


def test_validate_parking_policy_treats_communal_parking_as_absent():
    """User-ruled policy: unassigned/street/communal parking counts as no
    dedicated spot, not "brak informacji" and not "tak"."""
    listing = make_listing(raw_text="Mieszkanie. Parkowanie na ulicy przed blokiem. Koniec.")
    raw = {"cytat": "Parkowanie na ulicy przed blokiem.", "status": "nie"}
    assert fs.validate_parking(raw, listing) == {"status": "nie"}


def test_validate_parking_accepts_grounded_dedicated_spot_with_amount():
    listing = make_listing(raw_text="Mieszkanie. Miejsce w garażu podziemnym: 200 zł. Koniec.")
    raw = {"cytat": "Miejsce w garażu podziemnym: 200 zł.", "status": "tak", "kwota": 200}
    assert fs.validate_parking(raw, listing) == {"status": "tak", "amount": 200}


def test_validate_parking_rejects_ungrounded_claim_as_missing_not_absent():
    """An ungrounded "nie" must fall back to "brak informacji" (unknown),
    not silently become a confident "no parking" claim."""
    listing = make_listing(raw_text="2 pokoje, ogrzewanie miejskie wliczone w czynsz.")
    raw = {"cytat": "Brak miejsca parkingowego przy budynku.", "status": "nie"}
    assert fs.validate_parking(raw, listing) == {"status": "brak_informacji"}
