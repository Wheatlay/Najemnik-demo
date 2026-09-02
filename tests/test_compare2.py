"""
/porownaj2 - the default compare view. Selection happens in the gallery
("Tryb porownania"), so this page only ever renders the focused panel for
2-4 already-chosen listings; /porownaj's 25-column table stays reachable
behind a link.
"""
from sqlmodel import Session

from core.models import Listing


def _seed(db, user_id, **overrides) -> str:
    defaults = dict(url="https://example.com/1", title="Testowe", rent_owner=2000,
                    czynsz_admin=500, area_m2=45.0, rooms=2)
    defaults.update(overrides)
    with Session(db.get_engine()) as session:
        listing = Listing(user_id=user_id, **defaults)
        session.add(listing)
        session.commit()
        return listing.id


def test_shows_the_focused_panel_for_a_valid_selection(client, db, user):
    a = _seed(db, user.id, url="https://example.com/a", title="Alfa")
    b = _seed(db, user.id, url="https://example.com/b", title="Beta")
    html = client.get(f"/porownaj2?ids={a},{b}").text
    assert "Alfa" in html and "Beta" in html


def test_prompts_for_a_selection_when_none_given(client, db, user):
    _seed(db, user.id)
    html = client.get("/porownaj2").text
    assert "Wybierz mieszkania do porównania" in html


def test_has_no_close_button_when_it_is_the_whole_page(client, db, user):
    """The ✕ empties #compare-focus, which is right inside the full table
    and would leave a blank screen here."""
    a = _seed(db, user.id, url="https://example.com/a")
    b = _seed(db, user.id, url="https://example.com/b")
    html = client.get(f"/porownaj2?ids={a},{b}").text
    assert "compare-focus').innerHTML = ''" not in html


def test_ignores_another_users_listing_ids(client, client_b, db, user, user_b):
    mine = _seed(db, user.id, url="https://example.com/mine", title="Moje")
    theirs = _seed(db, user_b.id, url="https://example.com/theirs", title="Cudze")
    html = client.get(f"/porownaj2?ids={mine},{theirs}").text
    assert "Cudze" not in html
    # One valid listing is not a comparison - falls back to the prompt.
    assert "Wybierz mieszkania do porównania" in html
