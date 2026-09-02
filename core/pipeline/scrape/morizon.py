"""Morizon and Gratka - one parser, because they are one platform.

Both belong to Grupa Morizon-Gratka (Ringier Axel Springer) and are served by
the same Nuxt app: identical markup, identical embedded payload, different
skin. Registering both domains against this module is the whole difference.

Where the data lives: Nuxt 3 serializes its payload into
<script id="__NUXT_DATA__"> as devalue's flat array, where objects reference
each other by index - awkward to walk. But the listing itself is embedded in
that array as one self-contained JSON *string*, so it can be lifted out whole
without reimplementing devalue. The ld+json Offer alongside it carries the
description, the seller's phone and the cover image.
"""
import base64
import json
import re

from bs4 import BeautifulSoup

# The blob sits inside a JSON string, so its quotes arrive escaped (\"). The
# plain form is accepted too - cheap insurance if either site ever inlines it
# directly.
_PROPERTY_RE_ESCAPED = re.compile(r'\{\\"property\\":.*?\}\}')
_PROPERTY_RE_PLAIN = re.compile(r'\{"property":.*?\}\}')

# Photo CDN. Both sites serve /thumb/<base64 of the real URL>/<preset>/<name>,
# and the decoded path ends in <listing-photo-id>_<photo-id>.jpg.
_THUMB_RE = re.compile(r'https://img\d*\.static(?:morizon|gratka)\.com\.pl/thumb/([A-Za-z0-9+/=]+)/[^"\\\s]*')


def _property_blob(html: str) -> dict:
    m = _PROPERTY_RE_ESCAPED.search(html)
    raw = None
    if m:
        # unicode_escape also resolves the \uXXXX that Polish characters
        # arrive as inside the serialized string.
        raw = m.group(0).encode().decode("unicode_escape")
    else:
        m = _PROPERTY_RE_PLAIN.search(html)
        if m:
            raw = m.group(0)
    if not raw:
        return {}
    try:
        return json.loads(raw).get("property") or {}
    except json.JSONDecodeError:
        return {}


def _decoded(thumb_b64: str) -> str:
    try:
        return base64.b64decode(thumb_b64 + "===").decode("utf-8", "replace")
    except Exception:
        return ""


def _gallery(html: str, cover_url: str) -> list[str]:
    """Every photo belonging to *this* listing, in page order.

    A listing page also carries thumbnails for recommended listings - dozens
    of them - and they are indistinguishable by URL shape. What separates
    them is the id prefix inside the decoded CDN path, which the cover photo
    supplies: same prefix, same listing.
    """
    prefix = ""
    cover_m = _THUMB_RE.search(cover_url or "")
    if cover_m:
        name = _decoded(cover_m.group(1)).rsplit("/", 1)[-1]
        prefix = name.split("_", 1)[0]
    if not prefix:
        return [cover_url] if cover_url else []

    out: list[str] = []
    for m in _THUMB_RE.finditer(html):
        name = _decoded(m.group(1)).rsplit("/", 1)[-1]
        if name.split("_", 1)[0] == prefix and m.group(0) not in out:
            out.append(m.group(0))
    return out or ([cover_url] if cover_url else [])


def _split_location(location: str, province: str) -> tuple[str, str]:
    """'dolnośląskie Wrocław Fabryczna' -> ('Wrocław', 'Fabryczna').

    One flat string is all the payload gives. The province is known
    separately so it can be stripped exactly; after that the first token is
    taken as the city. That mis-splits the handful of two-word city names
    ("Nowy Sącz" -> city "Nowy"), which is visible and editable in the
    drawer - unlike silently dropping the district, which is the alternative.
    """
    parts = (location or "").split()
    if province and parts and parts[0].lower() == province.lower():
        parts = parts[1:]
    if not parts:
        return "", ""
    city = parts[0]
    # The payload repeats the district when it equals the sub-district
    # ("Bronowice Bronowice"); collapse consecutive duplicates.
    rest, seen = [], None
    for p in parts[1:]:
        if p != seen:
            rest.append(p)
        seen = p
    return city, " ".join(rest)


def parse(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    prop = _property_blob(html)
    raw: dict = {"site": "gratka" if "gratka.pl" in url else "morizon"}

    offer = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for o in obj if isinstance(obj, list) else [obj]:
            if isinstance(o, dict) and o.get("@type") == "Offer":
                offer = o
                break

    title_tag = soup.find("meta", property="og:title")
    raw["title"] = offer.get("name") or (title_tag.get("content") if title_tag else "") or ""

    if prop.get("price"):
        raw["rent_owner"] = prop["price"]
    if prop.get("living_area") or prop.get("residence_area"):
        raw["area_m2"] = prop.get("living_area") or prop.get("residence_area")
    if prop.get("number_of_rooms"):
        raw["rooms"] = str(prop["number_of_rooms"])
    if prop.get("floor") is not None:
        raw["floor"] = str(prop["floor"])
    if prop.get("street"):
        raw["address"] = prop["street"]

    city, district = _split_location(prop.get("location", ""), prop.get("province", ""))
    raw["city"] = city
    raw["district"] = district

    # "osoba prywatna" vs "agencja nieruchomości" - the one field on these
    # sites that answers the question the app actually asks about a listing.
    owner = (prop.get("owner") or "").lower()
    if owner:
        raw["posrednik"] = "agencja" in owner or "biuro" in owner

    seller = offer.get("seller") or {}
    if isinstance(seller, dict) and seller.get("telephone"):
        raw["phone"] = seller["telephone"]

    cover = prop.get("photo_url") or offer.get("image") or ""
    raw["image_urls"] = _gallery(html, cover)

    description = offer.get("description") or ""
    if description:
        description = BeautifulSoup(description, "lxml").get_text(" ", strip=True)
    raw["raw_text"] = f"{raw['title']}\n{description}"[:8000]

    if prop.get("is_archived"):
        raw["removed"] = True

    return raw
