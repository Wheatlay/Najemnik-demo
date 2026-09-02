"""
The drawer's "Co dalej?" block (templates/partials/_next_step.html): the
fields the *next* action needs, surfaced at the top of the panel as status
advances through a search.

Deliberately additive rather than a reordering - the groups below never move,
so these tests check what appears, not where anything went.
"""
from sqlmodel import Session

from core.models import Listing, Status


def _seed(db, user_id, **overrides) -> str:
    defaults = dict(url="https://example.com/1", title="Testowe", rent_owner=2000,
                    czynsz_admin=500, area_m2=45.0, rooms=2, phone="500100200")
    defaults.update(overrides)
    with Session(db.get_engine()) as session:
        listing = Listing(user_id=user_id, **defaults)
        session.add(listing)
        session.commit()
        return listing.id


def _drawer(client, lid):
    return client.get(f"/listings/{lid}/drawer").text


def test_no_prompt_before_anything_is_decided(client, db, user):
    """Nowe means the user hasn't judged the listing yet - a "what's next"
    prompt there would be noise, not guidance."""
    lid = _seed(db, user.id, status=Status.NOWE)
    assert "Co dalej" not in _drawer(client, lid)


def test_reviewed_listing_surfaces_the_phone(client, db, user):
    lid = _seed(db, user.id, status=Status.PRZEJRZANE)
    html = _drawer(client, lid)
    assert "Co dalej: zadzwoń" in html
    assert "500 100 200" in html or "500100200" in html


def test_reviewed_listing_without_a_phone_says_so(client, db, user):
    lid = _seed(db, user.id, status=Status.PRZEJRZANE, phone="")
    html = _drawer(client, lid)
    assert "Co dalej: zadzwoń" in html
    assert "nie podało numeru telefonu" in html


def test_booked_viewing_surfaces_the_date_field(client, db, user):
    lid = _seed(db, user.id, status=Status.UMOWIONE)
    html = _drawer(client, lid)
    assert "Co dalej: idź obejrzeć" in html
    assert "termin_ogledzin" in html


def test_termin_field_is_not_rendered_twice(client, db, user):
    """It used to live in the status card too; two inputs bound to the same
    field would race each other on the drawer re-render."""
    lid = _seed(db, user.id, status=Status.UMOWIONE)
    assert _drawer(client, lid).count('"key": "termin_ogledzin"') == 1


def test_viewed_listing_surfaces_the_ratings(client, db, user):
    lid = _seed(db, user.id, status=Status.OBEJRZANE)
    assert "Co dalej: oceń" in _drawer(client, lid)


def test_rejected_listing_gets_no_prompt(client, db, user):
    lid = _seed(db, user.id, status=Status.ODRZUCONE)
    assert "Co dalej" not in _drawer(client, lid)


def test_phone_is_not_shown_at_the_top_before_it_is_needed(client, db, user):
    """A brand-new listing shouldn't lead with a phone number - nothing has
    been decided yet, and calling isn't the next action.

    Asserts on the "📞 <number>" chip, not the bare digits: the number still
    legitimately renders inside the (collapsed) Kontakt field, where it's
    editable like any other field."""
    lid = _seed(db, user.id, status=Status.NOWE)
    assert "📞 500 100 200" not in _drawer(client, lid)


def test_phone_appears_once_when_calling_is_the_next_step(client, db, user):
    """It used to render twice on one screen for a Przejrzane listing: once
    in the permanent action row and once in "Co dalej: zadzwoń". Only the
    contextual one survives."""
    lid = _seed(db, user.id, status=Status.PRZEJRZANE)
    html = _drawer(client, lid)
    assert html.count("📞 500 100 200") == 1
