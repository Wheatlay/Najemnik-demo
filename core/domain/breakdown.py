"""
Structured, deterministic handling of the per-utility cost breakdown that AI
enrichment fills (core/pipeline/enrich/pipeline.py). The AI's job stops at judging,
per utility, whether it's included in czynsz, paid separately (with or
without a known amount), or simply not mentioned - everything downstream
(the Polish summary sentence, the extra-cost math) is plain Python so it's
always consistent and testable without a model in the loop.
"""

UTILITIES = ["woda", "ogrzewanie", "smieci", "prad", "gaz", "internet"]

LABELS_PL = {
    "woda": "wodę", "ogrzewanie": "ogrzewanie", "smieci": "śmieci",
    "prad": "prąd", "gaz": "gaz", "internet": "internet",
}
# Nominative form, for standalone mentions ("Prąd płatny osobno...").
LABELS_PL_NOM = {
    "woda": "woda", "ogrzewanie": "ogrzewanie", "smieci": "śmieci",
    "prad": "prąd", "gaz": "gaz", "internet": "internet",
}

STATUSES = ("w_czynszu", "osobno", "osobno_bez_kwoty", "brak_informacji")
# Plausible ceiling for a single utility's own monthly cost (zł). Anything
# above is almost certainly a total (whole czynsz, whole media package)
# misread as one utility's cost, not a real per-utility price.
_MAX_AMOUNT_PER_UTILITY = {
    "woda": 500, "ogrzewanie": 1500, "smieci": 200,
    "prad": 800, "gaz": 600, "internet": 250,
}


def empty_breakdown() -> dict:
    return {"version": 1, "utilities": {u: {"status": "brak_informacji"} for u in UTILITIES}}


def validate_breakdown(raw: dict, czynsz_admin: int | None = None,
                       rent_owner: int | None = None, heating: str = "") -> dict:
    """Clamps an arbitrary dict (typically assembled from per-utility AI
    answers) to the canonical schema - every utility present, a known
    status, and an amount only when it's plausible as that one utility's own
    monthly cost. Anything else collapses to a weaker status rather than
    trusting unvalidated AI output.

    The czynsz_admin/rent_owner cross-check catches the observed
    misattribution failure: ads phrased "czynsz 1045 zł (w tym woda,
    śmieci)" make the model answer each per-utility question with the WHOLE
    czynsz amount ("śmieci: osobno, 1045"), double-counting it per utility.
    An amount exactly equal to czynsz_admin means the model latched onto the
    admin-fee total - and a utility cited alongside that total is almost
    always included in it, so it becomes "w_czynszu". An amount equal to the
    rent itself (or rent+czynsz) is a plain wrong grab -> "brak_informacji".

    For gas heating specifically, ogrzewanie and gaz are asked as two
    separate questions but are routinely the SAME real bill (one gas meter
    heats the flat and runs the stove) - the ad genuinely describes one cost
    from two angles, not two charges. When both come back "osobno" with the
    identical amount (the tell of one bill answered twice), ogrzewanie is
    folded into gaz so it isn't counted twice."""
    from core.domain.normalize import to_int

    raw_utilities = raw.get("utilities", {}) if isinstance(raw, dict) else {}
    utilities = {}
    for u in UTILITIES:
        entry = raw_utilities.get(u) if isinstance(raw_utilities, dict) else None
        status = entry.get("status") if isinstance(entry, dict) else None
        if status not in STATUSES:
            utilities[u] = {"status": "brak_informacji"}
            continue
        if status == "osobno":
            amount = to_int(entry.get("amount")) if isinstance(entry, dict) else None
            if amount is None:
                utilities[u] = {"status": "osobno_bez_kwoty"}
            elif czynsz_admin and amount == czynsz_admin:
                utilities[u] = {"status": "w_czynszu"}
            elif rent_owner and amount in (rent_owner, rent_owner + (czynsz_admin or 0)):
                utilities[u] = {"status": "brak_informacji"}
            elif not (1 <= amount <= _MAX_AMOUNT_PER_UTILITY[u]):
                utilities[u] = {"status": "osobno_bez_kwoty"}
            else:
                utilities[u] = {"status": "osobno", "amount": amount}
        else:
            utilities[u] = {"status": status}

    if (heating == "gazowe" and utilities["ogrzewanie"]["status"] == "osobno"
            and utilities["gaz"]["status"] == "osobno"
            and utilities["ogrzewanie"]["amount"] == utilities["gaz"]["amount"]):
        utilities["ogrzewanie"] = {"status": "polaczone_z_gazem"}

    return {"version": 1, "utilities": utilities}


def _assumed_cost(u: str, heating: str, utility_costs: dict, heating_costs: dict) -> int:
    """The default assumption for one utility when its amount is unknown.
    ogrzewanie is special-cased on the `heating` type (core.pipeline.enrich.field_specs
    EnumPL result): district heating (miejskie) is usually already inside
    czynsz, so 0; a known other type (gazowe/elektryczne/kominkowe/inne)
    routinely costs real money on top, so a nonzero guess; an UNKNOWN type
    assumes nothing at all, rather than guessing blind on both the type and
    its cost at once."""
    if u == "ogrzewanie":
        from core.domain.costs import MISSING_INFO
        if heating and heating not in (MISSING_INFO, "miejskie"):
            return heating_costs.get(heating, 0)
        return 0
    return utility_costs.get(u, 0)


def extra_monthly_costs(breakdown: dict | None, heating: str = "",
                         utility_costs: dict | None = None,
                         heating_costs: dict | None = None) -> tuple[int | None, bool]:
    """Returns (extra_monthly_zl, estimated) - the sum of separately-billed
    utilities, using an assumed default (_assumed_cost) for any utility whose
    amount isn't known. `estimated` is True whenever at least one utility's
    contribution came from an assumption rather than a number stated in the
    ad, so the UI can flag the total as approximate.

    utility_costs/heating_costs default to the factory constants in
    core.infra.config - the real app path (core.domain.costs) passes the user's live
    Settings values instead, so this function itself stays a pure,
    dependency-free calculation that's trivial to unit test."""
    if utility_costs is None:
        from core.infra.config import ASSUMED_UTILITY_COSTS
        utility_costs = ASSUMED_UTILITY_COSTS
    if heating_costs is None:
        from core.infra.config import ASSUMED_HEATING_COST_BY_TYPE
        heating_costs = ASSUMED_HEATING_COST_BY_TYPE
    if not breakdown or not breakdown.get("utilities"):
        return None, False
    total = 0
    estimated = False
    for u in UTILITIES:
        entry = breakdown["utilities"].get(u, {"status": "brak_informacji"})
        status = entry.get("status")
        if status == "osobno":
            total += entry["amount"]
        elif status in ("osobno_bez_kwoty", "brak_informacji"):
            assumed = _assumed_cost(u, heating, utility_costs, heating_costs)
            total += assumed
            if assumed > 0:
                estimated = True
        # w_czynszu and polaczone_z_gazem contribute 0 - the latter's cost is
        # already counted once, under gaz's own "osobno" amount
    return total, estimated


def _join_pl(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " i " + items[-1]


def fees_note_from_breakdown(breakdown: dict | None, heating: str = "",
                              utility_costs: dict | None = None,
                              heating_costs: dict | None = None) -> str:
    """Builds the Polish `fees_note` sentence(s) shown to the user, entirely
    from the validated breakdown - the AI never writes this text directly,
    so wording is always consistent across listings.

    Utilities with nothing known are split by whether we're actually
    assuming a real cost for them (_assumed_cost > 0) or not: lumping
    "founded 0 zł, 0 zł, 100 zł, 50 zł" into one sentence for a mix of
    genuinely-free-to-assume and real-cost utilities read as noise. ogrzewanie
    is dropped from the "nothing known" list entirely when the heating type
    itself is unknown - there's nothing useful to say about a cost for an
    unknown heating type. When validate_breakdown folded ogrzewanie into gaz
    (same gas bill answered twice, see its docstring), ogrzewanie doesn't get
    its own sentence at all - the gaz line is annotated instead."""
    if not breakdown or not breakdown.get("utilities"):
        return ""
    if utility_costs is None:
        from core.infra.config import ASSUMED_UTILITY_COSTS
        utility_costs = ASSUMED_UTILITY_COSTS
    if heating_costs is None:
        from core.infra.config import ASSUMED_HEATING_COST_BY_TYPE
        heating_costs = ASSUMED_HEATING_COST_BY_TYPE

    from core.domain.costs import MISSING_INFO

    utilities = breakdown["utilities"]
    included = [u for u in UTILITIES if utilities.get(u, {}).get("status") == "w_czynszu"]
    with_amount = [u for u in UTILITIES if utilities.get(u, {}).get("status") == "osobno"]
    unclear = [u for u in UTILITIES if utilities.get(u, {}).get("status") in ("osobno_bez_kwoty", "brak_informacji")]
    if "ogrzewanie" in unclear and heating in ("", MISSING_INFO):
        unclear.remove("ogrzewanie")

    unclear_zero = [u for u in unclear if _assumed_cost(u, heating, utility_costs, heating_costs) == 0]
    unclear_nonzero = [u for u in unclear if _assumed_cost(u, heating, utility_costs, heating_costs) > 0]

    gas_heating_merged = utilities.get("ogrzewanie", {}).get("status") == "polaczone_z_gazem"

    sentences = []
    if included:
        sentences.append(f"Czynsz obejmuje {_join_pl([LABELS_PL[u] for u in included])}.")
    if with_amount:
        parts = [
            f"{LABELS_PL_NOM[u]} {utilities[u]['amount']} zł/mc" + (" (obejmuje też ogrzewanie)" if u == "gaz" and gas_heating_merged else "")
            for u in with_amount
        ]
        sentences.append(f"Osobno płatne: {_join_pl(parts)}.")
    if unclear_zero:
        sentences.append(f"Brak informacji o koszcie: {_join_pl([LABELS_PL_NOM[u] for u in unclear_zero])}.")
    if unclear_nonzero:
        names = _join_pl([LABELS_PL_NOM[u] for u in unclear_nonzero])
        assumed = _join_pl([f"{_assumed_cost(u, heating, utility_costs, heating_costs)} zł" for u in unclear_nonzero])
        verb = "wynoszą" if len(unclear_nonzero) > 1 else "wynosi"
        sentences.append(f"Brak informacji o koszcie: {names} - przyjęto szacunkowo, że {verb} {assumed}.")
    return " ".join(sentences)
