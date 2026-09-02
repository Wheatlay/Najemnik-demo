"""
Cost calculation (SPEC §6-7). Always computed on read, never stored, never
directly editable.
"""
import statistics

from core.domain.money_field import MISSING_INFO
from core.domain.money_field import amount as money_amount

# MISSING_INFO is defined in money_field (a dependency-free leaf) and
# re-exported here, because field_specs, breakdown and callprep_bank have
# always imported it from costs - and `heating`, an enum rather than a money
# field, still uses it as its "the ad never said" value.
__all__ = ["MISSING_INFO"]


def is_missing_info(text: str) -> bool:
    """Whether `heating` holds no real answer.

    Exact match now, not the substring scan this used to do: the six money
    fields that needed loose matching are structured, so a user note that
    merely contains the words "brak informacji" no longer reads as an absent
    answer. The retired "brak wzmianki"/"nie wspomniano" phrasings went with
    it - nothing has written them since the marker was unified, and any row
    still holding one is re-enriched by this branch's migration anyway.
    """
    return not text or text.strip().lower() == MISSING_INFO


def _extra_monthly(listing) -> tuple[int | None, bool]:
    """Extra monthly cost beyond rent_owner/czynsz_admin/parking, and whether
    it includes an assumed (not ad-stated) component. `other_costs`, when
    set, is a manual override of the AI-derived cost_breakdown - the user's
    correction always wins and is never flagged as an estimate. Falls back
    to the pre-breakdown formula (other_costs alone) for listings that
    haven't been through the new pipeline yet."""
    other_costs = getattr(listing, "other_costs", None)
    if other_costs is not None:
        return other_costs, False
    breakdown = getattr(listing, "cost_breakdown", None)
    if breakdown:
        from core.domain.breakdown import extra_monthly_costs
        from core.domain.settings import get_settings
        s = get_settings(listing.user_id)
        utility_costs = {
            "woda": s.woda_cost, "ogrzewanie": s.ogrzewanie_cost, "smieci": s.smieci_cost,
            "prad": s.prad_cost, "gaz": s.gaz_cost, "internet": s.internet_cost,
        }
        heating_costs = {
            "gazowe": s.heating_gazowe_cost, "elektryczne": s.heating_elektryczne_cost,
            "kominkowe": s.heating_kominkowe_cost, "inne": s.heating_inne_cost,
        }
        return extra_monthly_costs(breakdown, heating=listing.heating,
                                    utility_costs=utility_costs, heating_costs=heating_costs)
    return None, False


def suma_miesieczna(listing) -> int | None:
    extra, _ = _extra_monthly(listing)
    parts = [listing.rent_owner, listing.czynsz_admin, extra,
             money_amount(listing.parking), money_amount(listing.piwnica)]
    present = [p for p in parts if p is not None]
    if not present:
        return None
    return round(sum(present))


def suma_miesieczna_estimated(listing) -> bool:
    """True when suma_miesieczna includes an assumed (not ad-stated) utility
    cost - lets the UI show the total as approximate (e.g. a "~" prefix)."""
    _, estimated = _extra_monthly(listing)
    return estimated


def cena_za_m2(listing) -> int | None:
    total = suma_miesieczna(listing)
    if total is None or not listing.area_m2:
        return None
    return round(total / listing.area_m2)


def suma_wejscia(listing) -> int | None:
    parts = [money_amount(listing.deposit), money_amount(listing.notariusz),
             money_amount(listing.prowizja), money_amount(listing.oc)]
    present = [p for p in parts if p is not None]
    if not present:
        return None
    return round(sum(present))


def _active_market_listings(user_id: str) -> list:
    """The set every cheap/typical/expensive signal is measured against:
    this user's active, non-deleted, non-rejected listings (deliberately
    the whole tracked market within their account, not the current filter).
    Loaded once per request by CostContext instead of re-queried per color
    call."""
    from sqlmodel import Session, select

    from core.infra.db import get_engine
    from core.domain.queries import NOT_REJECTED, STILL_LISTED
    from core.models import Listing
    with Session(get_engine()) as session:
        # Both: a median you're being compared against shouldn't include ads
        # that no longer exist, nor ones you've already turned down.
        stmt = select(Listing).where(
            Listing.user_id == user_id, *STILL_LISTED, *NOT_REJECTED,
        )
        return list(session.exec(stmt).all())


def _ratio_bucket(value: int | None, totals: list[int]) -> str:
    """Where `value` sits relative to the median of `totals` - shared by
    every cheap/typical/expensive color signal in the app (drawer badges,
    gallery, map markers) so they all agree on the same thresholds."""
    if value is None or len(totals) < 3:
        return "cheap"
    median = statistics.median(totals)
    if median <= 0:
        return "cheap"
    ratio = value / median
    if ratio <= 0.92:
        return "cheap"
    if ratio <= 1.08:
        return "typical"
    return "expensive"


# .money-cheap/-typical/-expensive are defined once in static/css/brand.css -
# change the colors there, not here.
_RATIO_CLASS = {"cheap": "money-cheap", "typical": "money-typical", "expensive": "money-expensive"}

# CSS variable names (not colors) for the same buckets, for contexts that
# can't use a class (MapLibre marker colors, set via an inline CSS custom
# property) - map.js resolves these against brand.css's --color-ratio-*
# tokens at render time, so Python never carries a hex value.
_RATIO_VAR = {
    "cheap": "--color-ratio-cheap",
    "typical": "--color-ratio-typical",
    "expensive": "--color-ratio-expensive",
}


def _ratio_color_class(value: int | None, totals: list[int]) -> str:
    """Green/amber/red text color based on `value`'s position relative to
    the median of `totals` - lets the drawer/gallery show at a glance
    whether a listing's cost is cheap, typical, or expensive vs. the rest."""
    return _RATIO_CLASS[_ratio_bucket(value, totals)]


def suma_roczna(listing) -> int | None:
    """Monthly cost * 12 plus one-off entry cost - the map's "yearly cost"
    display mode. None only when neither component has any data at all."""
    suma, wejscie = suma_miesieczna(listing), suma_wejscia(listing)
    if suma is None and wejscie is None:
        return None
    return (suma or 0) * 12 + (wejscie or 0)


class CostContext:
    """Precomputes the market-wide totals that every cheap/typical/expensive
    color signal needs, once, so a full gallery/map render loads the active
    set a single time instead of re-querying it per card/marker (the old
    per-call _active_listings() made rendering O(N^2) in DB round-trips).

    Built in the router for list views, or in routers.pages.listing_ctx for
    single-listing re-renders, and passed into the template context as
    `cost_ctx`; templates call cost_ctx.suma_miesieczna_color(l) instead of
    reaching back into the database mid-render."""

    def __init__(self, market: list):
        self._suma = [v for l in market if (v := suma_miesieczna(l)) is not None]
        self._wejscie = [v for l in market if (v := suma_wejscia(l)) is not None]
        self._roczna = [v for l in market if (v := suma_roczna(l)) is not None]

    def suma_miesieczna_color(self, listing) -> str:
        return _ratio_color_class(suma_miesieczna(listing), self._suma)

    def suma_wejscia_color(self, listing) -> str:
        return _ratio_color_class(suma_wejscia(listing), self._wejscie)

    def suma_miesieczna_marker_var(self, listing) -> str:
        return _RATIO_VAR[_ratio_bucket(suma_miesieczna(listing), self._suma)]

    def suma_wejscia_marker_var(self, listing) -> str:
        return _RATIO_VAR[_ratio_bucket(suma_wejscia(listing), self._wejscie)]

    def suma_roczna_marker_var(self, listing) -> str:
        return _RATIO_VAR[_ratio_bucket(suma_roczna(listing), self._roczna)]


def cost_context(user_id: str) -> CostContext:
    """Loads the active-market set once and returns a CostContext over it."""
    return CostContext(_active_market_listings(user_id))
