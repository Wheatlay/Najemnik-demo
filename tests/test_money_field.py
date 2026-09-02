"""The six money fields' value semantics: what survives validation, what
each read means, and that rendering still produces the Polish the user (and
the benchmark's gold set) already knows."""
import pytest

from core.domain import money_field as mf


# --- validate: collapse to a weaker claim, never store the unchecked -------

def test_validate_keeps_a_plausible_amount():
    assert mf.validate("deposit", {"status": "tak", "amount": 4200}) == {
        "status": "tak", "amount": 4200}


def test_validate_accepts_a_numeric_string_amount():
    """The edit form posts strings; the AI posts ints. Both land here."""
    assert mf.validate("deposit", {"status": "tak", "amount": "4200"})["amount"] == 4200


def test_validate_drops_an_implausible_amount_but_keeps_the_status():
    """"There is a deposit" survives "...of 900000 zł" being nonsense - the
    claim and the number are separately trustworthy."""
    out = mf.validate("deposit", {"status": "tak", "amount": 900000})
    assert out == {"status": "tak"}


def test_validate_clamps_are_per_field():
    # 900 zł is a fine parking space and an impossible piwnica (max 500).
    assert mf.validate("parking", {"status": "tak", "amount": 900})["amount"] == 900
    assert "amount" not in mf.validate("piwnica", {"status": "tak", "amount": 900})


def test_validate_drops_an_amount_that_contradicts_the_status():
    assert mf.validate("prowizja", {"status": "nie", "amount": 500}) == {"status": "nie"}


def test_validate_downgrades_an_unknown_status():
    assert mf.validate("oc", {"status": "moze"}) == {"status": "brak_informacji"}
    assert mf.validate("oc", {}) == {"status": "brak_informacji"}


def test_validate_keeps_a_note_and_trims_it():
    assert mf.validate("prowizja", {"status": "tak", "note": "  50% czynszu "}) == {
        "status": "tak", "note": "50% czynszu"}


def test_validate_ignores_an_empty_note():
    assert mf.validate("prowizja", {"status": "tak", "note": "   "}) == {"status": "tak"}


def test_validate_rejects_a_non_dict():
    assert mf.validate("deposit", None) is None
    assert mf.validate("deposit", "4200") is None


# --- reads -----------------------------------------------------------------

def test_amount_reads_only_a_real_amount():
    assert mf.amount({"status": "tak", "amount": 4200}) == 4200
    assert mf.amount({"status": "tak"}) is None
    assert mf.amount(None) is None


def test_presence_is_tri_state():
    assert mf.presence({"status": "tak"}) is True
    assert mf.presence({"status": "nie"}) is False
    assert mf.presence({"status": "brak_informacji"}) is None
    assert mf.presence(None) is None


def test_a_confirmed_no_is_information_not_a_gap():
    """The distinction the old startswith("brak") check kept fumbling:
    "brak" (prowizja confirmed absent) is an answer; "brak informacji" is
    the absence of one."""
    assert mf.is_missing({"status": "nie"}) is False
    assert mf.is_missing({"status": "brak_informacji"}) is True
    assert mf.is_missing(None) is True


def test_bucket_colours_the_three_cases():
    assert mf.bucket({"status": "tak", "amount": 200}) == "pay"
    assert mf.bucket({"status": "tak"}) == "pay"
    assert mf.bucket({"status": "nie"}) == "free"
    assert mf.bucket({"status": "brak_informacji"}) == "unknown"
    assert mf.bucket(None) == "unknown"


# --- rendering: the user-visible wording must not have changed -------------

@pytest.mark.parametrize("key,expected", [
    ("deposit", "wymagana, kwota nie podana"),  # kaucja is feminine
    ("parking", "dostępne, kwota nie podana"),
    ("piwnica", "dostępna, kwota nie podana"),
    ("notariusz", "wymagany (najem okazjonalny), kwota nie podana"),
    ("prowizja", "wymagana, kwota nie podana"),
    ("oc", "wymagane, kwota nie podana"),
])
def test_present_labels_match_the_strings_these_fields_used_to_store(key, expected):
    """Pinned verbatim: the tour step titled „Dostępna, kwota nie podana",
    templates/pomoc.html and the benchmark gold set all quote these."""
    assert mf.present_label(key) == expected


def test_display_formats_an_amount_as_money():
    assert mf.display_string("deposit", {"status": "tak", "amount": 4200}) == "4 200 zł"


def test_display_uses_a_note_in_place_of_the_missing_amount():
    """"wymagana, 50% czynszu" - a note usually IS the amount said another
    way, so it replaces the "kwota nie podana" tail rather than trailing it."""
    assert mf.display_string("prowizja", {"status": "tak", "note": "50% czynszu"}) == \
        "wymagana, 50% czynszu"


def test_display_parenthesises_a_note_beside_a_real_amount():
    assert mf.display_string("deposit", {"status": "tak", "amount": 4200, "note": "przy umowie"}) == \
        "4 200 zł (przy umowie)"


def test_display_renders_absence_with_its_own_label():
    assert mf.display_string("parking", {"status": "nie"}) == "brak miejsca parkingowego"
    assert mf.display_string("prowizja", {"status": "nie", "note": "od właściciela"}) == \
        "brak (od właściciela)"


def test_display_falls_back_to_missing_info():
    assert mf.display_string("oc", {"status": "brak_informacji"}) == "brak informacji"
    assert mf.display_string("oc", None) == "brak informacji"


# --- benchmark boundary ----------------------------------------------------

def test_benchmark_string_reproduces_the_legacy_storage_format():
    """gold.csv was recorded when these were text columns. Serialising back
    to exactly that keeps 118 gold rows and score.py valid with no re-run."""
    assert mf.benchmark_string("deposit", {"status": "tak", "amount": 4200}) == "4200"
    assert mf.benchmark_string("piwnica", {"status": "tak"}) == "dostępna, kwota nie podana"
    assert mf.benchmark_string("parking", {"status": "nie"}) == "brak miejsca parkingowego"
    assert mf.benchmark_string("oc", {"status": "brak_informacji"}) == "brak informacji"


def test_benchmark_string_drops_notes():
    """Notes postdate the gold set, so there's nothing to compare them to."""
    assert mf.benchmark_string("prowizja", {"status": "tak", "note": "50% czynszu"}) == \
        "wymagana, kwota nie podana"


# --- registry agreement ----------------------------------------------------

def test_every_money_field_has_labels_and_clamps():
    """A field added to MONEY_FIELDS without both would render a KeyError at
    the user rather than failing here."""
    for key in mf.MONEY_FIELDS:
        assert key in mf.LABELS, key
        assert key in mf.CLAMPS, key


# --- the amount box must not be a lenient text parser ---------------------

@pytest.mark.parametrize("typed", ["abc", "50% czynszu", "-5", "12e5", "4200 albo 4500", "dużo"])
def test_text_in_the_amount_box_never_becomes_a_number(typed):
    """This shipped broken: the amount ran through normalize.to_int, which is
    a "find the first number in this text" parser meant for scraped ad copy.
    "50% czynszu" became 50 zł and joined the entry-cost total silently."""
    out = mf.validate("prowizja", {"status": "tak", "amount": typed})
    assert "amount" not in out, f"{typed!r} was read as {out.get('amount')}"


@pytest.mark.parametrize("typed,expected", [
    ("4200", 4200), (4200, 4200), ("4 200", 4200), ("4.200", 4200),
    ("4200 zł", 4200), ("  4200  ", 4200),
])
def test_real_amounts_still_parse(typed, expected):
    assert mf.validate("deposit", {"status": "tak", "amount": typed})["amount"] == expected


def test_to_amount_matches_the_internal_parser():
    assert mf.to_amount("4200") == 4200
    assert mf.to_amount("50% czynszu") is None
