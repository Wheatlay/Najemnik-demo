import json
import re

from bs4 import BeautifulSoup


def parse(html: str, url: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return {"notes": "otodom: __NEXT_DATA__ not found"}
    data = json.loads(m.group(1))
    ad = data.get("props", {}).get("pageProps", {}).get("ad")
    if not ad:
        return {"notes": "otodom: ad data missing"}

    raw: dict = {"site": "otodom", "title": ad.get("title", "")}

    chars = {c["key"]: c for c in ad.get("characteristics", [])}
    if "price" in chars:
        raw["rent_owner"] = chars["price"]["value"]
    if "rent" in chars:
        raw["czynsz_admin"] = chars["rent"]["value"]
    if "deposit" in chars:
        raw["deposit"] = chars["deposit"]["value"]
    if "m" in chars:
        raw["area_m2"] = chars["m"]["value"]
    if "rooms_num" in chars:
        raw["rooms"] = chars["rooms_num"]["value"]
    if "floor_no" in chars:
        raw["floor"] = chars["floor_no"]["value"].replace("floor_", "")
    if "building_floors_num" in chars:
        raw["floor_total"] = chars["building_floors_num"]["value"]

    loc = ad.get("location", {})
    coords = loc.get("coordinates", {})
    raw["lat"] = coords.get("latitude")
    raw["lon"] = coords.get("longitude")
    street = (loc.get("address") or {}).get("street") or {}
    street_name = street.get("name") or ""
    street_num = street.get("number") or ""
    reverse = (loc.get("reverseGeocoding") or {}).get("locations", [])
    city = next((l["name"] for l in reverse if l.get("locationLevel") == "city_or_village"), "")
    district = next((l["name"] for l in reverse if l.get("locationLevel") == "district"), "")
    raw["city"] = city
    raw["district"] = district
    raw["address"] = " ".join(p for p in (street_name, street_num) if p) or district or city

    contact = ad.get("contactDetails") or ad.get("owner") or ad.get("agency") or {}
    phones = contact.get("phones") or []
    if phones:
        raw["phone"] = phones[0]

    # advertiserType is Otodom's own structured advertiser-type field
    # ("business" for an agency/biuro nieruchomości, "private" for a direct
    # owner) - deterministic and free, so it takes priority over asking the
    # AI to infer posrednik from the ad text (core/pipeline/enrich/field_specs.py's
    # posrednik is only_if_empty, so a value set here suppresses that call).
    advertiser_type = ad.get("advertiserType")
    if advertiser_type == "business":
        raw["posrednik"] = True
    elif advertiser_type == "private":
        raw["posrednik"] = False

    images = ad.get("images", [])
    urls = [img.get("large") or img.get("medium") or img.get("small") or img.get("thumbnail") for img in images]
    raw["image_urls"] = [u for u in urls if u]

    desc = BeautifulSoup(ad.get("description", ""), "lxml").get_text(" ", strip=True)
    raw["raw_text"] = f"{raw['title']}\n{desc}"
    return raw
