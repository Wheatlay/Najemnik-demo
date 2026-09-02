from core.domain import fields


def test_no_duplicate_keys():
    keys = [f.key for f in fields.FIELDS]
    assert len(keys) == len(set(keys))


def test_computed_fields_not_editable():
    for f in fields.FIELDS:
        if f.computed:
            assert not f.editable


def test_money_fields_declare_which_total_they_feed():
    for f in fields.FIELDS:
        if f.type == "smart_money":
            assert f.smart_kind in ("monthly", "one_time"), f.key


def test_money_field_registry_matches_the_value_module():
    """Two lists of the same six fields would drift; this is the check that
    catches it. money_field owns the labels and clamps, fields.py owns the
    UI, and they have to name the same set."""
    from core.domain.money_field import MONEY_FIELDS
    registry = {f.key for f in fields.FIELDS if f.type == "smart_money"}
    assert registry == set(MONEY_FIELDS)


def test_select_enum_fields_list_their_options():
    for f in fields.FIELDS:
        if f.type == "select_enum":
            assert f.options, f.key


def test_gallery_card_is_small_fixed_set():
    card_fields = fields.fields_in("gallery_card")
    assert len(card_fields) <= 8


def test_filterable_fields_have_filterable_flag():
    for f in fields.filterable_fields():
        assert f.filterable is True


def test_is_editable_rejects_computed():
    assert fields.is_editable("suma_miesieczna") is False
    assert fields.is_editable("rent_owner") is True
    assert fields.is_editable("nonexistent") is False


def test_every_field_has_a_valid_source():
    valid = {"scraped", "ai_verify", "ai_extract", "manual", "derived"}
    for f in fields.FIELDS:
        assert f.source in valid


def test_every_ai_field_has_a_field_spec():
    from core.pipeline.enrich.field_specs import FIELD_SPECS_BY_KEY
    for f in fields.FIELDS:
        if f.source in ("ai_verify", "ai_extract") and f.key != "notes_extra":
            assert f.key in FIELD_SPECS_BY_KEY, f"{f.key} has no FieldSpec"


def test_tag_vocabulary_has_no_duplicates():
    assert len(fields.TAG_VOCABULARY) == len(set(fields.TAG_VOCABULARY))


def test_computed_and_derived_are_not_the_same_thing():
    """They read alike and used to be spelled alike, which made the one legal
    mismatch look like a typo.

    - FieldDef.computed  -> recalculated on read, never stored
    - source="derived"   -> value comes from other fields, no pipeline writes it

    Everything computed is necessarily derived. The converse doesn't hold:
    fees_note is built from cost_breakdown and then *stored*, so it is
    derived but not computed. That's the only such field; if another appears,
    decide deliberately rather than inheriting this exception.
    """
    from core.domain.fields import FIELDS

    for f in FIELDS:
        if f.computed:
            assert f.source == "derived", f"{f.key}: computed but source={f.source}"

    derived_but_stored = [f.key for f in FIELDS if f.source == "derived" and not f.computed]
    assert derived_but_stored == ["fees_note"], derived_but_stored
