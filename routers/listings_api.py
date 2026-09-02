from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from core.infra.db import new_session
from core.domain import money_field
from core.domain.costs import MISSING_INFO
from core.domain.fields import FIELDS_BY_KEY, is_editable
from core.models import Status, User
from core.domain.normalize import (
    normalize_available_from,
    normalize_ocena,
    normalize_phone,
    normalize_status,
    normalize_title_case,
    to_float,
    to_int,
)
from core.domain.rank import set_rank
from core.infra.deps import current_user, get_owned_listing
from routers.pages import listing_ctx
from core.infra.templating import render as render_template

router = APIRouter(dependencies=[Depends(current_user)])

# Which partial a field/rank edit returns, keyed by the `render` the client
# asks for. "drawer" refreshes the open drawer; "compare_row" swaps just that
# table row (compare inline edits get no global refresh, unlike drawer edits -
# see static/js/drawer.js). Gallery cards have no inline edit controls (clicking
# one opens the drawer), so there is deliberately no "gallery_card" entry.
_RENDER_TEMPLATES = {
    "drawer": "partials/detail_drawer.html",
    "compare_row": "partials/compare_row.html",
}
_DEFAULT_RENDER_TEMPLATE = "partials/detail_drawer.html"


def _coerce(field_key: str, raw_value: str):
    f = FIELDS_BY_KEY[field_key]
    raw_value = raw_value.strip() if isinstance(raw_value, str) else raw_value
    if f.type == "number":
        return to_float(raw_value) if field_key == "area_m2" else to_int(raw_value)
    if f.type == "date":
        return normalize_available_from(raw_value)
    if f.type == "datetime":
        if not raw_value:
            return None
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            return None
    if f.type == "select_status":
        return normalize_status(raw_value)
    if f.type == "select_ocena":
        return normalize_ocena(raw_value)
    if f.type == "tags":
        return [t.strip() for t in raw_value.split(",") if t.strip()]
    if f.type == "select_bool":
        # A non-nullable select_bool (e.g. pewnosc_lokalizacji) has no third
        # option to send, so raw_value is always "true"/"false" in practice -
        # default defensively to False (the model's own default) rather than
        # None, which that column no longer accepts as a meaningful value.
        return {"true": True, "false": False}.get(raw_value, None if f.nullable else False)
    if f.type == "select_enum":
        # Anything outside the closed set (stale form, hand-crafted request)
        # reads as "the ad never said" rather than being stored as a value
        # the cost tables have no entry for.
        return raw_value if raw_value in f.options else MISSING_INFO
    if field_key == "phone":
        return normalize_phone(raw_value)
    if field_key in ("city", "district"):
        return normalize_title_case(raw_value)
    return raw_value or ""


def _coerce_money(field_key: str, status: str, amount: str, note: str) -> dict | None:
    """A money field arrives as three inputs and is stored as one struct.

    Validated through the same money_field.validate the AI path uses, so a
    hand-typed amount is held to the identical plausible range - the
    free-text box this replaced accepted anything and silently contributed
    nothing to the totals when it wasn't a bare number.

    Also resolves a dual-purpose amount box (the kwota input still accepts
    stray text if someone pastes into it): if it holds something that isn't
    a valid amount and no separate note was supplied, that text becomes the
    note instead of being silently dropped.
    """
    amount = (amount or "").strip()
    note = (note or "").strip()
    if status == money_field.STATUS_YES and amount and not note and money_field.to_amount(amount) is None:
        note, amount = amount, ""
    return money_field.validate(field_key, {
        "status": status, "amount": amount, "note": note,
    })


@router.patch("/listings/{listing_id}/field")
def patch_field(request: Request, listing_id: str, key: str = Form(...),
                 value: str = Form(""), render: str = Form("drawer"),
                 status: str = Form(""), amount: str = Form(""), note: str = Form(""),
                 user: User = Depends(current_user)):
    if not is_editable(key):
        return JSONResponse({"error": f"field '{key}' is not editable"}, status_code=400)
    with new_session() as session:
        listing = get_owned_listing(session, user.id, listing_id)
        if not listing:
            return JSONResponse({"error": "not found"}, status_code=404)

        field = FIELDS_BY_KEY[key]
        if field.type == "smart_money":
            setattr(listing, key, _coerce_money(key, status, amount, note))
        else:
            setattr(listing, key, _coerce(key, value))

        # The value is the user's now, so it stops being credited to AI: drop
        # the stored receipt and remember the override. Reassigning (rather
        # than mutating in place) is required - SQLAlchemy doesn't track
        # mutations inside a plain JSON column, so an in-place pop/append
        # would never reach the database.
        if key in listing.ai_evidence:
            listing.ai_evidence = {k: v for k, v in listing.ai_evidence.items() if k != key}
        if key not in listing.edited_fields:
            listing.edited_fields = [*listing.edited_fields, key]

        listing.updated_at = datetime.now()
        session.add(listing)
        session.commit()
        session.refresh(listing)

        # Odrzucone is an archive state - a rejected listing shouldn't keep
        # occupying a ranking slot. set_rank(None) also cascades the
        # remaining ranked listings back down to a contiguous 1..N, the same
        # as clicking "usuń z rankingu" would.
        if key == "status" and listing.status == Status.ODRZUCONE and listing.rank is not None:
            set_rank(session, user.id, listing_id, None)
            session.refresh(listing)

        if key == "termin_ogledzin" and listing.termin_ogledzin is not None:
            from core.infra.events import record_event
            record_event(user.id, "viewing_scheduled", listing_id=listing_id)

        template = _RENDER_TEMPLATES.get(render, _DEFAULT_RENDER_TEMPLATE)
        return render_template(request, template, listing_ctx(listing))


@router.post("/listings/{listing_id}/rank")
def patch_rank(request: Request, listing_id: str, value: str = Form(""), render: str = Form("drawer"),
                user: User = Depends(current_user)):
    with new_session() as session:
        listing = get_owned_listing(session, user.id, listing_id)
        if not listing:
            return JSONResponse({"error": "not found"}, status_code=404)
        new_rank = to_int(value) if value.strip() else None
        set_rank(session, user.id, listing_id, new_rank)
        session.refresh(listing)
        template = _RENDER_TEMPLATES.get(render, _DEFAULT_RENDER_TEMPLATE)
        return render_template(request, template, listing_ctx(listing))


# No DELETE /listings/{id}. Removing a single listing permanently was a
# one-misclick-from-a-confirm-dialog action on data a user spent a whole
# search collecting, with no undo. Setting the status to "Odrzucone" is the
# reversible way to put a listing aside, and /konto still offers full
# account deletion for GDPR. Photos are cleaned up with the account.


@router.post("/listings/{listing_id}/position")
def set_position(request: Request, listing_id: str, lat: float = Form(...), lon: float = Form(...),
                  user: User = Depends(current_user)):
    with new_session() as session:
        listing = get_owned_listing(session, user.id, listing_id)
        if listing:
            listing.lat = lat
            listing.lon = lon
            # The map only allows dragging a pin at all when the user has
            # explicitly turned on "przesuń pinezkę" mode - reaching this
            # endpoint means they deliberately hand-placed it against the
            # real address, which is exactly what pewnosc_lokalizacji means.
            listing.pewnosc_lokalizacji = True
            session.add(listing)
            session.commit()
    return JSONResponse({"ok": True})
