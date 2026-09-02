from dataclasses import dataclass

from core.domain import costs


@dataclass
class FakeListing:
    user_id: str = "dummy-user-id"
    rent_owner: int | None = None
    czynsz_admin: int | None = None
    other_costs: int | None = None
    heating: str = ""
    parking: dict | None = None
    piwnica: dict | None = None
    deposit: dict | None = None
    notariusz: dict | None = None
    prowizja: dict | None = None
    oc: dict | None = None
    area_m2: float | None = None
    cost_breakdown: dict | None = None


def test_suma_miesieczna_basic():
    l = FakeListing(rent_owner=2100, czynsz_admin=1045, other_costs=100)
    assert costs.suma_miesieczna(l) == 3245


def test_suma_miesieczna_skips_a_confirmed_absence():
    l = FakeListing(rent_owner=2000, parking={"status": "nie"})
    assert costs.suma_miesieczna(l) == 2000


def test_suma_miesieczna_includes_piwnica():
    l = FakeListing(rent_owner=2000, piwnica={"status": "tak", "amount": 50})
    assert costs.suma_miesieczna(l) == 2050


def test_suma_miesieczna_all_null_is_none():
    l = FakeListing()
    assert costs.suma_miesieczna(l) is None


def test_cena_za_m2():
    l = FakeListing(rent_owner=2100, czynsz_admin=1045, area_m2=52.0)
    assert costs.cena_za_m2(l) == round(3145 / 52.0)


def test_cena_za_m2_missing_area():
    l = FakeListing(rent_owner=2100)
    assert costs.cena_za_m2(l) is None


def test_suma_wejscia():
    l = FakeListing(deposit={"status": "tak", "amount": 4500},
                    notariusz={"status": "tak"},
                    prowizja={"status": "tak", "amount": 500})
    assert costs.suma_wejscia(l) == 5000


def test_suma_wejscia_excludes_a_confirmed_cost_with_no_amount():
    """"There is a deposit, amount unstated" is real information but not a
    number - it must not silently count as zero."""
    l = FakeListing(deposit={"status": "tak"}, prowizja={"status": "tak", "amount": 500})
    assert costs.suma_wejscia(l) == 500


def test_suma_wejscia_includes_oc():
    l = FakeListing(deposit={"status": "tak", "amount": 4500},
                    oc={"status": "tak", "amount": 150})
    assert costs.suma_wejscia(l) == 4650


def test_suma_wejscia_all_null_is_none():
    l = FakeListing()
    assert costs.suma_wejscia(l) is None


def _use_default_settings(monkeypatch):
    """_extra_monthly reads assumed utility costs from the live Settings row
    (core.domain.settings.get_settings) so /ustawienia can change them at runtime -
    stubbing it to a plain default Settings() keeps these tests offline and
    independent of whatever's in the real DB, matching this module's own
    "always computed on read" purity elsewhere."""
    import core.domain.settings as settings_module
    from core.models import Settings
    monkeypatch.setattr(settings_module, "get_settings", lambda user_id: Settings(user_id=user_id))


def test_suma_miesieczna_uses_breakdown_when_present(monkeypatch):
    _use_default_settings(monkeypatch)
    breakdown = {"version": 1, "utilities": {
        "woda": {"status": "w_czynszu"}, "ogrzewanie": {"status": "w_czynszu"},
        "smieci": {"status": "w_czynszu"}, "prad": {"status": "osobno", "amount": 200},
        "gaz": {"status": "brak_informacji"}, "internet": {"status": "brak_informacji"},
    }}
    l = FakeListing(rent_owner=2000, czynsz_admin=500, cost_breakdown=breakdown)
    # extra = 200 (prad) + 100 (gaz assumed) + 50 (internet assumed) = 350
    assert costs.suma_miesieczna(l) == 2000 + 500 + 350
    assert costs.suma_miesieczna_estimated(l) is True


def test_suma_miesieczna_breakdown_fully_included_not_estimated(monkeypatch):
    _use_default_settings(monkeypatch)
    breakdown = {"version": 1, "utilities": {u: {"status": "w_czynszu"} for u in
                 ("woda", "ogrzewanie", "smieci", "prad", "gaz", "internet")}}
    l = FakeListing(rent_owner=2000, czynsz_admin=500, cost_breakdown=breakdown)
    assert costs.suma_miesieczna(l) == 2500
    assert costs.suma_miesieczna_estimated(l) is False


def test_other_costs_overrides_breakdown(monkeypatch):
    _use_default_settings(monkeypatch)
    breakdown = {"version": 1, "utilities": {
        "prad": {"status": "osobno", "amount": 200},
        **{u: {"status": "w_czynszu"} for u in ("woda", "ogrzewanie", "smieci", "gaz", "internet")},
    }}
    l = FakeListing(rent_owner=2000, czynsz_admin=500, other_costs=50, cost_breakdown=breakdown)
    assert costs.suma_miesieczna(l) == 2000 + 500 + 50
    assert costs.suma_miesieczna_estimated(l) is False


