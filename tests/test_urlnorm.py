import pytest

from core.pipeline.scrape.urlnorm import normalize_url


@pytest.mark.parametrize("raw,expected", [
    (
        "https://www.otodom.pl/pl/oferta/mieszkanie-ID4abcd?utm_source=fb&utm_medium=social",
        "https://otodom.pl/pl/oferta/mieszkanie-ID4abcd",
    ),
    (
        "https://www.olx.pl/d/oferta/mieszkanie-CID3-ID123.html?fbclid=xyz",
        "https://olx.pl/d/oferta/mieszkanie-CID3-ID123.html",
    ),
    (
        "https://OTODOM.PL/pl/oferta/x/",  # trailing slash, uppercase host
        "https://otodom.pl/pl/oferta/x",
    ),
    (
        "https://example.com/listing?utm_campaign=x&keep=yes",
        "https://example.com/listing?keep=yes",
    ),
])
def test_normalize_url_table(raw, expected):
    assert normalize_url(raw) == expected


def test_normalize_url_is_idempotent():
    url = "https://www.otodom.pl/pl/oferta/x?utm_source=fb"
    assert normalize_url(normalize_url(url)) == normalize_url(url)
