"""
URL normalization (SPEC §7): canonical form used both as the per-user
dedup key (core.pipeline.ingest) and the FetchCache key (cross-user, cuts real
network traffic to the source sites). Strips tracking noise and reduces
Otodom/OLX URLs to just their listing path.
"""
from urllib.parse import urlparse, urlunparse

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "igshid", "mc_cid", "mc_eid")


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    # Otodom/OLX encode the listing id in the path - the query string is
    # always tracking noise for both, so drop it entirely rather than
    # selectively filtering params.
    if "otodom.pl" in host or "olx.pl" in host:
        query = ""
    else:
        kept = [
            p for p in parsed.query.split("&")
            if p and not any(p.split("=")[0].lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
        ]
        query = "&".join(kept)

    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower() or "https", host, path, "", query, ""))
