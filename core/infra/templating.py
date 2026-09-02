"""Jinja environment, the render() helper every router uses, and the
template-side helpers (sort/nav URL building, the nav item list).

Naming convention in templates/partials/, enforced by nothing but worth
keeping straight:

  `name.html`   a **swappable view region**. Included by the full page on a
                normal load AND returned on its own as the body of an htmx
                response - gallery_content, map_content, compare_content,
                dashboard_content, settings_content, compare_row - or an
                htmx-only response body (detail_drawer, ingest_progress,
                ai_status, duplicates, compare_focus). If a route can name
                it as a response, it has no underscore.

  `_name.html`  a **fragment that is never a response body on its own**:
                either a building block included by a bigger template
                (_gallery_card, _filter_sidebar, _photo_gallery,
                _compare_row_inner, _callprep, _onboarding_*) or the htmx
                envelope machinery itself (_hx_view, _chrome_oob, _nav_bar,
                _search_form, _sidebar_region), which routes render but
                which are chrome rather than a view.

So: if you add a partial and a route returns it by name, no underscore.
Otherwise, underscore.
"""
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates

from core.domain import costs, display, fields, money_field
from core.infra.config import APP_NAME, BASE_DIR, DEMO_MODE, LOGO_DARK, LOGO_LIGHT
from core.pipeline.enrich import callprep_bank

templates = Jinja2Templates(directory="templates")

_STATIC_DIR = BASE_DIR / "static"


def asset_version(rel_path: str) -> str:
    """Cache-busting suffix for a file under static/, from its mtime.

    StaticFiles serves these at URLs that never change, so a browser that
    cached one keeps using the stale copy forever. For static/css/output.css
    - a gitignored Tailwind build artifact rebuilt by
    scripts/tools/build-css.bat - that means a restyle silently doesn't
    apply, which is invisible until you're staring at an unchanged page
    wondering whether the CSS is broken. It would hit beta testers over
    the zrok tunnel the same way, with no reason for them to guess at a
    hard refresh.

    Stat'ed per render rather than once at import, because the usual loop
    rebuilds assets *without* restarting the server - caching the value at
    import would reintroduce exactly the staleness this removes. A stat()
    per render is far below the noise floor next to the DB queries every
    view already does.
    """
    try:
        return str(int((_STATIC_DIR / rel_path).stat().st_mtime))
    except OSError:
        # Not built yet (fresh clone before build-css.bat), or a typo'd
        # path. The asset 404s on its own; don't take the page down too.
        return "0"


def render(request: Request, name: str, context: dict | None = None, **kwargs):
    ctx = dict(context or {})
    ctx.setdefault("current_user", getattr(request.state, "user", None))
    ctx.setdefault("csrf_token", getattr(request.state, "csrf_token", ""))
    return templates.TemplateResponse(request, name, ctx, **kwargs)


def sort_url(request: Request, key: str) -> str:
    """Query string for this column's header link: toggles asc <-> desc if
    it's already the active sort column, otherwise starts ascending -
    preserves every other current filter/query param."""
    current = request.query_params.get("sort", "")
    next_sort = f"-{key}" if current == key else key
    pairs = [(k, v) for k, v in request.query_params.multi_items() if k != "sort"]
    pairs.append(("sort", next_sort))
    return "?" + urlencode(pairs)


def sort_state(request: Request, key: str) -> str:
    """'asc' / 'desc' if `key` is the active sort column, else ''."""
    current = request.query_params.get("sort", "")
    if current == key:
        return "asc"
    if current == f"-{key}":
        return "desc"
    return ""


def nav_url(request: Request, path: str) -> str:
    """Top-nav link target that carries the current sort/filter query string
    over to the next view - switching from Galeria to Mapa and back
    shouldn't silently drop the sort order or active filters."""
    qs = request.query_params
    return f"{path}?{qs}" if str(qs) else path


# The top nav: only the views onto the user's listings. Ustawienia and Konto
# deliberately live in the account dropdown instead (base.html) - they're
# configuration, visited occasionally, and having Ustawienia in both places
# just made the nav wider.
NAV_ITEMS = [
    ("/mapa", "Mapa"),
    ("/galeria", "Galeria"),
    ("/porownaj2", "Porównaj"),
    ("/panel", "Pulpit"),
]

# Page titles, which need every view - including the ones not in the nav.
# Kept separate so dropping a page from the nav can't silently degrade its
# <title> to the raw view slug (base.html / _chrome_oob.html both read this).
NAV_LABELS = {path.strip("/"): label for path, label in NAV_ITEMS} | {
    "porownaj2": "Porównaj",
    "pomoc": "Pomoc i FAQ",
}


# How long after creation a photo-less listing is assumed to still be
# downloading. Photo download runs on a background thread after the import
# response is already sent (core/pipeline/ingest.py finish_listing_async), so
# there is a short window where "no photos yet" and "no photos at all" look
# identical in the DB. Bounded on purpose: plenty of listings genuinely have
# no photos, and they must not poll forever.
_PHOTO_GRACE = timedelta(minutes=2)


def is_awaiting_photos(listing) -> bool:
    if listing.photos or listing.created_at is None:
        return False
    return datetime.now() - listing.created_at < _PHOTO_GRACE



templates.env.globals.update(
    APP_NAME=APP_NAME,
    DEMO_MODE=DEMO_MODE,
    is_awaiting_photos=is_awaiting_photos,
    asset_version=asset_version,
    LOGO_LIGHT=LOGO_LIGHT,
    LOGO_DARK=LOGO_DARK,
    fields=fields,
    display=display,
    costs=costs,
    money=money_field,
    callprep=callprep_bank,
    STATUS_VALUES=display.STATUS_VALUES,
    STATUS_PILL_CLASSES=display.STATUS_PILL_CLASSES,
    STATUS_MARKER_VARS=display.STATUS_MARKER_VARS,
    COMPARE_GROUP_COLORS=display.COMPARE_GROUP_COLORS,
    COMPARE_GROUP_COLOR_DEFAULT=display.COMPARE_GROUP_COLOR_DEFAULT,
    sort_url=sort_url,
    sort_state=sort_state,
    nav_url=nav_url,
    NAV_ITEMS=NAV_ITEMS,
    NAV_LABELS=NAV_LABELS,
)
