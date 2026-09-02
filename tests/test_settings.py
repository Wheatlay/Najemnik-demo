import core.domain.settings as settings_module
from core.models import Settings


def test_get_settings_creates_default_row(db, user_a):
    settings = settings_module.get_settings(user_a.id)
    assert settings.user_id == user_a.id
    assert settings.prad_cost == 150
    assert settings.commute_points == []


def test_get_settings_is_cached_until_invalidated(db, user_a):
    first = settings_module.get_settings(user_a.id)
    assert first is settings_module.get_settings(user_a.id)

    from sqlmodel import Session, select
    with Session(db.get_engine()) as session:
        row = session.exec(select(Settings).where(Settings.user_id == user_a.id)).first()
        row.prad_cost = 999
        session.add(row)
        session.commit()

    # Stale cache still reflects the pre-write value...
    assert settings_module.get_settings(user_a.id).prad_cost == 150
    settings_module.invalidate_cache(user_a.id)
    # ...until invalidated.
    assert settings_module.get_settings(user_a.id).prad_cost == 999
