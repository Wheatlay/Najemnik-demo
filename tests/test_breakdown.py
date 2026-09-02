from core.domain import breakdown


def test_validate_breakdown_fills_all_utilities():
    result = breakdown.validate_breakdown({"utilities": {}})
    assert set(result["utilities"].keys()) == set(breakdown.UTILITIES)
    assert all(v["status"] == "brak_informacji" for v in result["utilities"].values())


def test_validate_breakdown_clamps_unknown_status():
    raw = {"utilities": {"woda": {"status": "coś dziwnego"}}}
    result = breakdown.validate_breakdown(raw)
    assert result["utilities"]["woda"]["status"] == "brak_informacji"


def test_validate_breakdown_osobno_requires_sane_amount():
    raw = {"utilities": {"prad": {"status": "osobno", "amount": 999999}}}
    result = breakdown.validate_breakdown(raw)
    assert result["utilities"]["prad"]["status"] == "osobno_bez_kwoty"

    raw = {"utilities": {"prad": {"status": "osobno", "amount": 150}}}
    result = breakdown.validate_breakdown(raw)
    assert result["utilities"]["prad"] == {"status": "osobno", "amount": 150}


def test_extra_monthly_costs_sums_and_assumes_defaults():
    raw = breakdown.validate_breakdown({"utilities": {
        "prad": {"status": "osobno", "amount": 200},
        "gaz": {"status": "osobno_bez_kwoty"},
        "internet": {"status": "brak_informacji"},
        "woda": {"status": "w_czynszu"},
        "ogrzewanie": {"status": "w_czynszu"},
        "smieci": {"status": "w_czynszu"},
    }})
    extra, estimated = breakdown.extra_monthly_costs(raw)
    assert extra == 200 + 100 + 50  # prad stated + gaz assumed + internet assumed
    assert estimated is True


def test_extra_monthly_costs_fully_included_no_estimate():
    raw = breakdown.validate_breakdown({"utilities": {
        u: {"status": "w_czynszu"} for u in breakdown.UTILITIES
    }})
    extra, estimated = breakdown.extra_monthly_costs(raw)
    assert extra == 0
    assert estimated is False


def test_extra_monthly_costs_none_breakdown():
    assert breakdown.extra_monthly_costs(None) == (None, False)


def test_fees_note_included_and_separate():
    raw = breakdown.validate_breakdown({"utilities": {
        "woda": {"status": "w_czynszu"}, "ogrzewanie": {"status": "w_czynszu"},
        "smieci": {"status": "w_czynszu"}, "prad": {"status": "osobno_bez_kwoty"},
        "gaz": {"status": "osobno_bez_kwoty"}, "internet": {"status": "brak_informacji"},
    }})
    note = breakdown.fees_note_from_breakdown(raw)
    assert "Czynsz obejmuje wodę, ogrzewanie i śmieci." in note
    assert "przyjęto szacunkowo" in note
    assert "50 zł" in note  # internet assumption
    assert "Brak informacji o koszcie: prąd, gaz i internet" in note


def test_fees_note_empty_breakdown_is_empty_string():
    assert breakdown.fees_note_from_breakdown(None) == ""
    assert breakdown.fees_note_from_breakdown({"utilities": {}}) == ""


# --- misattribution guard (whole-czynsz grabbed as one utility's cost) ----

def test_validate_breakdown_amount_equal_to_czynsz_admin_becomes_w_czynszu():
    raw = {"utilities": {"smieci": {"status": "osobno", "amount": 1045}}}
    result = breakdown.validate_breakdown(raw, czynsz_admin=1045)
    assert result["utilities"]["smieci"] == {"status": "w_czynszu"}


def test_validate_breakdown_amount_equal_to_rent_owner_becomes_brak_informacji():
    raw = {"utilities": {"woda": {"status": "osobno", "amount": 2200}}}
    result = breakdown.validate_breakdown(raw, rent_owner=2200)
    assert result["utilities"]["woda"] == {"status": "brak_informacji"}


def test_validate_breakdown_amount_equal_to_rent_plus_czynsz_becomes_brak_informacji():
    raw = {"utilities": {"woda": {"status": "osobno", "amount": 850}}}
    result = breakdown.validate_breakdown(raw, rent_owner=2200, czynsz_admin=850)
    # 850 matches czynsz_admin exactly - takes the w_czynszu branch first
    assert result["utilities"]["woda"]["status"] in ("w_czynszu", "brak_informacji")


def test_validate_breakdown_plausible_own_amount_kept_even_with_known_costs():
    raw = {"utilities": {"prad": {"status": "osobno", "amount": 180}}}
    result = breakdown.validate_breakdown(raw, czynsz_admin=1045, rent_owner=2200)
    assert result["utilities"]["prad"] == {"status": "osobno", "amount": 180}


def test_validate_breakdown_rejects_amount_above_per_utility_ceiling():
    raw = {"utilities": {"smieci": {"status": "osobno", "amount": 900}}}
    result = breakdown.validate_breakdown(raw)
    assert result["utilities"]["smieci"] == {"status": "osobno_bez_kwoty"}


# --- heating-aware ogrzewanie assumption -----------------------------------

def _breakdown_only_ogrzewanie_unclear() -> dict:
    """All utilities except ogrzewanie pinned to w_czynszu (contribute 0, not
    an estimate) so extra_monthly_costs isolates ogrzewanie's own
    contribution instead of also picking up prad/gaz/internet's baseline
    assumptions."""
    other = {u: {"status": "w_czynszu"} for u in breakdown.UTILITIES if u != "ogrzewanie"}
    return breakdown.validate_breakdown({"utilities": {**other, "ogrzewanie": {"status": "brak_informacji"}}})


def test_ogrzewanie_assumes_zero_when_heating_type_unknown():
    raw = _breakdown_only_ogrzewanie_unclear()
    extra, estimated = breakdown.extra_monthly_costs(raw, heating="brak informacji")
    assert extra == 0
    assert estimated is False


def test_ogrzewanie_assumes_zero_for_miejskie():
    raw = _breakdown_only_ogrzewanie_unclear()
    extra, estimated = breakdown.extra_monthly_costs(raw, heating="miejskie")
    assert extra == 0
    assert estimated is False


def test_ogrzewanie_assumes_nonzero_for_known_other_type():
    raw = _breakdown_only_ogrzewanie_unclear()
    extra, estimated = breakdown.extra_monthly_costs(raw, heating="elektryczne")
    assert extra == 300
    assert estimated is True


def test_fees_note_omits_ogrzewanie_when_heating_unknown():
    raw = breakdown.validate_breakdown({"utilities": {
        "ogrzewanie": {"status": "brak_informacji"}, "prad": {"status": "brak_informacji"},
    }})
    note = breakdown.fees_note_from_breakdown(raw, heating="brak informacji")
    assert "ogrzewanie" not in note
    assert "prąd" in note


def test_fees_note_mentions_ogrzewanie_for_known_non_miejskie_heating():
    raw = breakdown.validate_breakdown({"utilities": {"ogrzewanie": {"status": "brak_informacji"}}})
    note = breakdown.fees_note_from_breakdown(raw, heating="gazowe")
    assert "ogrzewanie" in note
    assert "250 zł" in note


# --- gas heating merge (same bill answered under both ogrzewanie and gaz) -

def test_validate_breakdown_merges_equal_gas_heating_amounts():
    raw = {"utilities": {
        "ogrzewanie": {"status": "osobno", "amount": 400},
        "gaz": {"status": "osobno", "amount": 400},
    }}
    result = breakdown.validate_breakdown(raw, heating="gazowe")
    assert result["utilities"]["ogrzewanie"] == {"status": "polaczone_z_gazem"}
    assert result["utilities"]["gaz"] == {"status": "osobno", "amount": 400}


def test_validate_breakdown_keeps_distinct_gas_heating_amounts_separate():
    """If the ad genuinely states two different figures (e.g. a separate
    electric floor-heating cost on top of gas for cooking), they must NOT be
    merged - only an exact match is the tell of one bill answered twice."""
    raw = {"utilities": {
        "ogrzewanie": {"status": "osobno", "amount": 200},
        "gaz": {"status": "osobno", "amount": 80},
    }}
    result = breakdown.validate_breakdown(raw, heating="gazowe")
    assert result["utilities"]["ogrzewanie"] == {"status": "osobno", "amount": 200}
    assert result["utilities"]["gaz"] == {"status": "osobno", "amount": 80}


def test_validate_breakdown_no_merge_for_non_gas_heating():
    raw = {"utilities": {
        "ogrzewanie": {"status": "osobno", "amount": 400},
        "gaz": {"status": "osobno", "amount": 400},
    }}
    result = breakdown.validate_breakdown(raw, heating="elektryczne")
    assert result["utilities"]["ogrzewanie"] == {"status": "osobno", "amount": 400}


def test_merged_gas_heating_not_double_counted_in_total():
    other = {u: {"status": "w_czynszu"} for u in breakdown.UTILITIES if u not in ("ogrzewanie", "gaz")}
    raw = breakdown.validate_breakdown({"utilities": {
        **other, "ogrzewanie": {"status": "osobno", "amount": 400}, "gaz": {"status": "osobno", "amount": 400},
    }}, heating="gazowe")
    extra, estimated = breakdown.extra_monthly_costs(raw, heating="gazowe")
    assert extra == 400  # not 800
    assert estimated is False


def test_merged_gas_heating_fees_note_mentions_it_once():
    other = {u: {"status": "w_czynszu"} for u in breakdown.UTILITIES if u not in ("ogrzewanie", "gaz")}
    raw = breakdown.validate_breakdown({"utilities": {
        **other, "ogrzewanie": {"status": "osobno", "amount": 400}, "gaz": {"status": "osobno", "amount": 400},
    }}, heating="gazowe")
    note = breakdown.fees_note_from_breakdown(raw, heating="gazowe")
    assert note.count("400 zł") == 1
    assert "obejmuje też ogrzewanie" in note
