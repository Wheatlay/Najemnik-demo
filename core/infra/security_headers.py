"""Standard security headers (SPEC §13) on every response."""
from starlette.middleware.base import BaseHTTPMiddleware

# tiles.openfreemap.org serves both the MapLibre style JSON and the actual
# vector tiles (static/js/map.js); unpkg.com is the htmx/Alpine/MapLibre CDN.
# 'unsafe-eval' is required by Alpine.js, which evaluates x-data/x-show/
# @click expressions via `new Function()` internally - without it, Alpine
# throws a CSP violation on every directive and silently never runs (every
# x-show'd element, including the ingest modal, stays at its default CSS
# display instead of being hidden), breaking the whole app's interactivity.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https://tiles.openfreemap.org; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com; "
    "connect-src 'self' https://unpkg.com https://tiles.openfreemap.org; "
    "font-src 'self' data:; "
    # MapLibre GL spins up its rendering work in a Web Worker created from a
    # blob: URL - without this, worker-src falls back to script-src (no
    # blob:), and the browser silently blocks the worker, breaking the map.
    "worker-src 'self' blob:;"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["Referrer-Policy"] = "same-origin"
        return response
