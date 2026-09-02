import json

from core.pipeline.scrape import generic, olx, otodom
from core.pipeline.scrape.dispatch import parser_for


def test_parser_for_dispatches_by_host():
    assert parser_for("https://www.otodom.pl/pl/oferta/x-ID123") is otodom.parse
    assert parser_for("https://www.olx.pl/d/oferta/x.html") is olx.parse
    assert parser_for("https://katowice.nieruchomosci-online.pl/x.html") is generic.parse
    assert parser_for("https://example-agency.pl/oferta/1") is generic.parse


def test_generic_parser_ldjson():
    html = """
    <html><head>
    <meta property="og:title" content="Ładne mieszkanie na wynajem">
    <script type="application/ld+json">
    {"@type": "Apartment", "address": {"streetAddress": "ul. Testowa 5", "addressLocality": "Katowice"},
     "geo": {"latitude": 50.26, "longitude": 19.02},
     "offers": {"price": 2500}, "floorSize": {"value": 48}, "numberOfRooms": 2,
     "image": ["https://cdn.example.com/1.jpg"]}
    </script>
    </head><body>Opis mieszkania, kontakt 123 456 789.</body></html>
    """
    raw = generic.parse(html, "https://example-agency.pl/oferta/1")
    assert raw["title"] == "Ładne mieszkanie na wynajem"
    assert raw["address"] == "ul. Testowa 5"
    assert raw["city"] == "Katowice"
    assert raw["rent_owner"] == 2500
    assert raw["area_m2"] == 48
    assert raw["rooms"] == "2"
    assert raw["image_urls"] == ["https://cdn.example.com/1.jpg"]


def test_otodom_parser_next_data():
    next_data = {
        "props": {"pageProps": {"ad": {
            "title": "2 pokoje Koszutka",
            "characteristics": [
                {"key": "price", "value": "2100"},
                {"key": "rent", "value": "1045"},
                {"key": "m", "value": "52"},
                {"key": "rooms_num", "value": "2"},
                {"key": "floor_no", "value": "floor_1"},
            ],
            "location": {
                "coordinates": {"latitude": 50.27, "longitude": 19.01},
                "address": {"street": {"name": "Placu Grunwaldzkiego", "number": "8"}},
                "reverseGeocoding": {"locations": [
                    {"locationLevel": "city_or_village", "name": "Katowice"},
                    {"locationLevel": "district", "name": "Koszutka"},
                ]},
            },
            "contactDetails": {"phones": ["+48123456789"]},
            "images": [{"large": "https://img.example.com/a.jpg"}],
            "description": "<p>Świetne mieszkanie</p>",
        }}}
    }
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
    raw = otodom.parse(html, "https://www.otodom.pl/pl/oferta/x-ID1")
    assert raw["title"] == "2 pokoje Koszutka"
    assert raw["rent_owner"] == "2100"
    assert raw["czynsz_admin"] == "1045"
    assert raw["area_m2"] == "52"
    assert raw["city"] == "Katowice"
    assert raw["district"] == "Koszutka"
    assert raw["phone"] == "+48123456789"
    assert raw["image_urls"] == ["https://img.example.com/a.jpg"]


def test_olx_parser_prerendered_state():
    state = {"ad": {"ad": {
        "title": "Mieszkanie 3 pokoje",
        "price": {"regularPrice": {"value": 2000}},
        "params": [{"key": "m", "value": "60"}, {"key": "rooms", "value": "3"}],
        "location": {"cityName": "Katowice", "districtName": "Koszutka"},
        "map": {"lat": 50.25, "lon": 19.0},
        "photos": ["https://img.olx.pl/1.jpg"],
        "description": "Opis oferty",
    }}}
    encoded = json.dumps(json.dumps(state))
    html = f"<script>window.__PRERENDERED_STATE__= {encoded};</script>"
    raw = olx.parse(html, "https://www.olx.pl/d/oferta/x.html")
    assert raw["title"] == "Mieszkanie 3 pokoje"
    assert raw["rent_owner"] == 2000
    assert raw["area_m2"] == "60"
    assert raw["city"] == "Katowice"
    assert "phone hidden" in raw["notes"]
    assert "posrednik" not in raw  # no isBusiness key in this fixture - AI still asks


# --- advertiser-type capture at ingestion (Phase 5 production port) -----
# Otodom's advertiserType and OLX's isBusiness are confirmed against real
# listing pages (see git history / research/benchmark/REPORT.md's ingestion section)
# - "business"/True = agency, "private"/False = direct owner. Setting
# posrednik here means core/pipeline/enrich/field_specs.py's only_if_empty posrednik
# call is skipped entirely for portal-badged listings.


def test_otodom_parser_sets_posrednik_true_for_business_advertiser():
    next_data = {"props": {"pageProps": {"ad": {
        "title": "Mieszkanie", "characteristics": [], "location": {},
        "advertiserType": "business", "description": "",
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
    raw = otodom.parse(html, "https://www.otodom.pl/pl/oferta/x-ID2")
    assert raw["posrednik"] is True


def test_otodom_parser_sets_posrednik_false_for_private_advertiser():
    next_data = {"props": {"pageProps": {"ad": {
        "title": "Mieszkanie", "characteristics": [], "location": {},
        "advertiserType": "private", "description": "",
    }}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
    raw = otodom.parse(html, "https://www.otodom.pl/pl/oferta/x-ID3")
    assert raw["posrednik"] is False


def test_olx_parser_sets_posrednik_from_is_business():
    for is_business, expected in [(True, True), (False, False)]:
        state = {"ad": {"ad": {
            "title": "Mieszkanie", "params": [], "location": {}, "map": {},
            "description": "", "isBusiness": is_business,
        }}}
        encoded = json.dumps(json.dumps(state))
        html = f"<script>window.__PRERENDERED_STATE__= {encoded};</script>"
        raw = olx.parse(html, "https://www.olx.pl/d/oferta/x.html")
        assert raw["posrednik"] is expected
