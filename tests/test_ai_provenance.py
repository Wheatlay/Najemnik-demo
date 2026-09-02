"""AI provenance: which fields get credited to the model, what receipt they
carry, and how a user edit revokes both."""
from unittest.mock import patch

from sqlmodel import Session

from core.domain import display
from core.domain.fields import FIELDS_BY_KEY
from core.models import Listing
from core.pipeline.enrich.field_specs import grounded_quote
from core.pipeline.enrich.pipeline import run_enrichment

# The ad text the model must be able to quote from for a claim to count.
RAW_TEXT = (
    "2 pokoje Koszutka. Czynsz do właściciela 2100 zł, opłata administracyjna 1045 zł. "
    "Oferta bezpośrednio od właściciela, bez pośredników. "
    "Do mieszkania przynależy miejsce w garażu podziemnym."
)


def _save(db, user_id, **overrides) -> str:
    defaults = dict(
        url="https://example.com/prov", title="2 pokoje Koszutka", city="Katowice",
        rent_owner=2100, czynsz_admin=1045, raw_text=RAW_TEXT,
    )
    defaults.update(overrides)
    with Session(db.get_engine()) as session:
        listing = Listing(user_id=user_id, **defaults)
        session.add(listing)
        session.commit()
        session.refresh(listing)
        return listing.id


def _get(db, listing_id) -> Listing:
    with Session(db.get_engine()) as session:
        return session.get(Listing, listing_id)


# --- grounded_quote: the receipt is only as good as its grounding ---------

class _FakeListing:
    raw_text = RAW_TEXT


def test_grounded_quote_returns_a_quote_that_is_really_in_the_ad():
    raw = {"cytat": "bez pośredników", "status": "prywatnie"}
    assert grounded_quote(raw, _FakeListing()) == "bez pośredników"


def test_grounded_quote_rejects_a_quote_the_model_invented():
    """The whole point: a receipt for text that isn't in the ad is worse than
    no receipt, because it looks like proof."""
    raw = {"cytat": "zwierzęta mile widziane", "status": "prywatnie"}
    assert grounded_quote(raw, _FakeListing()) is None


def test_grounded_quote_returns_none_when_the_prompt_asked_for_no_quote():
    assert grounded_quote({"kwota": 1045}, _FakeListing()) is None
    assert grounded_quote({}, _FakeListing()) is None
    assert grounded_quote(None, _FakeListing()) is None


# --- ai_provenance: who gets credit --------------------------------------

def test_ai_extract_field_with_a_value_is_credited_to_ai(db, user):
    listing = _get(db, _save(db, user.id, pets_allowed=True,
                             ai_evidence={"pets_allowed": None}))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["pets_allowed"]) is not None


def test_scraped_field_is_never_credited_to_ai(db, user):
    listing = _get(db, _save(db, user.id))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["area_m2"]) is None


def test_scraped_verify_field_is_not_credited_to_ai(db, user):
    """czynsz_admin came from the portal, so nothing recorded authorship for
    it - badging it would credit the wrong source."""
    listing = _get(db, _save(db, user.id, czynsz_admin=1045))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["czynsz_admin"]) is None


def test_gap_filled_verify_field_is_credited_to_ai(db, user):
    """The case FieldDef.source alone gets wrong: scraping found no kaucja,
    so the model wrote one - and "wymagana, kwota nie podana" is the model's
    phrasing, never a portal's. It has to carry the badge even though
    `deposit` is declared ai_verify."""
    listing = _get(db, _save(db, user.id, deposit={"status": "tak"},
                             ai_evidence={"deposit": None}))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["deposit"]) == {"quote": None}


def test_field_the_model_never_wrote_is_not_credited(db, user):
    listing = _get(db, _save(db, user.id, district=""))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["district"]) is None


def test_manual_field_is_never_credited_even_if_recorded(db, user):
    """Belt and braces: notatki are the user's by definition, so a stray
    authorship entry must not put an AI badge on them."""
    listing = _get(db, _save(db, user.id, notatki="moje", ai_evidence={"notatki": "x"}))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["notatki"]) is None


def test_quote_is_surfaced_when_one_was_recorded(db, user):
    listing = _get(db, _save(
        db, user.id, pets_allowed=True, ai_evidence={"pets_allowed": "bez pośredników"}))
    prov = display.ai_provenance(listing, FIELDS_BY_KEY["pets_allowed"])
    assert prov["quote"] == "bez pośredników"


def test_credited_without_a_quote_when_none_was_recorded(db, user):
    """Every prompt asks for a quote now, but the model may still answer with
    a null or invented one - the badge stays truthful ("a model wrote this")
    and simply has no fragment to show."""
    listing = _get(db, _save(db, user.id, pets_allowed=True,
                             ai_evidence={"pets_allowed": None}))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["pets_allowed"]) == {"quote": None}


def test_user_edited_field_loses_both_badge_and_quote(db, user):
    listing = _get(db, _save(
        db, user.id, pets_allowed=True,
        ai_evidence={"pets_allowed": "bez pośredników"}, edited_fields=["pets_allowed"]))
    assert display.ai_provenance(listing, FIELDS_BY_KEY["pets_allowed"]) is None


# --- the edit route revokes credit ---------------------------------------

def test_patching_a_field_drops_its_evidence_and_marks_it_edited(client, db, user):
    lid = _save(db, user.id, pets_allowed=True,
                ai_evidence={"pets_allowed": "bez pośredników", "district": "Koszutka"})

    resp = client.patch(f"/listings/{lid}/field", data={"key": "pets_allowed", "value": "false"})
    assert resp.status_code == 200

    listing = _get(db, lid)
    assert "pets_allowed" not in listing.ai_evidence
    assert "pets_allowed" in listing.edited_fields
    # Only that field's receipt is revoked, not the whole listing's.
    assert listing.ai_evidence["district"] == "Koszutka"
    assert display.ai_provenance(listing, FIELDS_BY_KEY["pets_allowed"]) is None


def test_reenrichment_does_not_take_back_a_user_edited_field(db, user):
    """A field the user corrected must survive the next AI run - otherwise
    the badge disappearing is meaningless, since the value returns anyway."""
    lid = _save(db, user.id, district="Moja Poprawka", edited_fields=["district"])

    def responder(prompt, timeout=None):
        if "wartosc" in prompt:
            return {"wartosc": "Koszutka"}
        if '"answer": "tak"}' in prompt:
            return {"answer": "tak"}
        if "status" in prompt:
            return {"status": "brak_informacji"}
        return {"kwota": None}

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        run_enrichment(lid)

    listing = _get(db, lid)
    assert listing.district == "Moja Poprawka"
    assert "district" not in listing.ai_evidence


def test_enrichment_records_a_grounded_quote(db, user):
    """End to end: an evidence-first answer whose quote is really in the ad
    ends up on the row as that field's receipt."""
    lid = _save(db, user.id)

    def responder(prompt, timeout=None):
        if "cytat" in prompt and "pośrednictwa" in prompt:
            return {"cytat": "bez pośredników", "status": "prywatnie"}
        if "cytat" in prompt:
            return {"cytat": None, "status": "brak informacji"}
        if "wartosc" in prompt:
            return {"wartosc": None}
        if '"answer": "tak"}' in prompt:
            return {"answer": "tak"}
        if "status" in prompt:
            return {"status": "brak_informacji"}
        return {"kwota": None}

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        run_enrichment(lid)

    assert _get(db, lid).ai_evidence.get("posrednik") == "bez pośredników"


# --- level A: every AI-authored field asks for a receipt ------------------

def _prompt_for(key):
    from core.pipeline.enrich.field_specs import FIELD_SPECS_BY_KEY, build_extract_prompt

    class _L:
        title, city, district = "2 pokoje", "Katowice", "Koszutka"
        raw_text = RAW_TEXT
        created_at = None
        rent_owner = 2100
    return build_extract_prompt(_L(), FIELD_SPECS_BY_KEY[key])


def test_every_ai_authored_field_asks_the_model_to_quote():
    """The badge promises a receipt; a field whose prompt never asks for a
    quote can never produce one, so it would badge with a permanent "no
    evidence recorded". Kept as a registry-wide sweep so a field added later
    can't quietly opt out."""
    from core.domain.fields import FIELDS
    from core.pipeline.enrich.field_specs import FIELD_SPECS_BY_KEY

    ai_authored = [f.key for f in FIELDS
                   if f.source == "ai_extract" and f.key in FIELD_SPECS_BY_KEY]
    assert ai_authored, "registry sanity: expected some ai_extract fields"
    missing = [k for k in ai_authored if "cytat" not in _prompt_for(k)]
    assert not missing, f"these fields can never show evidence: {missing}"


def test_quote_request_does_not_change_what_counts_as_a_valid_answer():
    """Level A is additive: schemas read their own keys and ignore "cytat",
    so a model that omits it (or invents one) still yields the same stored
    value it did before. Level B - rejecting ungrounded answers - is a
    separate change and deliberately isn't in effect for these fields."""
    from core.pipeline.enrich.field_specs import DatePL, EnumPL, TriStateBool, TriStateMoney

    assert TriStateBool().validate({"answer": "tak"}) is True
    assert TriStateBool().validate({"cytat": "wymyślone", "answer": "tak"}) is True

    assert TriStateMoney("prowizja").validate({"status": "nie"}) == {"status": "nie"}
    assert TriStateMoney("prowizja").validate({"cytat": None, "status": "nie"}) == {"status": "nie"}

    assert EnumPL(values=("miejskie",)).validate({"cytat": "x", "wartosc": "miejskie"}) == "miejskie"
    assert DatePL().validate({"cytat": "x", "data": "2026-09-01"}).isoformat() == "2026-09-01"


def test_district_is_told_to_skip_the_quote_when_using_the_header():
    """_quote_in_text only searches raw_text, so a header-derived quote would
    be silently dropped - the prompt asks for null there instead."""
    assert "nagłówka" in _prompt_for("district")


def test_demo_fixtures_carry_quotes_that_are_really_in_their_ad_text():
    """The tour points at the ✨ AI badge and tells the user to hover for the
    fragment, so the bundled examples must actually have one. Nothing
    re-verifies a stored quote at render time - editing a demo's raw_text
    without updating ai_evidence would silently show a fragment that is no
    longer in the ad, which is exactly the thing the badge promises can't
    happen."""
    import json

    from core.infra.config import BASE_DIR

    entries = json.loads((BASE_DIR / "fixtures" / "demo_listings.json").read_text(encoding="utf-8"))
    assert entries, "expected bundled demo listings"

    class _L:
        def __init__(self, text):
            self.raw_text = text

    ungrounded = []
    for entry in entries:
        listing = _L(entry.get("raw_text", ""))
        for key, quote in (entry.get("ai_evidence") or {}).items():
            # A None value is a legitimate "authored, but no quote recorded";
            # only an actual fragment has to be findable in the ad.
            if quote is not None and grounded_quote({"cytat": quote}, listing) is None:
                ungrounded.append((entry["url"], key))
    assert not ungrounded, f"demo quotes not found in their own raw_text: {ungrounded}"


def test_the_tour_listing_can_demonstrate_the_evidence_hover():
    """demo-2 is the listing the tour walks through, and its pets_allowed
    step promises a visible quote."""
    import json

    from core.infra.config import BASE_DIR

    entries = json.loads((BASE_DIR / "fixtures" / "demo_listings.json").read_text(encoding="utf-8"))
    demo2 = next(e for e in entries if e["url"].endswith("listing-2"))
    assert demo2["ai_evidence"].get("pets_allowed")


def test_demo_fixtures_do_not_credit_the_model_for_portal_data(client, db, user):
    """The badge has to be discriminating to mean anything. Odstępne, czynsz
    and a kaucja stated outright as a number come from the portal - if the
    examples badge those, the badge just means "a field" and teaches nothing.
    demo-1's kaucja is the deliberate exception: scraping found none, so the
    model wrote "wymagana, kwota nie podana"."""
    from sqlmodel import select

    client.post("/demo/wczytaj")
    with Session(db.get_engine()) as session:
        demo = session.exec(
            select(Listing).where(Listing.user_id == user.id, Listing.is_demo == True)
        ).all()

    for listing in demo:
        assert "rent_owner" not in listing.ai_evidence
        assert "czynsz_admin" not in listing.ai_evidence
        numeric_deposit = bool(listing.deposit and listing.deposit.get("amount"))
        assert ("deposit" in listing.ai_evidence) is not numeric_deposit, listing.title

    inferred = [listing for listing in demo if "deposit" in listing.ai_evidence]
    assert len(inferred) == 1


def test_enrichment_credits_a_gap_filled_verify_field(db, user):
    """End to end for the kaucja case: no scraped deposit, model says it's
    required without an amount, row records the authorship."""
    lid = _save(db, user.id, deposit=None)

    def responder(prompt, timeout=None):
        if "kaucja" in prompt:
            return {"cytat": None, "status": "tak", "kwota": None}
        if "cytat" in prompt:
            return {"cytat": None, "status": "brak informacji"}
        if "wartosc" in prompt:
            return {"wartosc": None}
        if '"answer"' in prompt:
            return {"answer": "brak informacji"}
        if "status" in prompt:
            return {"status": "brak_informacji"}
        return {"kwota": None}

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        run_enrichment(lid)

    listing = _get(db, lid)
    assert listing.deposit == {"status": "tak"}
    assert "deposit" in listing.ai_evidence
    assert display.ai_provenance(listing, FIELDS_BY_KEY["deposit"]) == {"quote": None}


def test_enrichment_does_not_credit_a_verify_field_it_left_alone(db, user):
    """The mirror case: a scraped kaucja is never re-asked, so nothing claims
    authorship of it and it stays unbadged."""
    lid = _save(db, user.id, deposit={"status": "tak", "amount": 4200})

    def responder(prompt, timeout=None):
        if "cytat" in prompt:
            return {"cytat": None, "status": "brak informacji"}
        if "wartosc" in prompt:
            return {"wartosc": None}
        if '"answer"' in prompt:
            return {"answer": "brak informacji"}
        if "status" in prompt:
            return {"status": "brak_informacji"}
        return {"kwota": None}

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=responder):
        run_enrichment(lid)

    listing = _get(db, lid)
    assert listing.deposit == {"status": "tak", "amount": 4200}
    assert "deposit" not in listing.ai_evidence


# --- the drawer's money control: the kwota box doubles as a notatka box ----

def test_field_row_renders_the_money_control(client, db, user):
    lid = _save(db, user.id, prowizja={"status": "tak", "amount": 800})
    html = client.get(f"/listings/{lid}/drawer").text
    assert "moneyField(" in html
    assert 'data-field="prowizja"' in html

def test_amount_box_stores_a_number_as_amount(client, db, user):
    lid = _save(db, user.id, prowizja=None)
    client.patch(f"/listings/{lid}/field", data={
        "key": "prowizja", "render": "drawer", "status": "tak", "amount": "800", "note": "",
    })
    assert _get(db, lid).prowizja == {"status": "tak", "amount": 800}


def test_amount_box_falls_back_to_a_note_when_not_a_number(client, db, user):
    """F5's kwota box strips non-digits client-side, but the server can't
    trust that - a hand-crafted request or a future variant might still send
    text as "amount", and it must become the note instead of being dropped."""
    lid = _save(db, user.id, prowizja=None)
    client.patch(f"/listings/{lid}/field", data={
        "key": "prowizja", "render": "drawer", "status": "tak", "amount": "50% czynszu", "note": "",
    })
    assert _get(db, lid).prowizja == {"status": "tak", "note": "50% czynszu"}


def test_explicit_note_is_not_overridden_by_a_numeric_amount(client, db, user):
    """Amount and notatka are two separate boxes in F5 - both must survive a
    save together."""
    lid = _save(db, user.id, prowizja=None)
    client.patch(f"/listings/{lid}/field", data={
        "key": "prowizja", "render": "drawer", "status": "tak",
        "amount": "800", "note": "do potwierdzenia",
    })
    assert _get(db, lid).prowizja == {"status": "tak", "amount": 800, "note": "do potwierdzenia"}
