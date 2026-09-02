from sqlmodel import Session

from core.models import Listing, Status
from core.domain.queries import apply_filters


def _seed(db, user_id, **overrides) -> str:
    defaults = {"url": "https://example.com/1", "title": "Test", "status": Status.NOWE}
    defaults.update(overrides)
    with Session(db.get_engine()) as session:
        listing = Listing(user_id=user_id, **defaults)
        session.add(listing)
        session.commit()
        return listing.id


def test_odrzucone_hidden_by_default(db, user):
    _seed(db, user.id, url="https://example.com/1", status=Status.NOWE)
    _seed(db, user.id, url="https://example.com/2", status=Status.ODRZUCONE)

    with Session(db.get_engine()) as session:
        results = apply_filters(session, user.id, {})
    assert len(results) == 1
    assert results[0].status == Status.NOWE


def test_odrzucone_shown_when_explicitly_selected(db, user):
    _seed(db, user.id, url="https://example.com/1", status=Status.NOWE)
    _seed(db, user.id, url="https://example.com/2", status=Status.ODRZUCONE)

    class Params(dict):
        def getlist(self, key):
            v = self.get(key)
            return v if isinstance(v, list) else ([v] if v else [])

    with Session(db.get_engine()) as session:
        results = apply_filters(session, user.id, Params(status=["Odrzucone"]))
    assert len(results) == 1
    assert results[0].status == Status.ODRZUCONE


def test_odrzucone_included_when_status_filter_includes_it_alongside_others(db, user):
    _seed(db, user.id, url="https://example.com/1", status=Status.NOWE)
    _seed(db, user.id, url="https://example.com/2", status=Status.ODRZUCONE)

    class Params(dict):
        def getlist(self, key):
            v = self.get(key)
            return v if isinstance(v, list) else ([v] if v else [])

    with Session(db.get_engine()) as session:
        results = apply_filters(session, user.id, Params(status=["Nowe", "Odrzucone"]))
    assert len(results) == 2


def test_entry_price_filter_uses_suma_wejscia(db, user):
    _seed(db, user.id, url="https://example.com/1", deposit={"status": "tak", "amount": 1000})
    _seed(db, user.id, url="https://example.com/2", deposit={"status": "tak", "amount": 5000})

    with Session(db.get_engine()) as session:
        results = apply_filters(session, user.id, {"entry_price_min": "2000"})
    assert len(results) == 1
    assert results[0].deposit["amount"] == 5000


def test_parking_filter_distinguishes_absent_from_unknown(db, user):
    """The distinction the old startswith("brak") parsing kept fumbling: a
    confirmed "no parking" is an answer, "nie wiadomo" is not - so the
    "false" filter must return the first and never the second."""
    _seed(db, user.id, url="https://example.com/1", parking={"status": "tak", "amount": 150})
    _seed(db, user.id, url="https://example.com/2", parking={"status": "nie"})
    _seed(db, user.id, url="https://example.com/3", parking={"status": "brak_informacji"})

    with Session(db.get_engine()) as session:
        present = apply_filters(session, user.id, {"parking": "true"})
        absent = apply_filters(session, user.id, {"parking": "false"})
    assert [l.url for l in present] == ["https://example.com/1"]
    assert [l.url for l in absent] == ["https://example.com/2"]


def test_malformed_numeric_and_date_params_degrade_to_no_filter(db, user):
    """A hand-edited URL or stale bookmark with garbage in a numeric/date
    filter param must not 500 the whole page - it should behave as if that
    one filter wasn't set."""
    _seed(db, user.id, url="https://example.com/1")
    _seed(db, user.id, url="https://example.com/2")

    with Session(db.get_engine()) as session:
        results = apply_filters(session, user.id, {
            "price_min": "abc", "price_max": "??", "m2_price_min": "x",
            "entry_price_min": "y", "rooms_min": "z", "area_min": "w",
            "ocena_wygladu_min": "n", "ocena_glosnosci_otoczenia_min": "n",
            "available_by": "not-a-date",
        })
    assert len(results) == 2
