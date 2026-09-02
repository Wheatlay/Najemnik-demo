import uuid
from datetime import date, datetime
from enum import Enum

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from core.infra.config import ASSUMED_HEATING_COST_BY_TYPE, ASSUMED_UTILITY_COSTS


class Status(str, Enum):
    NOWE = "Nowe"
    PRZEJRZANE = "Przejrzane"
    UMOWIONE = "Umówione na oględziny"
    OBEJRZANE = "Obejrzane"
    POTENCJALNE = "Potencjalne"
    ODRZUCONE = "Odrzucone"


def new_uuid() -> str:
    return str(uuid.uuid4())


class User(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    email: str = Field(unique=True, index=True)  # stored lowercase
    password_hash: str
    display_name: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    email_verified_at: datetime | None = None
    last_login_at: datetime | None = None
    is_admin: bool = False
    # Tombstone for self-serve account deletion (SPEC §13): row survives so
    # FK integrity in llm_usage/product_events holds, but PII is scrubbed.
    deleted_at: datetime | None = None
    # Unused. Drove the first-run checklist (SPEC §10), which the guided
    # tour replaced - the tour teaches the same three things in place and at
    # the moment each applies. Kept because dropping a column needs a
    # migration and buys nothing; nothing reads it.
    onboarding_dismissed: bool = False


class AuthSession(SQLModel, table=True):
    token_hash: str = Field(primary_key=True)  # sha256 of the cookie value
    user_id: str = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime  # 30 days, sliding on use
    user_agent: str = ""
    # Per-session CSRF secret (SPEC §6) - handed to the client once at login
    # and echoed back on every mutating request; unrelated to the session
    # cookie itself so a leaked Referer/log line can't be used to forge one.
    csrf_token: str = Field(default_factory=new_uuid)


class ApiToken(SQLModel, table=True):
    """Bearer token for the browser extension (SPEC §21 1.5c). Mirrors
    AuthSession's shape (only the hash is ever persisted) but is a distinct
    table/mechanism, not a session: it's cross-origin, doesn't expire on a
    sliding window, and is never read from a cookie - core.infra.deps's
    current_user_api dependency reads it from an Authorization: Bearer
    header only, which is what lets /api/* skip CSRF (see core/infra/csrf.py)
    without weakening it - CSRF defends against a browser attaching
    credentials *automatically*, which a header it never sends on its own
    can't happen to."""
    token_hash: str = Field(primary_key=True)  # sha256 of the bearer value
    user_id: str = Field(foreign_key="user.id", index=True)
    label: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    last_used_at: datetime | None = None


class UsageCounter(SQLModel, table=True):
    """Generic per-user/per-key/per-day counter backing every quota in
    SPEC §12 (imports, enrichment calls, login attempts, registrations) -
    no Redis, just a row bumped in place."""
    __table_args__ = (UniqueConstraint("scope", "key", "day"),)
    id: int | None = Field(default=None, primary_key=True)
    # "scope" identifies *what* is being counted (e.g. "imports:<user_id>",
    # "login_fail:<email>", "register_ip:<ip>") - key is normally the same
    # value folded into scope, kept separate only so a single scope can be
    # queried without string-parsing it back apart.
    scope: str = Field(index=True)
    key: str = ""
    day: date
    count: int = 0


class LLMUsage(SQLModel, table=True):
    """Per-call cost/usage log (SPEC §8) - one row per LLMProvider call, for
    steering (admin metrics page, M6) and future per-user enrichment
    quotas. token counts come straight from Ollama's own response fields
    when available."""
    id: str = Field(default_factory=new_uuid, primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    listing_id: str | None = Field(default=None, foreign_key="listing.id", index=True)
    provider: str = "ollama"
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    ts: datetime = Field(default_factory=datetime.now, index=True)


class ProductEvent(SQLModel, table=True):
    """Server-side product analytics (SPEC §15) - self-hosted by
    definition, no third-party page analytics. A handful of events that
    matter for steering: registered, first_import, import, enrich,
    viewing_scheduled, export."""
    id: str = Field(default_factory=new_uuid, primary_key=True)
    user_id: str | None = Field(default=None, foreign_key="user.id", index=True)
    event: str = Field(index=True)
    ts: datetime = Field(default_factory=datetime.now, index=True)
    props: dict = Field(default_factory=dict, sa_column=Column(JSON))


class FetchCache(SQLModel, table=True):
    """Global (cross-user) record of every page fetch (SPEC §7/§5). Dedups
    network traffic to source sites - a fetch newer than 6h is reused
    across users importing the same public URL - and quietly accumulates
    the raw material for Phase 2 aggregates (price history per URL/address
    across all users). raw_payload holds the scraper's already-extracted
    field dict, never the full HTML (size + GDPR hygiene); purged after 30
    days by the M6 nightly job, independent of the non-personal summary
    columns which may stay for aggregates."""
    id: str = Field(default_factory=new_uuid, primary_key=True)
    url_normalized: str = Field(index=True)
    fetched_at: datetime = Field(default_factory=datetime.now, index=True)
    http_status: int
    site: str = ""
    title: str = ""
    price_seen: int | None = None
    raw_payload: dict | None = Field(default=None, sa_column=Column(JSON))


class Listing(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("user_id", "url"),)

    # Identity
    id: str = Field(default_factory=new_uuid, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    url: str = Field(index=True)
    site: str = "other"
    # Naive local time throughout the app (single-machine, single-user, no
    # multi-timezone concern) - matches termin_ogledzin, which comes from a
    # browser <input type="datetime-local"> and is unavoidably local wall-
    # clock time. Mixing that with UTC elsewhere caused overdue/upcoming
    # viewings on Pulpit to be off by the local UTC offset.
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    raw_text: str = ""
    # False once a re-import finds the ad gone (404). Deliberately NOT the
    # same question as "the user rejected it" (status == Odrzucone) - a dead
    # ad still belongs in the gallery so you can see it went down, while a
    # rejected one is hidden. Call sites pick the predicate they mean; see
    # core/domain/queries.py for the two named helpers.
    is_active: bool = True
    # Bundled demo fixture (SPEC §10), badged "Przykład" and removable like
    # any other listing - not distinguished from real data in any query,
    # only in display.
    is_demo: bool = False

    # Location
    title: str = ""
    address: str = ""
    city: str = ""
    district: str = ""
    lat: float | None = None
    lon: float | None = None
    commute_time_car: str = ""
    commute_time_public: str = ""
    # Manual judgment call - the scraped pin can be an approximate area
    # centroid rather than the real building, so this can't be inferred by
    # AI or the scraper. Defaults to False (unconfirmed) - the user flips it
    # to True only after actively checking the map pin against the real
    # address, rather than assuming every pin is trustworthy until proven
    # otherwise. A plain bool (not tri-state like most other select_bool
    # fields) - there's no meaningful "don't know" state for a flag the user
    # sets themselves.
    pewnosc_lokalizacji: bool = False

    # Apartment
    area_m2: float | None = None
    rooms: int | None = None
    floor: int | None = None
    floor_total: int | None = None
    available_from: date | None = None
    pets_allowed: bool | None = None

    # Monthly cost
    rent_owner: int | None = None
    czynsz_admin: int | None = None
    other_costs: int | None = None
    heating: str = ""
    # The six money fields below are {status, amount, note} JSON - see
    # core/domain/money_field.py for the schema and why they stopped being
    # Polish sentences. None means never filled.
    parking: dict | None = Field(default=None, sa_column=Column(JSON))
    piwnica: dict | None = Field(default=None, sa_column=Column(JSON))
    fees_note: str = ""

    # Entry cost
    deposit: dict | None = Field(default=None, sa_column=Column(JSON))
    notariusz: dict | None = Field(default=None, sa_column=Column(JSON))
    prowizja: dict | None = Field(default=None, sa_column=Column(JSON))
    # ubezpieczenie OC (odpowiedzialności cywilnej) najemcy
    oc: dict | None = Field(default=None, sa_column=Column(JSON))

    # Contact
    phone: str | None = None
    # tak = agencja/pośrednik, nie = prywatnie, None = brak informacji.
    posrednik: bool | None = None

    # Assessment
    status: Status = Field(default=Status.NOWE)
    termin_ogledzin: datetime | None = None
    ocena_wygladu: int | None = None
    ocena_glosnosci_otoczenia: int | None = None
    rank: int | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    notatki: str = ""

    # AI-generated
    ai_comment: str = ""
    # The record of what AI actually wrote on THIS row: {field_key: quote or
    # None}. A key being present is the authorship claim; its value is the
    # supporting fragment, quoted verbatim from raw_text, or None when the
    # model gave no usable quote.
    #
    # Presence - not FieldDef.source - is what the badge reads, because
    # `source` only says where a field is *normally* filled from. An
    # ai_verify field like `deposit` is usually the portal's, but when
    # scraping leaves it empty the model fills it, and a kaucja reading
    # "wymagana, kwota nie podana" is the model's words, not the portal's.
    # Only a per-row record can tell those two cases apart.
    ai_evidence: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Field keys the user has edited by hand. Once a key is in here the UI
    # stops crediting the value to AI, because it isn't AI's any more -
    # FieldDef.source describes where a field is *normally* filled from, not
    # who last wrote this particular row. Append-only: re-editing is still
    # a user edit, and clearing the box leaves the field the user's.
    edited_fields: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Structured per-utility judgment (woda/ogrzewanie/smieci/prad/gaz/internet)
    # filled by core.pipeline.enrich.pipeline; core.domain.breakdown derives fees_note and
    # the extra-monthly-cost math from this deterministically. See
    # core/domain/breakdown.py for the schema.
    cost_breakdown: dict | None = Field(default=None, sa_column=Column(JSON))
    enriched_at: datetime | None = None

    # Media
    photos: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class Settings(SQLModel, table=True):
    """Per-user app-wide defaults - see core/domain/settings.py for the cached
    get_settings(user_id) accessor. Column defaults mirror core.infra.config's
    factory constants so a fresh row (new account, or "reset to defaults")
    behaves exactly like the pre-/ustawienia hardcoded values."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="user.id", unique=True, index=True)

    # Assumed monthly cost (zł) for a utility an ad doesn't state an amount
    # for - see core.domain.breakdown.extra_monthly_costs.
    woda_cost: int = ASSUMED_UTILITY_COSTS["woda"]
    ogrzewanie_cost: int = ASSUMED_UTILITY_COSTS["ogrzewanie"]
    smieci_cost: int = ASSUMED_UTILITY_COSTS["smieci"]
    prad_cost: int = ASSUMED_UTILITY_COSTS["prad"]
    gaz_cost: int = ASSUMED_UTILITY_COSTS["gaz"]
    internet_cost: int = ASSUMED_UTILITY_COSTS["internet"]

    # Extra assumed monthly heating cost by type, added on top of the above
    # only when heating is a known non-district type - see
    # core.domain.breakdown._assumed_cost.
    heating_gazowe_cost: int = ASSUMED_HEATING_COST_BY_TYPE["gazowe"]
    heating_elektryczne_cost: int = ASSUMED_HEATING_COST_BY_TYPE["elektryczne"]
    heating_kominkowe_cost: int = ASSUMED_HEATING_COST_BY_TYPE["kominkowe"]
    heating_inne_cost: int = ASSUMED_HEATING_COST_BY_TYPE["inne"]

    # Named reference points (e.g. "Praca", "Uczelnia") for the drawer's
    # straight-line distance hint - [{"id", "name", "lat", "lon"}, ...].
    # No routing/geocoding integration exists in this app, so this is a
    # stand-in for real drive/transit time, not a replacement for it.
    commute_points: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
