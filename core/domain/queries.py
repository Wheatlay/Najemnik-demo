"""
Shared filter/sort logic (SPEC §10 Filtering) used by every view so map,
gallery, compare and dashboard always agree on "what's currently shown".
"""
from sqlmodel import Session, func, select

from core.domain.costs import cena_za_m2, suma_miesieczna, suma_wejscia
from core.domain.money_field import presence as money_presence
from core.models import Listing, Status

# --- "Is this listing still in play?" - two questions, not one ------------
#
# These were previously spelled out inline at four call sites, in three
# different combinations, with no way to tell deliberate variation from
# oversight. They ARE meant to differ; naming them is what makes that
# readable. Use as SQLAlchemy filter expressions:
#
#     select(Listing).where(Listing.user_id == uid, *STILL_LISTED)
#
# STILL_LISTED  - the ad itself hasn't come down (is_active). Says nothing
#                 about what the user thinks of it.
# NOT_REJECTED  - the user hasn't archived it (status != Odrzucone). Says
#                 nothing about whether the ad still exists.
#
# Pick deliberately. The gallery shows dead-but-not-rejected ads on purpose
# (you want to see one went down); the market baseline in core/domain/costs.py
# excludes both, since neither should skew a median you're comparing against.
STILL_LISTED = (Listing.is_active == True,)  # noqa: E712 - SQL expression, not a bool test
NOT_REJECTED = (Listing.status != Status.ODRZUCONE,)


def has_any_listings(session: Session, user_id: str) -> bool:
    """Brand-new-account check (SPEC §10): distinguishes "no listings at
    all yet" (post-signup empty state) from "filtered down to zero"
    (regular empty state), which the plain `listings` list can't tell
    apart on its own."""
    count = session.exec(
        select(func.count()).select_from(Listing).where(Listing.user_id == user_id)
    ).one()
    return count > 0


def has_demo_listings(session: Session, user_id: str) -> bool:
    """Whether the bundled examples are currently loaded - drives the demo
    banner and its one-click cleanup (templates/partials/_demo_banner.html)."""
    count = session.exec(
        select(func.count()).select_from(Listing)
        .where(Listing.user_id == user_id, Listing.is_demo == True)  # noqa: E712
    ).one()
    return count > 0


def apply_filters(session: Session, user_id: str, params: dict) -> list[Listing]:
    listings = list(session.exec(select(Listing).where(Listing.user_id == user_id)).all())

    def get(name):
        v = params.get(name)
        return v if v not in (None, "") else None

    def get_num(name, cast):
        """Like get(), but for a numeric filter param - a malformed value
        (hand-edited URL, stale bookmark) is treated the same as the filter
        not being set at all, rather than 500ing the whole page."""
        v = get(name)
        if v is None:
            return None
        try:
            return cast(v)
        except ValueError:
            return None

    statuses = params.getlist("status") if hasattr(params, "getlist") else params.get("status")
    if isinstance(statuses, str):
        statuses = [statuses]
    if statuses:
        listings = [l for l in listings if l.status.value in statuses]
    else:
        # Odrzucone is an archive state - hidden by default everywhere
        # (gallery/map/compare/stats) unless the user explicitly opts in by
        # ticking it in the status filter.
        listings = [l for l in listings if l.status != Status.ODRZUCONE]

    price_min, price_max = get_num("price_min", float), get_num("price_max", float)
    if price_min is not None:
        listings = [l for l in listings if (suma_miesieczna(l) or 0) >= price_min]
    if price_max is not None:
        listings = [l for l in listings if (suma_miesieczna(l) or 0) <= price_max]

    m2_min, m2_max = get_num("m2_price_min", float), get_num("m2_price_max", float)
    if m2_min is not None:
        listings = [l for l in listings if (cena_za_m2(l) or 0) >= m2_min]
    if m2_max is not None:
        listings = [l for l in listings if (cena_za_m2(l) or 0) <= m2_max]

    entry_min, entry_max = get_num("entry_price_min", float), get_num("entry_price_max", float)
    if entry_min is not None:
        listings = [l for l in listings if (suma_wejscia(l) or 0) >= entry_min]
    if entry_max is not None:
        listings = [l for l in listings if (suma_wejscia(l) or 0) <= entry_max]

    rooms_min = get_num("rooms_min", int)
    if rooms_min is not None:
        listings = [l for l in listings if (l.rooms or 0) >= rooms_min]
    area_min = get_num("area_min", float)
    if area_min is not None:
        listings = [l for l in listings if (l.area_m2 or 0) >= area_min]

    ocena_wygladu_min = get_num("ocena_wygladu_min", int)
    if ocena_wygladu_min is not None:
        listings = [l for l in listings if (l.ocena_wygladu or 0) >= ocena_wygladu_min]
    ocena_glosnosci_min = get_num("ocena_glosnosci_otoczenia_min", int)
    if ocena_glosnosci_min is not None:
        listings = [l for l in listings if (l.ocena_glosnosci_otoczenia or 0) >= ocena_glosnosci_min]

    if get("ranked_only") == "true":
        listings = [l for l in listings if l.rank is not None]

    tags_text = get("tags")
    if tags_text:
        wanted = [t.strip() for t in tags_text.split(",") if t.strip()]
        listings = [l for l in listings if all(t in l.tags for t in wanted)]

    available_by = get("available_by")
    if available_by:
        from datetime import date
        try:
            cutoff = date.fromisoformat(available_by)
        except ValueError:
            cutoff = None
        if cutoff is not None:
            listings = [l for l in listings if l.available_from is None or l.available_from <= cutoff]

    pets = get("pets_allowed")
    if pets == "true":
        listings = [l for l in listings if l.pets_allowed is True]
    elif pets == "false":
        listings = [l for l in listings if l.pets_allowed is False]

    parking = get("parking")
    if parking == "true":
        listings = [l for l in listings if money_presence(l.parking) is True]
    elif parking == "false":
        listings = [l for l in listings if money_presence(l.parking) is False]

    piwnica = get("piwnica")
    if piwnica == "true":
        listings = [l for l in listings if money_presence(l.piwnica) is True]
    elif piwnica == "false":
        listings = [l for l in listings if money_presence(l.piwnica) is False]

    q = get("q")
    if q:
        q_lower = q.lower()
        listings = [l for l in listings if q_lower in (l.title or "").lower()
                    or q_lower in (l.address or "").lower() or q_lower in (l.notatki or "").lower()]

    sort = get("sort") or "-created_at"
    reverse = sort.startswith("-")
    sort_key = sort.lstrip("-")

    def key_fn(l: Listing):
        if sort_key == "suma_miesieczna":
            v = suma_miesieczna(l)
        elif sort_key == "cena_za_m2":
            v = cena_za_m2(l)
        elif sort_key == "rank":
            v = l.rank
        else:
            v = getattr(l, sort_key, None)
        return (v is None, v if v is not None else 0)

    listings.sort(key=key_fn, reverse=reverse)
    return listings
