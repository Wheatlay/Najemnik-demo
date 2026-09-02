"""
Renders a single field's current value for templates - display string for
read-only/computed fields, raw value for editable inputs. One place so
detail drawer, gallery card, and compare table format identically (SPEC §4).
"""
from core.domain import costs
from core.domain import money_field
from core.domain import normalize as norm
from core.domain.fields import FieldDef


def computed_value(listing, key: str):
    if key == "suma_miesieczna":
        return costs.suma_miesieczna(listing)
    if key == "cena_za_m2":
        return costs.cena_za_m2(listing)
    if key == "suma_wejscia":
        return costs.suma_wejscia(listing)
    if key == "ai_comment":
        return listing.ai_comment
    return getattr(listing, key, None)


def ai_provenance(listing, f: FieldDef) -> dict | None:
    """Whether to credit this field's value to the model, and the receipt.

    Returns {"quote": str|None} for a field the AI genuinely authored, else
    None (render no badge at all).

    Driven by `ai_evidence`, which the pipeline writes per row, rather than
    by FieldDef.source. `source` only describes where a field is *normally*
    filled from, so it gets `ai_verify` fields wrong in both directions: a
    scraped `deposit` of "4200" is the portal's and must not be badged, but
    a `deposit` the model filled because scraping found nothing reads
    "wymagana, kwota nie podana" - unmistakably the model's words - and must
    be. Only the per-row record distinguishes them.

    A field the user has edited is theirs from then on, badge and receipt
    both gone (`edited_fields`).

    `quote` is None when the model answered without a usable quote: we
    credit the AI but have no fragment to show.
    """
    if f.computed or f.source == "manual":
        return None
    if f.key in (listing.edited_fields or []):
        return None
    evidence = listing.ai_evidence or {}
    if f.key not in evidence:
        return None
    return {"quote": evidence[f.key]}


def other_costs_hint(listing) -> str:
    """When `other_costs` hasn't been manually set, suma_miesieczna quietly
    falls back to the AI cost_breakdown's extra-utilities total (core.domain.costs.
    _extra_monthly) - without this, the field just renders blank and the
    user has no way to see where that money in the total came from short of
    reading the full fees_note. Surfaced as an input placeholder (not a
    stored value - typing a number still overrides the breakdown)."""
    if listing.other_costs is not None or not getattr(listing, "cost_breakdown", None):
        return ""
    from core.domain.breakdown import extra_monthly_costs
    extra, estimated = extra_monthly_costs(listing.cost_breakdown, heating=listing.heating)
    if not extra:
        return ""
    return f"{'~' if estimated else ''}{extra} zł (z analizy AI)"


def top_floor_heat_note(listing) -> str:
    """Warns that a top-floor unit (floor == floor_total) can run hot in
    summer - surfaced right under Piętro since that's the one place the
    two numbers being equal is easy to miss otherwise. Mentions the
    listing's own klimatyzacja tag when present, since that's the one
    mitigation worth calling out in the same breath rather than leaving
    the warning sitting there unqualified."""
    if listing.floor is None or listing.floor_total is None or listing.floor != listing.floor_total:
        return ""
    if "klimatyzacja" in listing.tags:
        return "Ostatnie piętro - może być gorąco latem, ale mieszkanie ma klimatyzację."
    return "Ostatnie piętro - może być gorąco latem."


def raw_value(listing, f: FieldDef):
    if f.computed:
        return computed_value(listing, f.key)
    if f.key == "available_from":
        return listing.available_from.isoformat() if listing.available_from else ""
    if f.key == "termin_ogledzin":
        return listing.termin_ogledzin.strftime("%Y-%m-%dT%H:%M") if listing.termin_ogledzin else ""
    if f.key == "status":
        return listing.status.value
    if f.key == "tags":
        return ", ".join(listing.tags)
    if f.type == "select_bool":
        value = getattr(listing, f.key, None)
        return "" if value is None else ("tak" if value else "nie")
    value = getattr(listing, f.key, "")
    return value if value is not None else ""


def is_field_missing(listing, f: FieldDef) -> bool:
    """Whether a cell should read as "the ad never said", for the compare
    table's amber italics. Kept here rather than assembled inline in Jinja,
    where it had grown into a three-clause expression reaching into two
    different modules' parsing helpers."""
    if f.type == "smart_money":
        return money_field.is_missing(getattr(listing, f.key, None))
    if f.type == "select_enum":
        return costs.is_missing_info(getattr(listing, f.key, "") or "")
    if f.type == "select_bool":
        return getattr(listing, f.key, None) is None
    return False


def display_value(listing, f: FieldDef) -> str:
    key = f.key
    if key == "suma_miesieczna":
        money = norm.format_money(costs.suma_miesieczna(listing))
        if money != "—" and costs.suma_miesieczna_estimated(listing):
            return "~ " + money
        return money
    if key == "cena_za_m2":
        v = costs.cena_za_m2(listing)
        return f"{v} zł/m²" if v is not None else "—"
    if key == "suma_wejscia":
        return norm.format_money(costs.suma_wejscia(listing))
    if key in ("rent_owner", "czynsz_admin", "other_costs"):
        return norm.format_money(getattr(listing, key))
    if key == "area_m2":
        return norm.format_area(listing.area_m2)
    if key == "rooms":
        return norm.format_rooms(listing.rooms)
    if key == "floor":
        return norm.format_floor(listing.floor, listing.floor_total)
    if key == "phone":
        return norm.format_phone(listing.phone)
    if key == "available_from":
        # available_from is None both before the AI ever looked at the ad
        # and after it confirmed "od zaraz" (or found no date at all) - only
        # the latter should read as "od zaraz"; pre-enrichment it's just
        # unknown, so use enriched_at to tell the two states apart.
        if listing.available_from is None and listing.enriched_at is None:
            return "—"
        return norm.format_available_from(listing.available_from)
    if key == "termin_ogledzin":
        return norm.format_termin_ogledzin(listing.termin_ogledzin)
    if key == "rank":
        return f"#{listing.rank}" if listing.rank is not None else "—"
    if key == "status":
        return listing.status.value
    if key == "tags":
        return ", ".join(listing.tags) if listing.tags else "—"
    if f.type == "select_bool":
        value = getattr(listing, key, None)
        if value is None:
            return "—"
        true_label, false_label = f.bool_labels or ("tak", "nie")
        return true_label if value else false_label
    if key in money_field.MONEY_FIELDS:
        # The six {status, amount, note} fields. money_field owns the wording
        # so the drawer, the compare table and the gallery can't drift apart -
        # and so the Polish stays identical to when these were stored as
        # sentences. heating is deliberately not here: it's a plain enum and
        # falls through to the generic branch below, same as before.
        return money_field.display_string(key, getattr(listing, key))
    if key == "url":
        return listing.url
    value = getattr(listing, key, None)
    return str(value) if value not in (None, "") else "—"


STATUS_VALUES = ["Nowe", "Przejrzane", "Umówione na oględziny", "Obejrzane", "Potencjalne", "Odrzucone"]

# Short ASCII slug per status, used to build both the CSS class name (pill)
# and the CSS variable name (marker) below - the single place that ties a
# status to "which color", so recoloring the app means editing
# static/css/brand.css only, never this file or a template.
STATUS_SLUGS = {
    "Nowe": "nowe",
    "Przejrzane": "przejrzane",
    "Umówione na oględziny": "umowione",
    "Obejrzane": "obejrzane",
    "Potencjalne": "potencjalne",
    "Odrzucone": "odrzucone",
}

# One .status-pill-<slug> class per status (defined in brand.css) - kept as a
# lookup table rather than an f-string in templates so a typo'd status value
# fails loudly (KeyError) instead of silently emitting an unstyled pill.
STATUS_PILL_CLASSES = {status: f"status-pill-{slug}" for status, slug in STATUS_SLUGS.items()}

# CSS *variable names* (not colors) - map markers/legend dots need a solid
# color in inline style, so map.js resolves these at runtime via
# getComputedStyle against brand.css's --color-status-* tokens instead of
# Python ever knowing a hex value.
STATUS_MARKER_VARS = {status: f"--color-status-{slug}" for status, slug in STATUS_SLUGS.items()}

# Compare-table group-header colors, keyed by the same `group` string used
# for the detail drawer's collapsible sections (SPEC: compare should mirror
# the drawer's own categories, not a separate 3-bucket scheme) - distinct
# colors per group so scanning a wide table doesn't read as one undifferentiated
# accent band. Classes defined in brand.css; add a slug here and its
# .compare-group-<slug> counterpart there to give a new group its own color.
COMPARE_GROUP_SLUGS: dict[str, str] = {
    "Lokalizacja": "lokalizacja",
    "Mieszkanie": "mieszkanie",
    "Koszt miesięczny": "koszt-miesieczny",
    "Koszt wejścia": "koszt-wejscia",
    "Kontakt": "kontakt",
    "Status i ocena": "status",
    "Notatki": "notatki",
    "AI": "ai",
}
COMPARE_GROUP_COLORS: dict[str, str] = {
    group: f"compare-group-{slug}" for group, slug in COMPARE_GROUP_SLUGS.items()
}
COMPARE_GROUP_COLOR_DEFAULT = "compare-group-default"
