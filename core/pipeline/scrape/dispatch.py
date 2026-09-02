import time
from urllib.parse import urlparse

from core.pipeline.scrape import generic, morizon, olx, otodom
from core.pipeline.scrape.cache import get_cached, record_fetch
from core.pipeline.scrape.fetch import fetch
from core.pipeline.scrape.urlnorm import normalize_url

# Only sites whose data can't be read from schema.org markup need an entry
# here. generic.parse already handles nieruchomosci-online and domiporta
# fully from their ld+json - adding modules for them would be two more
# parsers to maintain for no extra field.
PARSERS = {
    "otodom.pl": otodom.parse,
    "olx.pl": olx.parse,
    # One Nuxt app behind two brands (Grupa Morizon-Gratka) - see morizon.py.
    "morizon.pl": morizon.parse,
    "gratka.pl": morizon.parse,
}


def parser_for(url: str):
    host = urlparse(url).netloc.lower()
    for domain, fn in PARSERS.items():
        if domain in host:
            return fn
    return generic.parse


REMOVED_STATUS_CODES = {404, 410}


def scrape_url(url: str) -> dict:
    """Fetch a listing URL and return a raw (un-normalized) field dict, or
    {"removed": True} if the page 404s/410s or otherwise looks removed.

    Reads through FetchCache first (SPEC §7): a successful fetch of the
    same normalized URL by *any* user, newer than 6h, is reused with zero
    network traffic. A 200 response doesn't guarantee a real listing page -
    sites occasionally serve a bot-check/interstitial page instead (no
    embedded listing JSON), which the parser can't tell apart from a
    genuinely empty response. Retry a couple of times before giving up, so
    a single transient interstitial doesn't get treated as "successfully
    scraped an empty listing"."""
    url_normalized = normalize_url(url)
    cached = get_cached(url_normalized)
    if cached is not None:
        return cached

    parser = parser_for(url)
    raw: dict = {"notes": "no attempt made"}
    http_status = 0
    for attempt in range(3):
        r = fetch(url)
        http_status = r.status_code
        if r.status_code in REMOVED_STATUS_CODES:
            record_fetch(url_normalized, http_status, site=urlparse(url).netloc)
            return {"removed": True}
        if r.status_code != 200:
            raw = {"notes": f"HTTP {r.status_code}"}
        else:
            raw = parser(r.text, url)
            if raw.get("title"):
                break
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    raw["site"] = raw.get("site") or urlparse(url).netloc

    record_fetch(
        url_normalized, http_status, site=raw.get("site", ""),
        title=raw.get("title", ""), raw_payload=raw if http_status == 200 else None,
    )
    return raw


def scrape_html(url: str, html: str) -> dict:
    """Parse listing HTML the *client* already fetched (SPEC §21 1.5c, the
    browser extension) - same parsers as scrape_url, minus the network hop
    that's the entire reason the extension exists (host_permissions let a
    browser fetch a portal page directly, which this server's own IP
    otherwise has to do for every user).

    Deliberately does NOT call record_fetch(): FetchCache is a record of
    *this server's* fetches, read back with no ownership/dedup check beyond
    "http_status == 200 and recent" (see get_cached above) - writing an
    unverified client payload there would let one user's extension quietly
    serve fabricated data to every other user importing the same URL for
    the next 6h.
    """
    raw = parser_for(url)(html, url)
    raw["site"] = raw.get("site") or urlparse(url).netloc
    return raw
