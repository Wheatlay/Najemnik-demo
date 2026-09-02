"""
The six "does this cost money, and how much" fields: deposit, parking,
piwnica, notariusz, prowizja, oc.

Stored as JSON, one column each:

    {"status": "tak" | "nie" | "brak_informacji",
     "amount": int | None,
     "note": str | None}

A column value of None means the field was never filled, and reads the same
as "brak_informacji". "Present but no amount given" is `status="tak"` with no
amount - there is deliberately no fourth status for it. `note` carries the
prose the old free-text format was good at ("50% czynszu", "od właściciela")
and never takes part in arithmetic.

These used to be free-text columns holding Polish sentences, which every
consumer then had to parse back with regexes and a `startswith("brak")`
prefix check - so field semantics lived in Polish grammar, and the five
gendered label variants existed only because the label *was* the storage.
The model already answers with {status, kwota}; that structure is now kept
instead of being flattened and re-derived. Same shape `cost_breakdown`
already uses for utilities.

The Polish labels survive as a *rendering* concern (`display_string`), so
what the user sees is unchanged - and `display_string` reproduces the old
strings exactly, which is what lets the benchmark keep scoring against a
gold set recorded in the previous format.
"""
import re

from core.domain.normalize import format_money

# Canonical "the ad never mentioned this at all" marker. Defined here rather
# than in costs.py so this module stays a leaf and costs.py can import it -
# costs.py re-exports it, since field_specs and breakdown (heating, which is
# an enum rather than a money field) have always imported it from there.
MISSING_INFO = "brak informacji"

MONEY_FIELDS = ("deposit", "parking", "piwnica", "notariusz", "prowizja", "oc")

STATUS_YES = "tak"
STATUS_NO = "nie"
STATUS_UNKNOWN = "brak_informacji"
STATUSES = (STATUS_YES, STATUS_NO, STATUS_UNKNOWN)

# Plausible ranges for each field's own amount, shared by the AI path
# (field_specs.TriStateMoney) and the user-edit path (listings_api._coerce)
# so a hand-typed value can't bypass a check the model is held to.
CLAMPS: dict[str, tuple[int, int]] = {
    "deposit": (1, 30000),
    "parking": (1, 1000),
    "piwnica": (1, 500),
    "notariusz": (1, 2000),
    "prowizja": (1, 10000),
    "oc": (1, 1000),
}

# (adjective for "it applies", label for "it doesn't"). Gendered per field
# because they're shown to a Polish speaker: kaucja is wymagana, parking is
# dostępne. All six read "<adjective>, kwota nie podana" when present without
# an amount, so only the adjective is stored.
_NO_AMOUNT_SUFFIX = ", kwota nie podana"
LABELS: dict[str, tuple[str, str]] = {
    "deposit": ("wymagana", "brak"),
    "parking": ("dostępne", "brak miejsca parkingowego"),
    "piwnica": ("dostępna", "brak piwnicy/komórki lokatorskiej"),
    "notariusz": ("wymagany (najem okazjonalny)", "brak wymogu"),
    "prowizja": ("wymagana", "brak"),
    "oc": ("wymagane", "brak wymogu"),
}

_MAX_NOTE_LEN = 200


def present_label(key: str) -> str:
    """"wymagana, kwota nie podana" and friends - the select's "yes" option."""
    return LABELS[key][0] + _NO_AMOUNT_SUFFIX


def absent_label(key: str) -> str:
    return LABELS[key][1]


# Whole zł only, optionally spaced/dotted as thousands and optionally
# suffixed - "4200", "4 200", "4.200 zł". Nothing else.
_AMOUNT_RE = re.compile(r"^\s*(\d[\d  .]*)\s*(?:zł|zl|pln)?\s*$", re.IGNORECASE)


def _strict_amount(value) -> int | None:
    """A number, or nothing - deliberately NOT normalize.to_int().

    to_int is a lenient "find the first number in this text" parser, which is
    right for scraped ad copy ("czynsz 2 100 zł miesięcznie") and badly wrong
    for something a user typed into an amount box: it turned "50% czynszu"
    into 50 zł and quietly added it to the totals, and "-5" into 5. Here an
    input either *is* an amount or isn't one.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else None
    if not isinstance(value, str):
        return None
    m = _AMOUNT_RE.match(value)
    if not m:
        return None
    digits = re.sub(r"[  .]", "", m.group(1))
    return int(digits) if digits.isdigit() else None


def to_amount(text) -> int | None:
    """Public entry point for `_strict_amount`, for callers that need to
    classify a piece of typed text as "an amount" or "not" before deciding
    what to do with it - see variant F's combined kwota/notatka field in
    routers/listings_api.py."""
    return _strict_amount(text)


def validate(key: str, raw) -> dict | None:
    """Clamps arbitrary input - an AI answer or a submitted form - to the
    canonical shape, in the same spirit as breakdown.validate_breakdown:
    collapse to a weaker claim rather than store something unchecked.

    An unrecognised status becomes "brak_informacji". An amount outside the
    field's plausible range is dropped while the status stands, because
    "there is a deposit" survives "…of 900000 zł" being nonsense. An amount
    on a "nie"/"brak_informacji" answer is contradictory and dropped too.
    """
    if not isinstance(raw, dict):
        return None

    status = raw.get("status")
    if status not in STATUSES:
        status = STATUS_UNKNOWN

    out: dict = {"status": status}

    if status == STATUS_YES:
        amount = _strict_amount(raw.get("amount"))
        low, high = CLAMPS.get(key, (1, 100000))
        if amount is not None and low <= amount <= high:
            out["amount"] = amount

    note = raw.get("note")
    if isinstance(note, str) and note.strip():
        out["note"] = note.strip()[:_MAX_NOTE_LEN]

    return out


# --- reads -----------------------------------------------------------------

def amount(field) -> int | None:
    """The value that counts toward a total, or None. Replaces smart_value()'s
    "is this string just a number" regex."""
    if not isinstance(field, dict):
        return None
    return field.get("amount")


def presence(field) -> bool | None:
    """True the ad confirms it applies, False it confirms it doesn't, None it
    never said. Replaces smart_presence(), which inferred this from whether
    the stored sentence began with "brak"."""
    if not isinstance(field, dict):
        return None
    status = field.get("status")
    if status == STATUS_YES:
        return True
    if status == STATUS_NO:
        return False
    return None


def is_missing(field) -> bool:
    """Never filled, or the ad genuinely didn't mention it - as opposed to a
    confirmed "no" (prowizja "brak"), which is real information."""
    return presence(field) is None


def bucket(field, colors: tuple[str, str] | None = None) -> str:
    """Red/green/amber cue for the drawer: "unknown" when the ad never said,
    otherwise whichever of `colors` = (tak_bucket, nie_bucket) applies.

    Defaults to ("pay", "free") - tak costs you, nie doesn't - which is
    right for the four obligation fields (deposit, notariusz, prowizja, oc)
    but backwards for the two amenity fields (parking, piwnica): HAVING a
    parking spot is good news, the same way pets_allowed=tak is. Callers
    pass FieldDef.bool_colors (the identical (true_bucket, false_bucket)
    tuple select_bool fields already use - reused rather than duplicated,
    since it's the same question: "which of the two answers is favourable")
    so parking/piwnica render tak as green instead of every field defaulting
    to the same tak=red reading regardless of what tak actually means.
    """
    p = presence(field)
    if p is None:
        return "unknown"
    tak_bucket, nie_bucket = colors or ("pay", "free")
    return tak_bucket if p else nie_bucket


# --- rendering -------------------------------------------------------------

def display_string(key: str, field) -> str:
    """What the user reads. Reproduces the strings this field used to *store*,
    so on-screen wording, tour step titles and the help page all stay true.

    A note replaces the "kwota nie podana" tail when there's no amount
    ("wymagana, 50% czynszu"), because a note usually IS the missing amount
    expressed another way; alongside an amount or a "nie" it's parenthetical.
    """
    if not isinstance(field, dict):
        return MISSING_INFO

    status = field.get("status")
    note = field.get("note")
    value = field.get("amount")

    if status == STATUS_YES:
        if value is not None:
            return f"{format_money(value)} ({note})" if note else format_money(value)
        if note:
            return f"{LABELS[key][0]}, {note}"
        return present_label(key)

    if status == STATUS_NO:
        return f"{absent_label(key)} ({note})" if note else absent_label(key)

    return f"{MISSING_INFO} ({note})" if note else MISSING_INFO


def benchmark_string(key: str, field) -> str:
    """The legacy storage string, for research/benchmark only.

    gold.csv holds 118 rows recorded when these fields were stored as text,
    and score.py normalises that vocabulary. Serialising back to it at the
    benchmark boundary keeps the gold set, the recorded model calls and the
    scorer all valid without a re-run. Notes are dropped - they postdate the
    gold set and have nothing to compare against.
    """
    if not isinstance(field, dict):
        return MISSING_INFO
    status = field.get("status")
    if status == STATUS_YES:
        value = field.get("amount")
        return str(value) if value is not None else present_label(key)
    if status == STATUS_NO:
        return absent_label(key)
    return MISSING_INFO


