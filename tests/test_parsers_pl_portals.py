"""Parser coverage for the Polish rental portals beyond Otodom/OLX.

Fixtures in tests/fixtures_html/ are entirely synthetic, minimal reproductions
of the markup contracts the parsers read.  They deliberately contain reserved
domains and invalid phone numbers so parser coverage can be published without
redistributing listing content or contact data.

These are the sites the app claims to support, so a portal changing its markup
should fail here rather than quietly importing an empty listing - which is how
the OLX hydration bug reached production.
"""
import pathlib

import pytest

from core.pipeline.scrape import generic, morizon
from core.pipeline.scrape.dispatch import parser_for

FIXTURES = pathlib.Path(__file__).parent / "fixtures_html"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("url,expected", [
    ("https://www.otodom.pl/pl/oferta/x", "otodom"),
    ("https://www.olx.pl/d/oferta/x.html", "olx"),
    ("https://www.morizon.pl/oferta/x", "morizon"),
    ("https://gratka.pl/nieruchomosci/x/ob/1", "morizon"),
    # No module of their own: generic reads their schema.org markup in full.
    ("https://www.domiporta.pl/nieruchomosci/x/1", "generic"),
    ("https://warszawa.nieruchomosci-online.pl/mieszkanie,x/1.html", "generic"),
])
def test_each_supported_portal_routes_to_a_parser(url, expected):
    assert parser_for(url).__module__.rsplit(".", 1)[-1] == expected


def test_morizon_reads_the_embedded_property_blob():
    url = "https://www.morizon.pl/oferta/syntetyczna-oferta-demo"
    raw = morizon.parse(_html("morizon_rental.html"), url)

    assert raw["site"] == "morizon"
    assert raw["rent_owner"] == 3100
    assert raw["area_m2"] == 42
    assert raw["rooms"] == "2"
    assert raw["floor"] == "3"
    assert raw["address"] == "Demo 1"
    assert raw["city"] == "Katowice"
    assert raw["district"] == "Śródmieście"
    assert raw["posrednik"] is False  # "osoba prywatna"
    assert raw["phone"]


def test_gratka_uses_the_same_parser_and_flags_an_agency():
    url = "https://gratka.pl/nieruchomosci/syntetyczna-oferta/ob/demo"
    raw = morizon.parse(_html("gratka_rental.html"), url)

    assert raw["site"] == "gratka"  # same platform, different brand
    assert raw["rent_owner"] == 2600
    assert raw["area_m2"] == 37
    assert raw["city"] == "Katowice"
    assert raw["posrednik"] is True  # "agencja nieruchomości"
    # The payload repeats a district that equals its sub-district; the parser
    # collapses that rather than storing "Bronowice Bronowice".
    assert raw["district"] == "Ligota"


def test_morizon_gallery_excludes_other_listings_photos():
    """A listing page carries thumbnails for recommended listings too, in the
    same URL shape. Only photos sharing the cover's id prefix are this
    listing's."""
    url = "https://www.morizon.pl/oferta/syntetyczna-oferta-demo"
    raw = morizon.parse(_html("morizon_rental.html"), url)

    photos = raw["image_urls"]
    assert len(photos) > 1
    # The fixture deliberately includes unrelated thumbs; a parser that took
    # them all would return far more than the listing actually has.
    assert len(photos) < 40
    assert all(p.startswith("https://img") for p in photos)


def test_domiporta_reads_the_apartment_nested_in_itemoffered():
    """RealEstateListing keeps address/offers outside and geo/floorSize on the
    Apartment in itemOffered. Reading only the wrapper lost half the listing."""
    url = "https://www.domiporta.pl/nieruchomosci/syntetyczna-oferta-demo"
    raw = generic.parse(_html("domiporta_rental.html"), url)

    assert raw["site"] == "domiporta"
    assert raw["rent_owner"] == "3200"
    assert raw["city"] == "Katowice"
    assert float(raw["area_m2"]) == 50        # from itemOffered
    assert raw["floor"] == "2"                # from itemOffered
    assert float(raw["lat"]) == pytest.approx(50.2501)   # from itemOffered
    assert len(raw["image_urls"]) > 1


def test_nieruchomosci_online_parses_from_plain_ldjson():
    url = "https://katowice.nieruchomosci-online.pl/mieszkanie,demo/1.html"
    raw = generic.parse(_html("nieruchomosci_online_rental.html"), url)

    assert raw["site"] == "nieruchomosci-online"
    assert raw["rent_owner"] == "2800"
    assert raw["city"] == "Katowice"
    assert raw["rooms"] == "3"
    assert float(raw["area_m2"]) == 64.0
    assert float(raw["lat"]) == pytest.approx(50.2602)


@pytest.mark.parametrize("url,expected", [
    ("https://warszawa.nieruchomosci-online.pl/mieszkanie,x/1.html", "nieruchomosci-online"),
    ("https://www.domiporta.pl/nieruchomosci/x/1", "domiporta"),
    ("https://www.example.com.pl/oferta/1", "example"),   # steps past .com.pl
    ("https://adresowo.pl/x", "adresowo"),
])
def test_site_label_is_the_registrable_name(url, expected):
    """It used to be nieruchomosci-online-or-"other", which put every other
    portal under one meaningless label in the UI and in FetchCache."""
    assert generic.site_label(url) == expected
