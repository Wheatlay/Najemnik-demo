from core.domain import display
from core.domain.fields import FIELDS_BY_KEY
from core.models import Listing


def make_listing(**overrides) -> Listing:
    defaults = dict(url="https://example.com/1", title="Test")
    defaults.update(overrides)
    return Listing(**defaults)


def test_raw_value_available_from_null_is_empty_string_not_display_text():
    listing = make_listing(available_from=None)
    f = FIELDS_BY_KEY["available_from"]
    assert display.raw_value(listing, f) == ""


def test_raw_value_available_from_set_is_iso_date():
    from datetime import date
    listing = make_listing(available_from=date(2026, 8, 1))
    f = FIELDS_BY_KEY["available_from"]
    assert display.raw_value(listing, f) == "2026-08-01"


def test_display_value_available_from_null_shows_od_zaraz_after_enrichment():
    from datetime import datetime
    listing = make_listing(available_from=None, enriched_at=datetime(2026, 7, 1))
    f = FIELDS_BY_KEY["available_from"]
    assert display.display_value(listing, f) == "od zaraz"


def test_every_money_field_formats_its_amount_as_money():
    listing = make_listing(piwnica={"status": "tak", "amount": 200},
                           oc={"status": "tak", "amount": 150},
                           deposit={"status": "tak", "amount": 4500})
    for key, expected in (("piwnica", "200 zł"), ("oc", "150 zł"), ("deposit", "4 500 zł")):
        assert display.display_value(listing, FIELDS_BY_KEY[key]) == expected


def test_money_field_without_an_amount_renders_its_polish_label():
    """The wording users already know, now generated at render time instead
    of being what's stored."""
    listing = make_listing(parking={"status": "nie"})
    assert display.display_value(listing, FIELDS_BY_KEY["parking"]) == "brak miejsca parkingowego"
    listing = make_listing(prowizja={"status": "tak", "note": "50% czynszu"})
    assert display.display_value(listing, FIELDS_BY_KEY["prowizja"]) == "wymagana, 50% czynszu"


def test_display_value_available_from_null_before_enrichment_shows_dash():
    listing = make_listing(available_from=None, enriched_at=None)
    f = FIELDS_BY_KEY["available_from"]
    assert display.display_value(listing, f) == "—"


def test_raw_value_phone_null_is_empty_string_not_literal_none():
    listing = make_listing(phone=None)
    f = FIELDS_BY_KEY["phone"]
    assert display.raw_value(listing, f) == ""


def test_select_bool_display_value_uses_custom_labels():
    f = FIELDS_BY_KEY["posrednik"]
    assert display.display_value(make_listing(posrednik=True), f) == "pośrednik"
    assert display.display_value(make_listing(posrednik=False), f) == "prywatnie"
    assert display.display_value(make_listing(posrednik=None), f) == "—"


def test_select_bool_raw_value_generic_for_any_field():
    # posrednik (unlike pewnosc_lokalizacji) is a genuinely nullable
    # select_bool - "brak informacji" is a real, reachable third state.
    f = FIELDS_BY_KEY["posrednik"]
    assert display.raw_value(make_listing(posrednik=True), f) == "tak"
    assert display.raw_value(make_listing(posrednik=False), f) == "nie"
    assert display.raw_value(make_listing(posrednik=None), f) == ""


def test_pewnosc_lokalizacji_defaults_to_false():
    listing = make_listing()
    assert listing.pewnosc_lokalizacji is False


def test_pewnosc_lokalizacji_is_not_nullable():
    """No "brak informacji" third state - it's a plain confirmed/not-yet-
    confirmed flag the user sets themselves, unlike the AI-filled tri-state
    fields (posrednik, pets_allowed)."""
    f = FIELDS_BY_KEY["pewnosc_lokalizacji"]
    assert f.nullable is False
