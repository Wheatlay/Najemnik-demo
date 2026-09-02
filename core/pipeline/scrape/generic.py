import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

NUM_RE = r"[\d]{1,3}(?:[\s.]?\d{3})*(?:[.,]\d+)?"


def site_label(url: str) -> str:
    """'warszawa.nieruchomosci-online.pl' -> 'nieruchomosci-online'.

    The label was hardcoded to nieruchomosci-online-or-"other", which lumped
    every other portal this parser handles under one meaningless name in the
    UI and in FetchCache. Take the registrable name: the last two labels,
    stepping one further left past the second-level suffixes Polish sites
    use (.com.pl, .net.pl)."""
    host = urlparse(url).netloc.lower().split(":")[0]
    parts = [p for p in host.split(".") if p and p != "www"]
    if len(parts) < 2:
        return host or "other"
    if len(parts) >= 3 and parts[-2] in ("com", "net", "org", "co"):
        return parts[-3]
    return parts[-2]


def _first(*values):
    """First value that isn't None/empty - schema.org lets the same field sit
    on the listing wrapper or on the property it wraps."""
    for v in values:
        if v not in (None, "", {}, []):
            return v
    return None


def parse(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    raw: dict = {"site": site_label(url)}

    title_tag = soup.find("meta", property="og:title") or soup.find("title")
    raw["title"] = (
        title_tag.get("content") if title_tag and title_tag.has_attr("content")
        else title_tag.get_text(strip=True) if title_tag else ""
    ) or ""

    ldjson_objs = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        ldjson_objs.extend(obj if isinstance(obj, list) else [obj])

    apartment = next(
        (o for o in ldjson_objs if o.get("@type") in ("Apartment", "Product", "House", "RealEstateListing")),
        None,
    )
    if apartment:
        # A RealEstateListing/Product commonly wraps the actual Apartment in
        # itemOffered, keeping name/address/offers on the outside and
        # geo/floorSize/numberOfRooms on the inside (domiporta does exactly
        # this). Reading only the outer object silently lost half the
        # listing, so consult both.
        item = apartment.get("itemOffered")
        item = item if isinstance(item, dict) else {}

        addr = _first(apartment.get("address"), item.get("address")) or {}
        raw["address"] = addr.get("streetAddress", "")
        raw["city"] = addr.get("addressLocality", "")
        geo = _first(apartment.get("geo"), item.get("geo")) or {}
        raw["lat"] = geo.get("latitude")
        raw["lon"] = geo.get("longitude")

        offers = _first(apartment.get("offers"), item.get("offers"))
        offer = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offer, dict) and offer.get("price"):
            raw["rent_owner"] = offer.get("price")

        floor_size = _first(apartment.get("floorSize"), item.get("floorSize")) or {}
        if floor_size.get("value"):
            raw["area_m2"] = floor_size.get("value")
        rooms = _first(apartment.get("numberOfRooms"), item.get("numberOfRooms"))
        if rooms:
            raw["rooms"] = str(rooms)
        floor = _first(apartment.get("floorLevel"), item.get("floorLevel"))
        if floor is not None:
            raw["floor"] = str(floor)

        imgs = _first(apartment.get("image"), item.get("image")) or []
        imgs = imgs if isinstance(imgs, list) else [imgs]
        raw["image_urls"] = imgs

        agent = _first(apartment.get("agent"), apartment.get("seller"), item.get("agent")) or {}
        if isinstance(agent, dict) and agent.get("telephone"):
            raw["phone"] = agent["telephone"]

    if not raw.get("rent_owner"):
        og_price = soup.find("meta", property="product:price:amount") or soup.find("meta", itemprop="price")
        if og_price:
            raw["rent_owner"] = og_price.get("content")

    if not raw.get("image_urls"):
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            raw["image_urls"] = [og_img["content"]]

    body_text = soup.get_text(" ", strip=True)
    raw["raw_text"] = f"{raw['title']}\n{body_text[:4000]}"

    if not raw.get("phone"):
        tel_m = re.search(r"(?:\+48[\s-]?)?\d{3}[\s-]?\d{3}[\s-]?\d{3}\b", body_text)
        if tel_m:
            raw["phone"] = tel_m.group(0)

    if not raw.get("address"):
        addr_m = re.search(
            r"\bul\.?\s+[A-ZŻŹĆŃŁÓĄŚĘ][\wżźćńółąśęĄŚĘŁÓŻŹĆŃ.\-]*(?:\s+\d+\w*)?",
            body_text,
        )
        if addr_m:
            raw["address"] = addr_m.group(0)

    if not raw.get("rent_owner"):
        price_m = re.search(rf"({NUM_RE})\s*z(?:ł|l)\b", body_text)
        if price_m:
            raw["rent_owner"] = price_m.group(1)

    raw["notes"] = (raw.get("notes", "") + " generic-parser").strip()
    return raw
