import json
import re

from bs4 import BeautifulSoup


def parse(html: str, url: str) -> dict:
    m = re.search(r"window\.__PRERENDERED_STATE__=\s*(\".*?\");", html, re.DOTALL)
    if not m:
        return {"notes": "olx: __PRERENDERED_STATE__ not found"}
    data = json.loads(json.loads(m.group(1)))
    ad = data.get("ad", {}).get("ad")
    if not ad:
        return {"notes": "olx: ad data missing"}

    raw: dict = {"site": "olx", "title": ad.get("title", "")}

    # isBusiness is OLX's own structured advertiser-type flag - deterministic
    # and free, so it takes priority over asking the AI to infer posrednik
    # from the ad text (core/pipeline/enrich/field_specs.py's posrednik is
    # only_if_empty, so a value set here suppresses that call).
    if "isBusiness" in ad:
        raw["posrednik"] = bool(ad["isBusiness"])

    price = ad.get("price", {}) or {}
    reg = price.get("regularPrice") or {}
    if reg.get("value") is not None:
        raw["rent_owner"] = reg.get("value")

    params = {p["key"]: p for p in ad.get("params", [])}
    if "rent" in params:
        raw["czynsz_admin"] = params["rent"]["value"]
    if "m" in params:
        raw["area_m2"] = params["m"]["value"]
    if "rooms" in params:
        raw["rooms"] = params["rooms"]["value"]
    if "floor_select" in params:
        raw["floor"] = params["floor_select"]["value"]

    loc = ad.get("location", {})
    raw["city"] = loc.get("cityName", "")
    raw["district"] = loc.get("districtName", "")

    map_ = ad.get("map", {})
    raw["lat"] = map_.get("lat")
    raw["lon"] = map_.get("lon")

    # OLX hides the phone behind a client-side "reveal" interaction with no
    # static value in the page payload - leave phone null, don't try to
    # bypass it (SPEC §8).
    raw["notes"] = "olx: phone hidden behind reveal button, not scraped"

    photos = ad.get("photos") or ad.get("photosSet") or []
    raw["image_urls"] = [p for p in photos if isinstance(p, str)]

    desc_html = ad.get("description", "")
    desc = BeautifulSoup(desc_html, "lxml").get_text(" ", strip=True)
    raw["raw_text"] = f"{raw['title']}\n{desc}"

    addr_m = re.search(
        r"\bul\.?\s+[A-ZŻŹĆŃŁÓĄŚĘ][\wżźćńółąśęĄŚĘŁÓŻŹĆŃ.\-]*(?:\s+\d+\w*)?",
        raw["raw_text"],
    )
    raw["address"] = addr_m.group(0) if addr_m else (raw["district"] or raw["city"])
    return raw
