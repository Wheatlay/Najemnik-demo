"""
Every field's single canonical stored representation (SPEC §5). Whatever
produces a value for a field - scraper, AI enrichment, or manual edit - must
pass it through here before it hits the database. Display formatting is a
separate, one-way step (never fed back into storage).
"""
import re
from datetime import date, datetime

_NUM_RE = re.compile(r"[\d](?:[\d\s.,]*\d)?")


def normalize_decimal_separator(num: str) -> str:
    """Disambiguates a bare numeric string's '.'/',' into a form float()
    accepts. Polish ads mix conventions for the same amount ("1.500 zł",
    "1,500 zł", "1500,50 zł", "1.500,50 zł") with no single separator that
    always means the same thing.

    When BOTH characters appear, the order is unambiguous: the first is a
    thousands grouping, the last is the decimal point ("1.500,50" -> 1500.50).

    When only ONE appears, its role is inferred from how many digits follow
    it: a real Polish decimal amount is written with 1-2 digits after the
    separator (money in grosze, or "52,5 m2"), while a thousands group is
    always exactly 3 digits. So "1.500"/"1,500" (3 trailing digits) parses as
    1500; "1500,50" (2 trailing digits) parses as 1500.50. This exact
    3-vs-not-3 rule is what a naive "comma is decimal, dot chops it" parser
    gets wrong on ads that write "1.500 zł" for one thousand five hundred."""
    has_dot, has_comma = "." in num, "," in num
    if has_dot and has_comma:
        return num.replace(".", "").replace(",", ".")
    sep = "." if has_dot else "," if has_comma else None
    if sep is None:
        return num
    if len(num.rsplit(sep, 1)[1]) == 3:
        return num.replace(sep, "")
    return num.replace(sep, ".")


def to_int(value) -> int | None:
    """Parse a possibly-messy number (range -> midpoint, thousands sep, comma decimal)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).replace("\xa0", " ").strip()
    range_m = re.match(r"^\s*(\d[\d\s.,]*)\s*[-–]\s*(\d[\d\s.,]*)\s*$", text)
    if range_m:
        lo = to_int(range_m.group(1))
        hi = to_int(range_m.group(2))
        if lo is not None and hi is not None:
            return round((lo + hi) / 2)
    m = _NUM_RE.search(text)
    if not m:
        return None
    num = normalize_decimal_separator(m.group(0).replace(" ", ""))
    try:
        return int(round(float(num)))
    except ValueError:
        return None


def to_float(value, decimals: int = 1) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), decimals)
    text = str(value).replace("\xa0", " ").strip().replace(",", ".")
    m = re.search(r"[\d]+(?:\.\d+)?", text)
    if not m:
        return None
    return round(float(m.group(0)), decimals)


def normalize_phone(value) -> str | None:
    """Digits only, no country code, no spaces."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    if digits.startswith("48") and len(digits) > 9:
        digits = digits[2:]
    return digits or None


def format_phone(value: str | None) -> str:
    if not value:
        return "—"
    d = re.sub(r"\D", "", value)
    return " ".join(d[i:i + 3] for i in range(0, len(d), 3)).strip()


def normalize_floor(value) -> int | None:
    """0 = ground floor / parter. Accepts 'parter', 'ground', a number, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text in ("parter", "ground", "ground_floor", "0"):
        return 0
    m = re.search(r"-?\d+", text)
    return int(m.group(0)) if m else None


def format_floor(floor: int | None, floor_total: int | None) -> str:
    if floor is None:
        return "—"
    label = "parter" if floor == 0 else str(floor)
    return f"{label}/{floor_total}" if floor_total is not None else label


def normalize_rooms(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if "kawalerka" in text or "studio" in text:
        return 1
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None


def format_rooms(rooms: int | None) -> str:
    return f"{rooms} {'pokój' if rooms == 1 else 'pokoje'}" if rooms is not None else "—"


def format_area(area_m2: float | None) -> str:
    return f"{area_m2:.1f} m²" if area_m2 is not None else "—"


def format_money(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ") + " zł"


def normalize_available_from(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip().lower()
    if any(k in text for k in ("od zaraz", "zaraz", "asap", "immediately")):
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def format_available_from(value: date | None) -> str:
    return value.isoformat() if value else "od zaraz"


_MONTHS_PL = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


def format_termin_ogledzin(value: datetime | None) -> str:
    if not value:
        return "—"
    return f"{value.day} {_MONTHS_PL[value.month - 1]}, {value.strftime('%H:%M')}"


def normalize_title_case(value) -> str:
    if not value:
        return ""
    return str(value).strip().title()


def normalize_ocena(value) -> int | None:
    if value is None or value == "":
        return None
    n = to_int(value)
    if n is None:
        return None
    return max(1, min(5, n))


def normalize_status(value) -> str:
    from core.models import Status
    if isinstance(value, Status):
        return value.value
    text = str(value).strip()
    for s in Status:
        if s.value == text or s.name == text.upper():
            return s.value
    return Status.NOWE.value
