import statistics
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from core.domain.commute import commute_distances
from core.domain.costs import cena_za_m2, cost_context, suma_miesieczna, suma_roczna, suma_wejscia
from core.infra.config import DEMO_MODE
from core.infra.db import new_session
from core.models import Listing, Status, User
from core.domain.queries import apply_filters, has_any_listings, has_demo_listings
from core.domain.settings import get_settings
from core.infra.deps import current_user, get_owned_listing
from core.infra.templating import is_awaiting_photos, render

router = APIRouter(dependencies=[Depends(current_user)])


def _is_hx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _render_view(request: Request, full_template: str, partial_template: str, ctx: dict):
    """Full page on a normal browser nav; on an htmx request, the view's own
    content plus an out-of-band refresh of the nav bar / filter sidebar /
    search form / title, since those live outside #main-content and depend
    on `view` too (see partials/_chrome_oob.html)."""
    if _is_hx(request):
        return render(request, "partials/_hx_view.html", {**ctx, "content_template": partial_template})
    return render(request, full_template, ctx)


@router.get("/")
def root():
    return RedirectResponse(url="/galeria")


@router.post("/demo/wczytaj")
def load_demo(user: User = Depends(current_user)):
    from core.pipeline.demo import load_demo_listings
    with new_session() as session:
        load_demo_listings(session, user.id)
    return RedirectResponse(url="/galeria", status_code=303)


@router.post("/demo/usun")
def remove_demo(user: User = Depends(current_user)):
    """Clear the bundled examples. Scoped to is_demo rows - the only kind of
    listing this app still hard-deletes, since the user didn't collect them
    (see core/pipeline/demo.remove_demo_listings)."""
    from core.pipeline.demo import remove_demo_listings
    with new_session() as session:
        remove_demo_listings(session, user.id)
    return RedirectResponse(url="/galeria", status_code=303)


@router.post("/demo/reset")
def reset_demo(user: User = Depends(current_user)):
    """Restore the current browser's synthetic portfolio dataset."""
    if not DEMO_MODE:
        raise HTTPException(status_code=404)
    from core.pipeline.demo import load_demo_listings, remove_demo_listings
    with new_session() as session:
        remove_demo_listings(session, user.id)
        load_demo_listings(session, user.id)
    return RedirectResponse(url="/galeria", status_code=303)


@router.get("/galeria")
def galeria(request: Request, user: User = Depends(current_user)):
    with new_session() as session:
        listings = apply_filters(session, user.id, request.query_params)
        focus_id = request.query_params.get("focus")
        ctx = {"listings": listings, "view": "galeria", "focus_id": focus_id,
               "cost_ctx": cost_context(user.id),
               "has_any_listings": has_any_listings(session, user.id),
               "has_demo_listings": has_demo_listings(session, user.id)}
        return _render_view(request, "gallery.html", "partials/gallery_content.html", ctx)


@router.get("/mapa")
def mapa(request: Request, user: User = Depends(current_user)):
    with new_session() as session:
        listings = apply_filters(session, user.id, request.query_params)
        cost_ctx = cost_context(user.id)
        map_points = [
            {"id": l.id, "lat": l.lat, "lon": l.lon, "status": l.status.value,
             "suma": suma_miesieczna(l), "wejscie": suma_wejscia(l), "rok": suma_roczna(l),
             "price_color": cost_ctx.suma_miesieczna_marker_var(l),
             "wejscie_color": cost_ctx.suma_wejscia_marker_var(l), "rok_color": cost_ctx.suma_roczna_marker_var(l),
             "title": l.title, "district": l.district, "rooms": l.rooms, "area_m2": l.area_m2,
             "photo": f"/{l.photos[0]}" if l.photos else None}
            for l in listings if l.lat is not None and l.lon is not None
        ]
        focus_id = request.query_params.get("focus")
        # The reference points from /ustawienia, drawn on the map as their own
        # kind of marker - until now they only ever produced a distance number
        # in the drawer, so there was no way to see *where* they actually are.
        commute_points = [
            {"id": p.get("id"), "name": p.get("name"), "lat": p.get("lat"), "lon": p.get("lon")}
            for p in (get_settings(user.id).commute_points or [])
            if p.get("lat") is not None and p.get("lon") is not None
        ]
        ctx = {"listings": listings, "view": "mapa", "map_points": map_points, "focus_id": focus_id,
               "commute_points": commute_points,
               "cost_ctx": cost_ctx, "has_any_listings": has_any_listings(session, user.id)}
        return _render_view(request, "map.html", "partials/map_content.html", ctx)


@router.get("/porownaj2")
def porownaj2(request: Request, ids: str = "", user: User = Depends(current_user)):
    """Compare the two to four synthetic listings selected in the gallery."""
    listing_ids = [i for i in ids.split(",") if i]
    with new_session() as session:
        listings = [get_owned_listing(session, user.id, i) for i in listing_ids]
        listings = [l for l in listings if l]
        ctx = {
            "view": "porownaj2", "listings": listings,
            "best": best_per_field(listings) if 2 <= len(listings) <= 4 else {},
            "cost_ctx": cost_context(user.id),
            "has_any_listings": has_any_listings(session, user.id),
            "compare_ids": ",".join(l.id for l in listings),
        }
        return _render_view(request, "compare2.html", "partials/compare2_content.html", ctx)


@router.get("/panel")
def panel(request: Request, user: User = Depends(current_user)):
    with new_session() as session:
        listings = apply_filters(session, user.id, request.query_params)
        active = [l for l in listings if l.is_active]
        totals = [c for l in active if (c := suma_miesieczna(l)) is not None]
        m2_totals = [c for l in active if (c := cena_za_m2(l)) is not None]
        # Status counts always reflect every non-deleted listing (including
        # Odrzucone) so the dashboard shows the full picture, even though
        # apply_filters() hides Odrzucone from `listings`/stats/cheapest by
        # default - it's an archive state, not something to count out of view.
        all_listings = session.exec(select(Listing).where(Listing.user_id == user.id)).all()
        counts: dict = {}
        for l in all_listings:
            counts[l.status.value] = counts.get(l.status.value, 0) + 1
        cheapest = sorted(active, key=lambda l: (
            suma_miesieczna(l) is None, suma_miesieczna(l) or 0))[:5]
        best_rated = sorted(
            [l for l in active if l.ocena_wygladu or l.ocena_glosnosci_otoczenia],
            key=lambda l: -(((l.ocena_wygladu or 0) + (l.ocena_glosnosci_otoczenia or 0)) / 2),
        )[:5]
        ranked = sorted([l for l in active if l.rank], key=lambda l: l.rank)[:5]
        # "Umówione" without a termin isn't an *upcoming* viewing yet - it
        # still needs a date picked, so it doesn't belong in this agenda.
        # Sorting ascending naturally puts overdue (past) dates first.
        upcoming_viewings = sorted(
            [l for l in active if l.status == Status.UMOWIONE and l.termin_ogledzin],
            key=lambda l: l.termin_ogledzin,
        )
        ctx = {
            "listings": listings, "view": "panel", "counts": counts,
            "avg_cost": round(sum(totals) / len(totals)) if totals else None,
            "median_cost": round(statistics.median(totals)) if totals else None,
            "avg_m2": round(sum(m2_totals) / len(m2_totals)) if m2_totals else None,
            "stats_count": len(active),
            "cheapest": cheapest, "best_rated": best_rated, "ranked": ranked,
            # termin_ogledzin comes from a browser <input type="datetime-local">
            # (naive local wall-clock time) - "now" must be naive local too,
            # or overdue/upcoming here is off by the UTC offset.
            "upcoming_viewings": upcoming_viewings, "now": datetime.now(),
            "has_any_listings": len(all_listings) > 0,
        }
        return _render_view(request, "dashboard.html", "partials/dashboard_content.html", ctx)


def best_per_field(listings: list[Listing]) -> dict[str, list[str]]:
    """For each `compare`-shown field with a known better/worse direction,
    which listing id(s) hold the best value - used by the focused
    (2-4 selected) compare panel to highlight winners per row."""
    from core.domain.costs import cena_za_m2, suma_miesieczna, suma_wejscia
    from core.domain.fields import BETTER_DIRECTION, fields_in

    best: dict[str, list[str]] = {}
    for f in fields_in("compare"):
        direction = BETTER_DIRECTION.get(f.key)
        if not direction:
            continue
        if f.key == "suma_miesieczna":
            values = {l.id: suma_miesieczna(l) for l in listings}
        elif f.key == "cena_za_m2":
            values = {l.id: cena_za_m2(l) for l in listings}
        elif f.key == "suma_wejscia":
            values = {l.id: suma_wejscia(l) for l in listings}
        else:
            values = {l.id: getattr(l, f.key, None) for l in listings}
        present = {lid: v for lid, v in values.items() if v is not None}
        if not present:
            continue
        target = min(present.values()) if direction == "min" else max(present.values())
        best[f.key] = [lid for lid, v in present.items() if v == target]
    return best


@router.get("/porownaj/focus")
def porownaj_focus(request: Request, compare_ids: str = "", user: User = Depends(current_user)):
    ids = [i for i in compare_ids.split(",") if i]
    with new_session() as session:
        listings = [get_owned_listing(session, user.id, i) for i in ids]
        listings = [l for l in listings if l]
        if not 2 <= len(listings) <= 4:
            return render(request, "partials/compare_focus.html", {"listings": [], "best": {}})
        return render(request, "partials/compare_focus.html",
                      {"listings": listings, "best": best_per_field(listings), "cost_ctx": cost_context(user.id)})


def listing_ctx(listing: Listing) -> dict:
    """Context shared by every render of detail_drawer.html - gallery_card.html
    and compare_row.html ignore the extra keys, so callers that pick between
    the three templates (a field/rank edit can re-render any of them,
    depending which view is behind the drawer) can use this unconditionally.
    Includes a fresh cost_ctx so the re-rendered card/row/drawer colors its
    cost against the same market the list view does."""
    settings = get_settings(listing.user_id)
    return {"listing": listing, "cost_ctx": cost_context(listing.user_id),
            "commute_distances": commute_distances(listing.lat, listing.lon, settings.commute_points)}


@router.get("/listings/{listing_id}/drawer")
def drawer(request: Request, listing_id: str, user: User = Depends(current_user)):
    with new_session() as session:
        listing = get_owned_listing(session, user.id, listing_id)
        if not listing:
            return render(request, "partials/drawer_empty.html")
        return render(request, "partials/detail_drawer.html", listing_ctx(listing))


# htmx cancels a polling trigger when the response carries this status. Still
# a 2xx, so the final contents swap in before the poll stops.
_HTMX_STOP_POLLING = 286


@router.get("/listings/{listing_id}/photo")
def gallery_card_photo(request: Request, listing_id: str, user: User = Depends(current_user)):
    """Re-renders the contents of a gallery card's image layer, so a card
    waiting on its photos fills itself in once they land (see
    _gallery_card.html for why the container around this never swaps)."""
    with new_session() as session:
        listing = get_owned_listing(session, user.id, listing_id)
        if not listing:
            # Deleted mid-poll: stop now rather than retrying until the grace
            # window happens to close.
            return HTMLResponse("", status_code=_HTMX_STOP_POLLING)
        done = not is_awaiting_photos(listing)
        return render(request, "partials/_gallery_card_photo.html", {"listing": listing},
                      status_code=_HTMX_STOP_POLLING if done else 200)


@router.get("/listings/{listing_id}/drawer-photos")
def drawer_photos(request: Request, listing_id: str, user: User = Depends(current_user)):
    """Same idea as gallery_card_photo above, for the drawer's larger photo
    gallery (see detail_drawer.html's polling wrapper for why)."""
    with new_session() as session:
        listing = get_owned_listing(session, user.id, listing_id)
        if not listing:
            return HTMLResponse("", status_code=_HTMX_STOP_POLLING)
        done = not is_awaiting_photos(listing)
        return render(request, "partials/_photo_gallery.html", {"listing": listing},
                      status_code=_HTMX_STOP_POLLING if done else 200)


