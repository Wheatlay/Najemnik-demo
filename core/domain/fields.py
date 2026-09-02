"""
The source of truth for every field's existence and behavior.

The detail drawer, gallery card, and compare table render themselves from
FIELDS (via fields_in / groups_in / compare_columns) - add a field here and
those views pick it up. Two views are deliberately NOT generated from the
registry and hardcode their own field lists: the filter sidebar
(templates/partials/_filter_sidebar.html, whose range/checkbox/grouped inputs
don't map to a uniform per-field loop) and the map points/popups
(routers/pages.py). Of the flags below, `show_in`, `sortable` (sort dropdown),
`computed`, `source`, `options` and the bool_* fields are consumed by code;
`filterable` and `smart_kind` are declarative metadata that document intent
but are not currently wired to a generator - don't assume setting them makes
a filter or a cost appear on their own.
"""
from dataclasses import dataclass, field
from typing import Literal

FieldType = Literal[
    "text", "textarea", "number", "date", "datetime",
    "select_status", "select_ocena", "select_bool", "rank", "tags",
    # {status, amount, note} JSON - core/domain/money_field.py owns the
    # schema, the plausible-amount clamps and the Polish wording.
    "smart_money",
    # A closed set of values, listed in FieldDef.options.
    "select_enum",
    "link",
]
ShowIn = Literal["detail", "gallery_card", "compare", "filter"]

# The closed set `heating` may hold. Single source of truth: the AI schema
# (core/pipeline/enrich/field_specs.py) and the drawer's <select> both read
# it from here, and core/infra/config.ASSUMED_HEATING_COST_BY_TYPE plus the
# Settings.heating_*_cost columns are keyed by these same words.
HEATING_TYPES = ("miejskie", "gazowe", "elektryczne", "kominkowe", "inne")

# Where a field's value comes from - drives which pipeline (if any) is
# allowed to write it, and documents the trust level of what's on screen:
#   scraped     - filled only by the site parsers (core/pipeline/scrape/*), never AI
#   ai_verify   - scraping usually fills it; AI cross-checks it against the
#                 ad text (verify-then-extract-on-mismatch, core/pipeline/enrich/pipeline.py)
#   ai_extract  - AI-only; scraping never provides a value for this field
#   manual      - user-entered only, nothing automated ever writes it
#   derived     - the value comes from *other* fields, so no pipeline
#                 writes it directly. Not the same as FieldDef.computed:
#                 that says "recalculated on read, never stored", and the
#                 two genuinely differ. fees_note is derived (built from
#                 cost_breakdown) but *is* stored, so it's
#                 source="derived", computed=False. Naming them alike
#                 previously made that read like a mistake.
FieldSource = Literal["scraped", "ai_verify", "ai_extract", "manual", "derived"]


@dataclass
class FieldDef:
    key: str
    label: str
    type: FieldType
    group: str
    editable: bool = True
    computed: bool = False
    # Which total a money field feeds: suma_miesieczna or suma_wejscia.
    # The old `smart` bool alongside this said the same thing twice (it was
    # set on exactly the fields with a smart_kind), so it's gone - the type
    # is what marks a money field now.
    smart_kind: Literal["monthly", "one_time"] | None = None
    # Allowed values for a select_enum field.
    options: tuple[str, ...] = ()
    show_in: frozenset = field(default_factory=lambda: frozenset({"detail"}))
    filterable: bool = False
    sortable: bool = False
    source: FieldSource = "manual"
    # Custom (true_label, false_label) for select_bool fields whose two
    # known states aren't literally "tak"/"nie" (e.g. posrednik is
    # "pośrednik"/"prywatnie") - stored value stays a plain bool either way.
    bool_labels: tuple[str, str] | None = None
    # False for a select_bool field whose model column is a plain bool, not
    # Optional[bool] - hides the "brak informacji" option entirely, since
    # there's no third state to represent (e.g. pewnosc_lokalizacji is a
    # confirmed-or-not flag, always False until the user actively checks).
    nullable: bool = True
    # (true_bucket, false_bucket) using the same "pay"/"free" cost-direction
    # buckets as smart fields (red/green) - lets a select_bool convey which
    # answer is favorable (e.g. pets_allowed=tak is good news) instead of
    # every select_bool defaulting to the same neutral accent color. None
    # keeps the neutral accent look for fields where neither answer is "better".
    bool_colors: tuple[str, str] | None = None


FIELDS: list[FieldDef] = [
    # --- Lokalizacja ---
    FieldDef("title", "Nazwa", "text", "Lokalizacja", source="scraped",
             show_in=frozenset({"detail", "gallery_card", "filter"})),
    FieldDef("address", "Adres", "text", "Lokalizacja", source="scraped", show_in=frozenset({"detail"})),
    FieldDef("city", "Miasto", "text", "Lokalizacja", source="scraped",
             show_in=frozenset({"detail", "filter"}), filterable=True),
    FieldDef("district", "Dzielnica", "text", "Lokalizacja", source="ai_extract",
             show_in=frozenset({"detail", "compare", "filter"}), filterable=True),
    FieldDef("commute_time_car", "Czas dojazdu (auto)", "text", "Lokalizacja", source="manual",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("commute_time_public", "Czas dojazdu (komunikacja)", "text", "Lokalizacja", source="manual",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("pewnosc_lokalizacji", "Pewność lokalizacji", "select_bool", "Lokalizacja", source="manual",
             show_in=frozenset({"detail", "compare"}), bool_colors=("free", "pay"), nullable=False),

    # --- Mieszkanie ---
    FieldDef("area_m2", "Powierzchnia", "number", "Mieszkanie", source="scraped",
             show_in=frozenset({"detail", "gallery_card", "compare", "filter"}),
             filterable=True, sortable=True),
    FieldDef("rooms", "Pokoje", "number", "Mieszkanie", source="scraped",
             show_in=frozenset({"detail", "gallery_card", "compare", "filter"}),
             filterable=True, sortable=True),
    FieldDef("floor", "Piętro", "number", "Mieszkanie", source="scraped", show_in=frozenset({"detail", "compare"})),
    FieldDef("floor_total", "Piętra w budynku", "number", "Mieszkanie", source="scraped",
             show_in=frozenset({"detail"})),
    FieldDef("available_from", "Dostępne od", "date", "Mieszkanie", source="ai_extract",
             show_in=frozenset({"detail", "compare", "filter"}), filterable=True),
    FieldDef("pets_allowed", "Zwierzęta dozwolone", "select_bool", "Mieszkanie", source="ai_extract",
             show_in=frozenset({"detail", "compare", "filter"}), filterable=True, bool_colors=("free", "pay")),

    # --- Koszt miesięczny ---
    FieldDef("rent_owner", "Odstępne", "number", "Koszt miesięczny", source="ai_verify",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("czynsz_admin", "Czynsz", "number", "Koszt miesięczny", source="ai_verify",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("other_costs", "Opłaty dodatkowe (ręczna korekta)", "number", "Koszt miesięczny", source="manual",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("fees_note", "Co obejmują opłaty?", "textarea", "Koszt miesięczny", source="derived",
             editable=False, show_in=frozenset({"detail"})),
    FieldDef("heating", "Ogrzewanie (rodzaj)", "select_enum", "Koszt miesięczny", source="ai_extract",
             options=HEATING_TYPES,
             show_in=frozenset({"detail", "compare"})),
    # bool_colors=("free", "pay"): same convention as pets_allowed just
    # above - having a spot is good news (green), not having one is the
    # worse outcome (red). The four Koszt wejścia fields below are the
    # opposite: they're obligations, so tak (you're on the hook) stays red,
    # which is bucket()'s default and needs no override.
    FieldDef("parking", "Garaż / miejsce parkingowe", "smart_money", "Koszt miesięczny", source="ai_extract",
             smart_kind="monthly", show_in=frozenset({"detail", "compare"}), bool_colors=("free", "pay")),
    FieldDef("piwnica", "Piwnica / komórka lokatorska", "smart_money", "Koszt miesięczny", source="ai_extract",
             smart_kind="monthly", show_in=frozenset({"detail", "compare"}), bool_colors=("free", "pay")),
    FieldDef("suma_miesieczna", "Suma miesięczna", "number", "Koszt miesięczny", source="derived",
             editable=False, computed=True,
             show_in=frozenset({"detail", "gallery_card", "compare", "filter"}),
             filterable=True, sortable=True),
    FieldDef("cena_za_m2", "Cena za m²", "number", "Koszt miesięczny", source="derived",
             editable=False, computed=True,
             show_in=frozenset({"detail", "gallery_card", "compare", "filter"}),
             filterable=True, sortable=True),

    # --- Koszt wejścia ---
    FieldDef("deposit", "Kaucja", "smart_money", "Koszt wejścia", source="ai_verify",
             smart_kind="one_time",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("notariusz", "Notariusz", "smart_money", "Koszt wejścia", source="ai_extract",
             smart_kind="one_time",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("prowizja", "Prowizja", "smart_money", "Koszt wejścia", source="ai_extract",
             smart_kind="one_time",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("oc", "Ubezpieczenie OC", "smart_money", "Koszt wejścia", source="ai_extract",
             smart_kind="one_time",
             show_in=frozenset({"detail", "compare"})),
    FieldDef("suma_wejscia", "Suma wejścia", "number", "Koszt wejścia", source="derived",
             editable=False, computed=True, show_in=frozenset({"detail", "compare"})),

    # --- Kontakt ---
    FieldDef("phone", "Nr telefonu", "text", "Kontakt", source="scraped", show_in=frozenset({"detail", "compare"})),
    FieldDef("posrednik", "Pośrednik / Prywatnie", "select_bool", "Kontakt", source="ai_extract",
             show_in=frozenset({"detail", "compare"}), bool_labels=("pośrednik", "prywatnie"),
             bool_colors=("pay", "free")),
    FieldDef("url", "Ogłoszenie", "link", "Kontakt", source="scraped", editable=False,
             show_in=frozenset({"detail"})),

    # --- Status i ocena ---
    FieldDef("status", "Status", "select_status", "Status i ocena", source="manual",
             show_in=frozenset({"detail", "gallery_card", "compare", "filter"}),
             filterable=True, sortable=True),
    FieldDef("termin_ogledzin", "Termin oględzin", "datetime", "Status i ocena", source="manual",
             show_in=frozenset({"detail"})),
    FieldDef("ocena_wygladu", "Ocena wyglądu", "select_ocena", "Status i ocena", source="manual",
             show_in=frozenset({"detail", "compare", "filter"}), filterable=True, sortable=True),
    FieldDef("ocena_glosnosci_otoczenia", "Ocena głośności otoczenia", "select_ocena", "Status i ocena",
             source="manual",
             show_in=frozenset({"detail", "compare", "filter"}), filterable=True, sortable=True),
    FieldDef("rank", "Ranking", "rank", "Status i ocena", source="manual",
             show_in=frozenset({"detail", "gallery_card", "compare", "filter"}), filterable=True, sortable=True),
    # --- Notatki ---
    FieldDef("tags", "Tagi", "tags", "Notatki", source="manual",
             show_in=frozenset({"detail", "compare", "filter"}), filterable=True),
    FieldDef("notatki", "Notatki", "textarea", "Notatki", source="manual",
             show_in=frozenset({"detail", "filter"}), filterable=True),

    # --- AI ---
    FieldDef("ai_comment", "Analiza AI (porównawcza)", "textarea", "AI", source="derived",
             editable=False, computed=True, show_in=frozenset({"compare"})),
]

FIELDS_BY_KEY: dict[str, FieldDef] = {f.key: f for f in FIELDS}


def fields_in(show_in: str) -> list[FieldDef]:
    return [f for f in FIELDS if show_in in f.show_in]


def filterable_fields() -> list[FieldDef]:
    return [f for f in FIELDS if f.filterable]


def sortable_fields() -> list[FieldDef]:
    """Ordered with the "podstawowe" compare-column preset's priority first -
    that list is already the curated "most commonly checked" set, so the sort
    dropdown surfaces the same fields up top instead of raw declaration
    order. Sortable fields outside that preset (the two star ratings) fall
    through to the end, in their original relative order."""
    priority = {key: i for i, key in enumerate(COMPARE_PRESETS["podstawowe"])}
    return sorted((f for f in FIELDS if f.sortable), key=lambda f: priority.get(f.key, len(priority)))


def groups_in(show_in: str) -> list[tuple[str, list[FieldDef]]]:
    """Fields matching show_in, grouped by `group`, preserving declaration order."""
    groups: dict[str, list[FieldDef]] = {}
    for f in fields_in(show_in):
        groups.setdefault(f.group, []).append(f)
    return list(groups.items())


def money_fields() -> list[FieldDef]:
    """The six {status, amount, note} fields, in money_field.MONEY_FIELDS
    order. A function rather than a context key so any template can ask for
    them directly - the A/B trial partial is rendered both by its own page
    and by the shared PATCH route, and only one of those two knew to pass a
    list."""
    from core.domain.money_field import MONEY_FIELDS
    order = {k: i for i, k in enumerate(MONEY_FIELDS)}
    return sorted((f for f in FIELDS if f.type == "smart_money"), key=lambda f: order[f.key])


def is_editable(key: str) -> bool:
    f = FIELDS_BY_KEY.get(key)
    return bool(f and f.editable and not f.computed)


BETTER_DIRECTION: dict[str, str] = {
    "rent_owner": "min", "czynsz_admin": "min", "other_costs": "min",
    "suma_miesieczna": "min", "cena_za_m2": "min", "suma_wejscia": "min",
    "area_m2": "max", "rooms": "max",
    "ocena_wygladu": "max", "ocena_glosnosci_otoczenia": "max",
}


def compare_columns() -> list[tuple[str, list[FieldDef]]]:
    """Compare-table column groups mirror the detail drawer's own sections
    (SPEC: same categories the user already knows from the sidebar), rather
    than a separate coarse bucketing - a "Dane" catch-all for everything
    non-rating/non-status crammed 18 columns into one indistinguishable group."""
    groups: dict[str, list[FieldDef]] = {}
    for f in fields_in("compare"):
        groups.setdefault(f.group, []).append(f)
    return list(groups.items())


def compare_field_keys() -> list[str]:
    return [f.key for f in fields_in("compare")]


def compare_group_keys() -> dict[str, list[str]]:
    """Group -> ordered field keys, for the compare table's group-header label:
    it must land on the first VISIBLE column of the group (client-side, since
    visibility is a per-user column toggle), not just the first one declared."""
    return {group: [f.key for f in group_fields] for group, group_fields in compare_columns()}


# Named column-visibility presets for the compare table's "Kolumny" picker -
# lets the user shrink a 25-column table down to just what they care about
# without losing access to the rest (SPEC UX ask: readable without a wide
# screen, without deleting functionality).
COMPARE_PRESETS: dict[str, list[str]] = {
    "podstawowe": ["district", "area_m2", "rooms", "floor", "suma_miesieczna",
                   "cena_za_m2", "status", "rank"],
    "finanse": ["rent_owner", "czynsz_admin", "other_costs", "heating", "parking", "piwnica",
                "suma_miesieczna", "cena_za_m2", "deposit", "notariusz", "prowizja", "oc",
                "suma_wejscia"],
    "ocena_status": ["ocena_wygladu", "ocena_glosnosci_otoczenia", "rank", "status",
                      "tags"],
}


# Compare-table column widths (px) - starting sizes only. The table's
# <colgroup> renders these as inline `width`, which the compare view's
# drag-resize handles (static/js/compare.js) then read/mutate directly and
# persist per-column to localStorage, so these are just sane defaults, not
# the final word - a plain "one width for everything" table reads as a wall
# of empty/cramped cells either way, but users can always drag to taste.
_NARROW = 64        # short numbers: piętro, ranking
_MEDIUM_NUM = 90     # money, powierzchnia, pokoje, cena/m2
_RATING = 120        # star ratings
_DATE = 120
_STATUS = 170
_WIDE = 180          # free text: dzielnica, telefon
_MEDIUM_TEXT = 190   # short smart-field notes: kaucja, notariusz, prowizja
_TEXTAREA = 260      # longer free text: ogrzewanie, uwagi, AI
_AI_COMMENT = 360    # comparative AI analysis - long multi-line pros/cons text

_COMPARE_COL_WIDTH: dict[str, int] = {
    "title": _WIDE,
    "floor": _NARROW, "rank": _NARROW,
    "rooms": _MEDIUM_NUM, "area_m2": _MEDIUM_NUM, "rent_owner": _MEDIUM_NUM,
    "czynsz_admin": _MEDIUM_NUM, "other_costs": _MEDIUM_NUM,
    "suma_miesieczna": _MEDIUM_NUM, "cena_za_m2": _MEDIUM_NUM, "suma_wejscia": _MEDIUM_NUM,
    "ocena_wygladu": _RATING, "ocena_glosnosci_otoczenia": _RATING,
    "available_from": _DATE,
    "pets_allowed": _NARROW,
    "status": _STATUS,
    "district": _WIDE, "phone": _WIDE, "posrednik": _WIDE,
    "notariusz": _MEDIUM_TEXT, "prowizja": _MEDIUM_TEXT, "oc": _MEDIUM_TEXT, "deposit": _MEDIUM_TEXT,
    "heating": _TEXTAREA, "parking": _TEXTAREA, "piwnica": _TEXTAREA,
    "tags": _TEXTAREA, "ai_comment": _AI_COMMENT,
}


def compare_col_width(key: str) -> int:
    return _COMPARE_COL_WIDTH.get(key, _WIDE)


# Closed vocabulary for amenity tags - the AI tagging prompt (core/pipeline/enrich/
# prompts/tags.py) may only select from this list, and anything it returns
# outside it is dropped in Python (core/pipeline/enrich/enrich.py:suggest_tags), so a
# hallucinated tag can never reach the database. Also used by the filter
# sidebar to render checkboxes instead of a free-text field.
TAG_VOCABULARY: list[str] = [
    "balkon", "taras", "ogródek", "winda", "klimatyzacja", "zmywarka",
    "nie umeblowane",
]
