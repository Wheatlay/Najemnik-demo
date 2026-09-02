import threading
import time
from urllib.parse import urlparse

import requests

from core.infra.config import HTTP_HEADERS


class FetchError(Exception):
    pass


# Politeness (SPEC §7): >=5s between requests to the same host, global
# concurrency capped at 2 - the FetchCache is what actually keeps traffic
# low (most re-fetches never reach here), this just keeps a burst of
# distinct-URL imports from hammering one host.
_DOMAIN_DELAY_SECONDS = 5
_MAX_CONCURRENT_FETCHES = 2

_domain_lock = threading.Lock()
_last_fetch_at: dict[str, float] = {}
_concurrency_semaphore = threading.Semaphore(_MAX_CONCURRENT_FETCHES)


def _wait_for_domain_turn(host: str) -> None:
    with _domain_lock:
        last = _last_fetch_at.get(host, 0.0)
        wait = _DOMAIN_DELAY_SECONDS - (time.monotonic() - last)
        _last_fetch_at[host] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)


def fetch(url: str, retries: int = 3, timeout: int = 25) -> requests.Response:
    host = urlparse(url).netloc.lower()
    last_exc = None
    with _concurrency_semaphore:
        _wait_for_domain_turn(host)
        for attempt in range(retries):
            try:
                r = requests.get(url, headers=HTTP_HEADERS, timeout=timeout)
                r.encoding = r.apparent_encoding or "utf-8"
                return r
            except requests.RequestException as e:
                last_exc = e
                time.sleep(1.5 * (attempt + 1))
    raise FetchError(str(last_exc)) from last_exc
