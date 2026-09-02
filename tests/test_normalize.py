from datetime import date

from core.domain import normalize as n


def test_to_int_plain():
    assert n.to_int("2100") == 2100


def test_to_int_thousands_space():
    assert n.to_int("2 100 zł") == 2100


def test_to_int_range_midpoint():
    assert n.to_int("150-250") == 200


def test_to_int_comma_decimal():
    assert n.to_int("1500,50") == 1500  # round-half-to-even
    assert n.to_int("1500,60") == 1501


def test_to_int_thousands_dot():
    # Ads routinely write "1.500 zł" for one thousand five hundred - a naive
    # "comma is decimal" parser misreads this as 1.5.
    assert n.to_int("1.500 zł") == 1500
    assert n.to_int("4.500") == 4500


def test_to_int_thousands_comma():
    assert n.to_int("1,500") == 1500


def test_to_int_thousands_dot_decimal_comma():
    assert n.to_int("1.234,50") == 1234


def test_to_int_none():
    assert n.to_int(None) is None
    assert n.to_int("") is None
    assert n.to_int("brak informacji") is None


def test_to_float_area():
    assert n.to_float("52") == 52.0
    assert n.to_float("52,5") == 52.5
    assert n.to_float(52.34, 1) == 52.3


def test_normalize_phone():
    assert n.normalize_phone("+48 123 456 789") == "123456789"
    assert n.normalize_phone("48123456789") == "123456789"
    assert n.normalize_phone("123-456-789") == "123456789"
    assert n.normalize_phone(None) is None
    assert n.normalize_phone("") is None


def test_format_phone():
    assert n.format_phone("123456789") == "123 456 789"
    assert n.format_phone(None) == "—"


def test_normalize_floor_ground():
    assert n.normalize_floor("parter") == 0
    assert n.normalize_floor("ground") == 0
    assert n.normalize_floor("0") == 0
    assert n.normalize_floor(0) == 0


def test_normalize_floor_number():
    assert n.normalize_floor("3") == 3
    assert n.normalize_floor("floor_3") == 3
    assert n.normalize_floor(None) is None


def test_format_floor():
    assert n.format_floor(0, 5) == "parter/5"
    assert n.format_floor(2, 5) == "2/5"
    assert n.format_floor(2, None) == "2"
    assert n.format_floor(None, None) == "—"


def test_normalize_rooms():
    assert n.normalize_rooms("kawalerka") == 1
    assert n.normalize_rooms("studio") == 1
    assert n.normalize_rooms("3 pokoje") == 3
    assert n.normalize_rooms(2) == 2


def test_format_rooms():
    assert n.format_rooms(1) == "1 pokój"
    assert n.format_rooms(2) == "2 pokoje"
    assert n.format_rooms(None) == "—"


def test_format_area():
    assert n.format_area(52.0) == "52.0 m²"
    assert n.format_area(None) == "—"


def test_format_money():
    assert n.format_money(2100) == "2 100 zł"
    assert n.format_money(0) == "0 zł"
    assert n.format_money(None) == "—"


def test_normalize_available_from():
    assert n.normalize_available_from("od zaraz") is None
    assert n.normalize_available_from(None) is None
    assert n.normalize_available_from("2026-08-01") == date(2026, 8, 1)
    assert n.normalize_available_from("01.08.2026") == date(2026, 8, 1)


def test_format_available_from():
    assert n.format_available_from(None) == "od zaraz"
    assert n.format_available_from(date(2026, 8, 1)) == "2026-08-01"


def test_normalize_ocena_clamped():
    assert n.normalize_ocena("7") == 5
    assert n.normalize_ocena("0") == 1
    assert n.normalize_ocena("3") == 3
    assert n.normalize_ocena(None) is None
