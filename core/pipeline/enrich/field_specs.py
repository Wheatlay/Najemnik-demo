"""
Declarative registry driving the per-field enrichment pipeline
(core/pipeline/enrich/pipeline.py). Each FieldSpec describes one AI-touched Listing
field: what to ask, in what mode, and how to validate the answer. Every
answer schema guarantees a canonical result or MISSING_INFO/None - raw model
text never reaches the database (see AnswerSchema.validate).

This registry, plus Python-side validation, is what replaced the old
monolithic prompt in core/pipeline/enrich/prompts/enrich.py: instead of one big
"return this exact JSON shape" prompt the model routinely got wrong in some
key, each field gets one short question with one strict answer format.

Model/prompt choices here are benchmarked in research/benchmark/ (see
research/benchmark/REPORT.md): Bielik-11B-v3.0-Instruct:Q5_K_M with the evidence-first
posrednik/parking prompts and the shared prowizja/district hints ties
qwen2.5:32b on accuracy (277/303 gold rows each) while running ~1.7x faster.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from core.domain.breakdown import STATUSES as UTILITY_STATUSES
from core.domain import money_field
from core.domain.costs import MISSING_INFO
from core.domain.fields import HEATING_TYPES
from core.domain.normalize import to_int

# ---------------------------------------------------------------------------
# Context shared by every prompt
# ---------------------------------------------------------------------------


def build_context(listing) -> str:
    header = f"{listing.title or ''} ({listing.city or ''} {listing.district or ''})".strip()
    return f"{header}\n\nTreść ogłoszenia:\n{(listing.raw_text or '')[:4000]}"


# ---------------------------------------------------------------------------
# Answer schemas - validate(raw_answer_dict) -> canonical value | None
# `None` means "no usable answer" and the caller stores MISSING_INFO (or
# leaves a nullable column as None for TriStateBool).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntPLN:
    """A plain zł amount, or nothing. Rejects out-of-range garbage instead
    of trusting whatever number the model produced."""
    min_value: int = 1
    max_value: int = 20000

    def validate(self, raw: dict) -> int | None:
        if not isinstance(raw, dict):
            return None
        value = to_int(raw.get("kwota"))
        if value is None or not (self.min_value <= value <= self.max_value):
            return None
        return value


@dataclass(frozen=True)
class TriStateMoney:
    """status: tak/nie/brak informacji + optional kwota -> the money-field
    struct (core/domain/money_field.py).

    The model already answers in this shape; this used to flatten it into a
    Polish sentence that every consumer then parsed back. `key` names which
    field's clamps and labels apply - money_field owns both, so the AI path
    and the user-edit path can't drift apart.
    """
    key: str

    def validate(self, raw: dict) -> dict:
        if not isinstance(raw, dict):
            return {"status": money_field.STATUS_UNKNOWN}
        return money_field.validate(self.key, {
            "status": raw.get("status") if raw.get("status") in ("tak", "nie") else None,
            "amount": raw.get("kwota"),
        }) or {"status": money_field.STATUS_UNKNOWN}


@dataclass(frozen=True)
class TriStateBool:
    def validate(self, raw: dict) -> bool | None:
        if not isinstance(raw, dict):
            return None
        answer = raw.get("answer")
        if answer == "tak":
            return True
        if answer == "nie":
            return False
        return None


@dataclass(frozen=True)
class EnumPL:
    values: tuple[str, ...]
    key: str = "wartosc"

    def validate(self, raw: dict) -> str:
        if not isinstance(raw, dict):
            return MISSING_INFO
        value = raw.get(self.key)
        if value in self.values:
            return value
        return MISSING_INFO


# Literal strings a model sometimes emits that pass ShortText's "non-empty
# string" check but aren't real answers (observed: qwen2.5 returning the bare
# word "Null" for district on one listing, which then got stored as a real
# district name). Benchmarked in research/benchmark/items.py before being ported here.
_SHORTTEXT_JUNK = {"null", "none", "brak", MISSING_INFO.lower()}


@dataclass(frozen=True)
class ShortText:
    key: str = "wartosc"
    max_len: int = 80

    def validate(self, raw: dict) -> str | None:
        if not isinstance(raw, dict):
            return None
        value = raw.get(self.key)
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip()
        if value.lower() in _SHORTTEXT_JUNK:
            return None
        return value[: self.max_len]


@dataclass(frozen=True)
class DatePL:
    """available_from: the model is asked to normalize whatever the ad says
    ("od zaraz", "dostępne od 1 sierpnia", a bare date) to ISO-8601 itself,
    since it has to parse Polish month names anyway - core.domain.normalize's
    parser only understands numeric date formats. "od zaraz"/immediately
    available correctly returns null (available_from's own None means
    "now"; see core.domain.normalize.format_available_from)."""

    def validate(self, raw: dict) -> date | None:
        if not isinstance(raw, dict):
            return None
        value = raw.get("data")
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None


@dataclass(frozen=True)
class AgencyStatus:
    """Tri-state for posrednik: True = agencja/pośrednik, False =
    explicitly prywatnie (direct from owner), None = the ad simply doesn't
    address it either way. Mirrors pets_allowed's Optional[bool] pattern -
    a plain ShortText schema could only ever produce a name or nothing, so
    it could never capture "prywatnie" at all."""

    def validate(self, raw: dict) -> bool | None:
        if not isinstance(raw, dict):
            return None
        status = raw.get("status")
        if status == "agencja":
            return True
        if status == "prywatnie":
            return False
        return None


@dataclass(frozen=True)
class UtilityStatus:
    def validate(self, raw: dict) -> dict:
        if not isinstance(raw, dict) or raw.get("status") not in UTILITY_STATUSES:
            return {"status": "brak_informacji"}
        status = raw["status"]
        if status == "osobno":
            amount = to_int(raw.get("kwota"))
            if amount is None or not (1 <= amount <= 3000):
                return {"status": "osobno_bez_kwoty"}
            return {"status": "osobno", "amount": amount}
        return {"status": status}


# ---------------------------------------------------------------------------
# Field specs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label_pl: str
    definition_pl: str
    schema: object
    mode: Literal["verify", "extract"]
    only_if_empty: bool = False
    # Overrides build_extract_prompt's schema-type dispatch for this one
    # field. Signature: (listing, spec) -> str. Used where a field needs
    # wording beyond what its answer schema's generic template provides
    # (e.g. posrednik/parking's evidence-first grounding below).
    custom_prompt: Callable | None = None
    # Overrides schema.validate(raw) for this one field, when validation
    # needs the listing itself (not just the raw answer dict) - e.g.
    # checking that a model-claimed quote actually appears in raw_text.
    # Signature: (raw, listing) -> canonical value (same domain as
    # schema.validate would produce).
    validate_with_listing: Callable | None = None


# ---------------------------------------------------------------------------
# Grounding helpers for evidence-first prompts (posrednik, parking): the
# model must quote the literal ad fragment it's basing its answer on before
# answering: validate_with_listing then rejects any answer whose quote
# doesn't actually appear in listing.raw_text, treating an ungrounded claim
# as "brak informacji"/unknown rather than trusting it. Benchmarked in
# research/benchmark/prompts_v2.py (bielik-v4/v5) - posrednik 62%->93%, parking
# 35%->94% on the 34-listing gold set.
# ---------------------------------------------------------------------------


# Prepended to every extract prompt that can carry a receipt (all of them
# except the two that already have bespoke evidence-first wording). Kept as
# one constant so the phrasing can't drift template by template - the exact
# wording is what the gold-set benchmark measures.
#
# Level A only: the model is asked to quote, and grounded_quote() stores the
# quote, but validation still ignores it. An answer with a missing or
# invented quote is accepted exactly as before and simply shows no receipt.
# Making an ungrounded quote *invalidate* the answer (what posrednik and
# parking do via validate_with_listing) is a separate, stronger change -
# benchmark first, see research/benchmark/.
QUOTE_INSTRUCTION = (
    'Najpierw znajdź w treści ogłoszenia DOSŁOWNY fragment (cytat), na którym opierasz odpowiedź - '
    'przepisz go dokładnie, bez parafrazy. Jeśli w ogłoszeniu nie ma takiego fragmentu, "cytat" musi być null '
    '(i wtedy odpowiedz tak, jak nakazuje reguła "brak informacji" poniżej).'
)
QUOTE_FIELD = '"cytat": "<dosłowny fragment ogłoszenia>" lub null, '

# district is the one field whose answer may legitimately come from the
# context header (city/district line) rather than the ad body - and
# _quote_in_text only searches raw_text, so a header quote would be dropped
# and the field would show no receipt despite a correct answer. Asking for
# null in that case makes the absence deliberate instead of a silent miss.
QUOTE_INSTRUCTION_DISTRICT = (
    'Jeśli opierasz się na fragmencie z TREŚCI ogłoszenia, przepisz go dosłownie do "cytat". '
    'Jeśli dzielnicę bierzesz z nagłówka powyżej, "cytat" musi być null.'
)


def _clean_for_match(s: str) -> str:
    s = re.sub(r"[.…]+$", "", s.strip())  # drop a trailing "..."/"…" continuation marker
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)  # "biura ." and "biura." must compare equal
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def _quote_in_text(quote, raw_text: str) -> bool:
    if not isinstance(quote, str) or not quote.strip():
        return False
    q = _clean_for_match(quote)
    t = _clean_for_match(raw_text or "")
    return len(q) >= 6 and q in t


def grounded_quote(raw, listing) -> str | None:
    """The ad fragment an evidence-first answer claimed, if it genuinely
    appears in raw_text - otherwise None.

    Deliberately the *same* check that decides whether to trust the answer
    (`_quote_in_text`), so the drawer can never show a receipt for a value
    the pipeline itself considered ungrounded. Returns the model's original
    wording, not the match-normalized form, because it's shown to a human.

    Only fields whose prompt asks for "cytat" can produce one; everything
    else returns None and simply has no receipt to show.
    """
    if not isinstance(raw, dict):
        return None
    quote = raw.get("cytat")
    if not _quote_in_text(quote, listing.raw_text):
        return None
    return quote.strip()


# ---------------------------------------------------------------------------
# Custom per-field prompts (must be defined before FIELD_SPECS, which
# references them by name)
# ---------------------------------------------------------------------------


def build_prowizja_prompt(listing, spec: "FieldSpec") -> str:
    """Targets: models answering 'wymagana, kwota nie podana' or a wrong
    number when the ad states a formula (e.g. '123% czynszu',
    'jednomiesięczny czynsz + VAT') instead of a bare zł figure."""
    return f"""Analizujesz ogłoszenie wynajmu mieszkania.

{build_context(listing)}

Pytanie dotyczy: {spec.label_pl}.
{spec.definition_pl}
{QUOTE_INSTRUCTION}
Ustal status na podstawie TYLKO tego cytatu:
- "tak" - cytat potwierdza, że to dotyczy tej oferty (podaj kwotę w zł jeśli jest podana, inaczej null)
- "nie" - cytat wprost temu zaprzecza / mówi że tego nie ma
- "brak informacji" - nie znalazłeś pasującego cytatu
Jeśli prowizja jest podana jako procent lub wielokrotność czynszu (np. "123% czynszu", "jednomiesięczny czynsz + VAT"), OBLICZ kwotę w złotych na podstawie czynszu podanego w tym samym ogłoszeniu i podaj wynik jako liczbę - nie zostawiaj "kwota nie podana", jeśli da się to policzyć z danych w ogłoszeniu. Cytatem jest wtedy fragment podający tę formułę.
Nie zgaduj kwoty, jeśli w ogłoszeniu nie ma podstawy do jej obliczenia.

Zwróć WYŁĄCZNIE obiekt JSON: {{{QUOTE_FIELD}"status": "tak"/"nie"/"brak informacji", "kwota": <liczba lub null>}}"""


def build_district_prompt(listing, spec: "FieldSpec") -> str:
    """Targets: models answering 'brak informacji' or a city-prefixed
    variant ('Katowice Koszutka') when the district is right there in the
    context header we build, just not inside 'Treść ogłoszenia:' itself."""
    return f"""Analizujesz ogłoszenie wynajmu mieszkania.

{build_context(listing)}

Pytanie: {spec.label_pl}?
{spec.definition_pl}
UWAGA: nagłówek powyżej (przed "Treść ogłoszenia:") to też dane ogłoszenia - często zawiera miasto i dzielnicę. Jeśli dzielnica jest tam podana, użyj jej. Zwróć SAMĄ nazwę dzielnicy/osiedla, bez nazwy miasta (np. "Koszutka", nie "Katowice Koszutka").
Jeśli ogłoszenie nie podaje tej informacji wprost (ani w nagłówku, ani w treści), zwróć null - nie zgaduj.
{QUOTE_INSTRUCTION_DISTRICT}

Zwróć WYŁĄCZNIE obiekt JSON: {{{QUOTE_FIELD}"wartosc": "<tekst>"}} lub {{{QUOTE_FIELD}"wartosc": null}}"""


def build_posrednik_prompt(listing, spec: "FieldSpec") -> str:
    """Evidence-first: the model must quote the ad fragment it's basing its
    answer on before answering, and the cue->verdict mapping is repeated at
    the classification step (not just the find-the-quote step) so a
    correctly-quoted boilerplate footer actually gets classified as agencja
    instead of being quoted then second-guessed."""
    return f"""Analizujesz ogłoszenie wynajmu mieszkania.

{build_context(listing)}

Pytanie: {spec.label_pl}?
{spec.definition_pl}
Najpierw znajdź w treści ogłoszenia DOSŁOWNY fragment (cytat), który wskazuje na status pośrednictwa. Jeśli nic takiego nie ma w tekście, "cytat" musi być null.
Potem, na podstawie WYŁĄCZNIE tego cytatu (nie zgaduj poza nim), ustal:
- "agencja" - cytat wskazuje na biuro/agencję pośrednictwa. Liczy się KAŻDY z poniższych typów cytatu jako "agencja", nawet bez słowa "agencja" wprost: stopka prawna w stylu "niniejsze ogłoszenie nie stanowi oferty handlowej w rozumieniu Kodeksu Cywilnego", wzmianka o systemie/programie dla biur nieruchomości (np. "ASARI CRM"), informacja o prowizji biura/pośrednika ("prowizja biura", "wynagrodzenie pośrednika", "wymagana prowizja dla biura").
- "prywatnie" - cytat wskazuje na ofertę bezpośrednio od właściciela / bez pośredników
- "brak informacji" - nie znalazłeś żadnego pasującego cytatu

Zwróć WYŁĄCZNIE obiekt JSON: {{"cytat": "<dosłowny fragment ogłoszenia>" lub null, "status": "agencja"/"prywatnie"/"brak informacji"}}"""


def validate_posrednik(raw: dict, listing) -> bool | None:
    if not isinstance(raw, dict):
        return None
    status = raw.get("status")
    if status not in ("agencja", "prywatnie"):
        return None
    if not _quote_in_text(raw.get("cytat"), listing.raw_text):
        return None  # ungrounded claim - fall back to "brak informacji"
    return status == "agencja"


def build_parking_prompt(listing, spec: "FieldSpec") -> str:
    """Evidence-first + the parking policy: unassigned/communal/street
    parking ("parkowanie na ulicy", "miejsca dla mieszkańców przed
    blokiem") counts as "nie" (no dedicated spot), not "tak" and not "brak
    informacji" - a rule the ad text alone doesn't make obvious without
    being told."""
    return f"""Analizujesz ogłoszenie wynajmu mieszkania.

{build_context(listing)}

Pytanie dotyczy: {spec.label_pl}.
{spec.definition_pl}
Najpierw znajdź w treści ogłoszenia DOSŁOWNY fragment (cytat) wspominający o miejscu parkingowym, garażu lub miejscu postojowym. Jeśli ogłoszenie w ogóle nie wspomina o parkowaniu, "cytat" musi być null.
Potem, na podstawie WYŁĄCZNIE tego cytatu, ustal status:
- "tak" - cytat potwierdza miejsce parkingowe/garaż PRZYPISANE do tej oferty (np. "miejsce w garażu podziemnym", "miejsce postojowe w cenie") - podaj kwotę w zł TYLKO jeśli cytat podaje ją wprost jako cenę SAMEGO miejsca, inaczej null
- "nie" - cytat opisuje WYŁĄCZNIE niezarezerwowany/wspólny parking (parkowanie na ulicy, miejsca dla mieszkańców przed blokiem, parking ogólnodostępny) - to NIE jest przypisane miejsce, więc licz to jako brak miejsca parkingowego
- "brak informacji" - brak pasującego cytatu

Zwróć WYŁĄCZNIE obiekt JSON: {{"cytat": "<dosłowny fragment ogłoszenia>" lub null, "status": "tak"/"nie"/"brak informacji", "kwota": <liczba lub null>}}"""


def validate_parking(raw: dict, listing) -> dict:
    unknown = {"status": money_field.STATUS_UNKNOWN}
    if not isinstance(raw, dict):
        return unknown
    status = raw.get("status")
    if status not in ("tak", "nie"):
        return unknown
    if not _quote_in_text(raw.get("cytat"), listing.raw_text):
        return unknown  # ungrounded claim - fall back to unknown, not "nie"
    return money_field.validate("parking", {"status": status, "amount": raw.get("kwota")}) or unknown


FIELD_SPECS: list[FieldSpec] = [
    FieldSpec(
        "rent_owner", "czynsz najmu płatny właścicielowi/wynajmującemu (tzw. odstępne)",
        "Kwota w złotych, którą najemca płaci co miesiąc bezpośrednio właścicielowi/wynajmującemu "
        "za wynajem (bez opłaty administracyjnej/czynszu do spółdzielni czy wspólnoty).",
        IntPLN(min_value=1, max_value=20000), mode="verify",
    ),
    FieldSpec(
        "czynsz_admin", "opłata administracyjna (czynsz do wspólnoty/spółdzielni)",
        "Miesięczna opłata administracyjna/eksploatacyjna płacona do wspólnoty lub spółdzielni "
        "mieszkaniowej (nie mylić z czynszem dla właściciela).",
        IntPLN(min_value=1, max_value=5000), mode="verify",
    ),
    FieldSpec(
        "deposit", "kaucja zabezpieczająca",
        "Jednorazowa kaucja zwrotna wpłacana przy podpisaniu umowy najmu.",
        TriStateMoney("deposit"), mode="verify",
    ),
    FieldSpec(
        "heating", "rodzaj ogrzewania",
        "Typ ogrzewania mieszkania.",
        EnumPL(values=(*HEATING_TYPES, MISSING_INFO)),
        mode="extract",
    ),
    FieldSpec(
        "parking", "miejsce parkingowe / garaż",
        "Czy do mieszkania przypisane jest miejsce parkingowe lub garaż, i czy jest wliczone "
        "w cenę czy płatne osobno.",
        TriStateMoney("parking"),
        mode="extract",
        custom_prompt=build_parking_prompt, validate_with_listing=validate_parking,
    ),
    FieldSpec(
        "piwnica", "piwnica / komórka lokatorska",
        "Czy do mieszkania przypisana jest piwnica lub komórka lokatorska, i czy jest wliczona "
        "w cenę czy płatna osobno.",
        TriStateMoney("piwnica"),
        mode="extract",
    ),
    FieldSpec(
        "notariusz", "wymóg najmu okazjonalnego (oświadczenie notarialne)",
        "Czy ogłoszenie wspomina o wymogu najmu okazjonalnego / oświadczenia u notariusza "
        "(koszt ponosi zwykle najemca).",
        TriStateMoney("notariusz"),
        mode="extract",
    ),
    FieldSpec(
        "prowizja", "prowizja agencji/pośrednika",
        "Prowizja za pośrednictwo w wynajmie - czy jest wymagana, ile wynosi, lub czy oferta "
        "jest bezpośrednio od właściciela (bez prowizji).",
        TriStateMoney("prowizja"),
        mode="extract",
        custom_prompt=build_prowizja_prompt,
    ),
    FieldSpec(
        "oc", "ubezpieczenie OC (odpowiedzialności cywilnej) najemcy",
        "Czy ogłoszenie wymaga od najemcy wykupienia ubezpieczenia OC (odpowiedzialności "
        "cywilnej) - często wspominane razem z najmem okazjonalnym lub kaucją.",
        TriStateMoney("oc"),
        mode="extract",
    ),
    FieldSpec(
        "pets_allowed", "zgoda na zwierzęta domowe",
        "Czy ogłoszenie wprost mówi, że zwierzęta są dozwolone lub zakazane.",
        TriStateBool(), mode="extract", only_if_empty=True,
    ),
    FieldSpec(
        "district", "dzielnica",
        "Dzielnica/osiedle, w której znajduje się mieszkanie.",
        ShortText(max_len=60), mode="extract", only_if_empty=True,
        custom_prompt=build_district_prompt,
    ),
    FieldSpec(
        "available_from", "data dostępności mieszkania",
        "Od kiedy mieszkanie jest dostępne do wynajęcia - jeśli ogłoszenie mówi \"od zaraz\"/"
        "\"dostępne natychmiast\" bez konkretnej daty, zwróć null (oznacza dostępność od zaraz).",
        DatePL(), mode="extract", only_if_empty=True,
    ),
    FieldSpec(
        "posrednik", "pośrednik / agencja nieruchomości",
        "Czy ogłoszenie jest ofertą biura pośrednictwa/agencji nieruchomości, czy wprost "
        "ofertą prywatną bezpośrednio od właściciela.",
        AgencyStatus(), mode="extract", only_if_empty=True,
        custom_prompt=build_posrednik_prompt, validate_with_listing=validate_posrednik,
    ),
]

FIELD_SPECS_BY_KEY: dict[str, FieldSpec] = {s.key: s for s in FIELD_SPECS}


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

# The cross-check prompt that used to run for mode="verify" fields lived
# here. Its only output was an order-of-magnitude mismatch note appended to
# notes_extra ("Uwagi (AI)"); with that field removed, the two model calls it
# cost per field bought nothing measurable, so it went too. verify mode now
# means only "fill this if scraping left it empty, never overwrite". Restore
# from git history if the cross-check is ever wanted with a real output.

_INT_EXTRACT_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

{context}

Pytanie: jaka jest kwota (w zł) dla: {label}?
{definition}
Jeśli ogłoszenie nie podaje tej kwoty wprost - nie zgaduj, zwróć null.

Zwróć WYŁĄCZNIE obiekt JSON: {{"kwota": <liczba>}} lub {{"kwota": null}}"""

_TRISTATE_MONEY_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

{context}

Pytanie dotyczy: {label}.
{definition}
{quote_instruction}
Ustal status na podstawie TYLKO tego cytatu:
- "tak" - cytat potwierdza, że to dotyczy tej oferty (podaj kwotę w zł jeśli cytat ją podaje, inaczej null)
- "nie" - cytat wprost temu zaprzecza / mówi że tego nie ma
- "brak informacji" - nie znalazłeś pasującego cytatu
Nie zgaduj kwoty, jeśli nie jest podana wprost.

Zwróć WYŁĄCZNIE obiekt JSON: {{{quote_field}"status": "tak"/"nie"/"brak informacji", "kwota": <liczba lub null>}}"""

_TRISTATE_BOOL_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

{context}

Pytanie: {label}?
{definition}
{quote_instruction}
Odpowiedz "tak" lub "nie" TYLKO jeśli znaleziony cytat wprost to potwierdza lub wyklucza. Jeśli nie ma takiego cytatu, odpowiedz "brak informacji" - nie zgaduj.

Zwróć WYŁĄCZNIE obiekt JSON: {{{quote_field}"answer": "tak"/"nie"/"brak informacji"}}"""

_ENUM_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

{context}

Pytanie: {label}?
{definition}
{quote_instruction}
Wybierz DOKŁADNIE jedną z wartości: {values}, opierając się TYLKO na tym cytacie.
Jeśli nie ma pasującego cytatu, zwróć "brak informacji" - nie zgaduj.

Zwróć WYŁĄCZNIE obiekt JSON: {{{quote_field}"wartosc": "<jedna z wartości powyżej>"}}"""

_SHORT_TEXT_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

{context}

Pytanie: {label}?
{definition}
{quote_instruction}
Jeśli ogłoszenie nie podaje tej informacji wprost, zwróć null - nie zgaduj.

Zwróć WYŁĄCZNIE obiekt JSON: {{{quote_field}"wartosc": "<tekst>"}} lub {{{quote_field}"wartosc": null}}"""

_DATE_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania. Dzisiejsza data (data dodania ogłoszenia): {today}.

{context}

Pytanie: {label}?
{definition}
Zwróć datę w formacie ISO RRRR-MM-DD (np. "2026-08-01"). Jeśli ogłoszenie podaje samą nazwę miesiąca bez roku (np. "od lipca"), przyjmij NAJBLIŻSZE wystąpienie tego miesiąca licząc od dzisiejszej daty podanej wyżej (jeśli ten miesiąc w tym roku już minął, weź przyszły rok).
WAŻNE: jeśli ogłoszenie mówi "od zaraz", "dostępne natychmiast", "od teraz" LUB w ogóle NIE podaje żadnej daty ani okresu dostępności, zwróć {{"data": null}} - NIGDY nie zwracaj dzisiejszej daty ani żadnej zgadywanej daty w takim przypadku. Przykład: ogłoszenie zawiera tylko "Do wynajęcia od zaraz" bez dalszych szczegółów o terminie -> odpowiedź to {{"data": null}}, NIE dzisiejsza data.

{quote_instruction}

Zwróć WYŁĄCZNIE obiekt JSON: {{{quote_field}"data": "RRRR-MM-DD"}} lub {{{quote_field}"data": null}}"""

_AGENCY_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

{context}

Pytanie: {label}?
{definition}
Ustal status na podstawie TYLKO treści ogłoszenia:
- "agencja" - ogłoszenie wprost wskazuje, że to oferta biura/agencji nieruchomości (pośrednika)
- "prywatnie" - ogłoszenie wprost mówi, że jest bezpośrednio od właściciela / bez pośredników / bez prowizji dla biura
- "brak informacji" - ogłoszenie w ogóle nie porusza tego tematu
Nie zgaduj - jeśli nic nie wskazuje ani na jedno, ani na drugie, zwróć "brak informacji".

Zwróć WYŁĄCZNIE obiekt JSON: {{"status": "agencja"/"prywatnie"/"brak informacji"}}"""

UTILITY_TEMPLATE = """Analizujesz ogłoszenie wynajmu mieszkania.

{context}

Znane już kwoty dla TEGO ogłoszenia (nie mylić z kosztem poniższego medium): {known_costs}

Pytanie: jak ogłoszenie traktuje koszt: {utility_label}?
Ustal status na podstawie TYLKO treści ogłoszenia:
- "w_czynszu" - ogłoszenie mówi, że ten koszt jest wliczony w czynsz/opłatę administracyjną
- "osobno" - ogłoszenie mówi, że jest płatny osobno, i podaje KONKRETNĄ, WŁASNĄ kwotę TEGO medium (podaj ją w "kwota")
- "osobno_bez_kwoty" - ogłoszenie mówi, że jest płatny osobno, ale BEZ podanej własnej kwoty
- "brak_informacji" - ogłoszenie w ogóle nie wspomina o tym koszcie
WAŻNE: nie podawaj w "kwota" czynszu administracyjnego, czynszu dla właściciela ani żadnej innej sumy zbiorczej wymienionej wyżej - "kwota" musi być kosztem WYŁĄCZNIE tego jednego medium, jeśli ogłoszenie faktycznie go tak rozdziela. Jeśli ogłoszenie wspomina to medium tylko przy okazji sumy całkowitej (np. "czynsz 1045 zł w tym woda i śmieci"), to jest to "w_czynszu", NIE "osobno". Nie zgaduj kwoty, jeśli nie jest podana wprost jako osobna pozycja.{gas_heating_hint}

Zwróć WYŁĄCZNIE obiekt JSON: {{"status": "<jedna z wartości powyżej>", "kwota": <liczba lub null>}}"""


def build_extract_prompt(listing, spec: FieldSpec) -> str:
    if spec.custom_prompt is not None:
        return spec.custom_prompt(listing, spec)
    context = build_context(listing)
    schema = spec.schema
    # Every templated field asks for its receipt; IntPLN is the exception,
    # since rent/czynsz come from the portal's own structured fields and the
    # model is only filling a gap, not reading prose.
    q = {"quote_instruction": QUOTE_INSTRUCTION, "quote_field": QUOTE_FIELD}
    if isinstance(schema, IntPLN):
        return _INT_EXTRACT_TEMPLATE.format(context=context, label=spec.label_pl, definition=spec.definition_pl)
    if isinstance(schema, TriStateMoney):
        return _TRISTATE_MONEY_TEMPLATE.format(context=context, label=spec.label_pl, definition=spec.definition_pl, **q)
    if isinstance(schema, TriStateBool):
        return _TRISTATE_BOOL_TEMPLATE.format(context=context, label=spec.label_pl, definition=spec.definition_pl, **q)
    if isinstance(schema, AgencyStatus):
        return _AGENCY_TEMPLATE.format(context=context, label=spec.label_pl, definition=spec.definition_pl)
    if isinstance(schema, EnumPL):
        return _ENUM_TEMPLATE.format(context=context, label=spec.label_pl, definition=spec.definition_pl,
                                      values=", ".join(f'"{v}"' for v in schema.values), **q)
    if isinstance(schema, ShortText):
        return _SHORT_TEXT_TEMPLATE.format(context=context, label=spec.label_pl, definition=spec.definition_pl, **q)
    if isinstance(schema, DatePL):
        today = (listing.created_at or datetime.now()).date().isoformat()
        return _DATE_TEMPLATE.format(context=context, label=spec.label_pl, definition=spec.definition_pl, today=today, **q)
    raise TypeError(f"no extract prompt for schema {schema!r}")


_GAS_HEATING_HINT = (
    "\nUWAGA: to mieszkanie ma ogrzewanie gazowe. Jeśli ogłoszenie podaje JEDEN łączny koszt gazu, który "
    "pokrywa zarówno ogrzewanie, jak i gotowanie (typowe dla ogrzewania gazowego - to ten sam licznik/rachunek), "
    "podaj tę SAMĄ kwotę zarówno tutaj (ogrzewanie), jak i w osobnym pytaniu o koszt gazu - nie dziel jednego "
    "rachunku na dwie różne, mniejsze kwoty."
)


def build_utility_prompt(listing, utility: str, label: str) -> str:
    known = []
    if listing.czynsz_admin:
        known.append(f"czynsz administracyjny = {listing.czynsz_admin} zł")
    if listing.rent_owner:
        known.append(f"czynsz dla właściciela = {listing.rent_owner} zł")
    known_costs = ", ".join(known) if known else "brak"
    gas_heating_hint = _GAS_HEATING_HINT if (utility == "ogrzewanie" and listing.heating == "gazowe") else ""
    return UTILITY_TEMPLATE.format(context=build_context(listing), utility_label=label, known_costs=known_costs,
                                    gas_heating_hint=gas_heating_hint)
