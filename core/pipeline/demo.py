"""Demo listings (SPEC §10): "Zobacz przykład" loads 3 bundled fixtures so
every view can be explored before a new account has any real data. Badged
*Przykład* in templates (Listing.is_demo) and removable in one click via
remove_demo_listings() below.

The public portfolio fixtures are entirely synthetic.  They retain plausible
Katowice districts and cost relationships so the product can be explored
without redistributing listing text, contact details or photography.

They're deliberately arranged so the advertised order and the real order
disagree:

    demo-1  ad 1 850 zł  ->  ~3 300 zł   (high admin fee + unknown utilities)
    demo-2  ad 2 200 zł  ->  ~3 660 zł   (parking + separately billed media)
    demo-3  ad 2 450 zł  ->  ~3 380 zł   (transparent utilities, no agency)

demo-2 looks 250 zł cheaper than demo-3 in the ad and costs more per month
more to live in. That inversion is the argument for the app, so if these
numbers are ever edited, keep it intact - tests/test_demo_and_admin.py
asserts it.

No real ad URLs or street numbers are used; coordinates are district-level.
Phone numbers are deliberately invalid placeholders rather than absent, because the
call-prep block is gated on listing.phone and is one of the features the
examples exist to demonstrate.

Loading also seeds a reference point on the map (DEMO_COMMUTE_POINT), and
removing takes it away again.
"""
import json
import shutil
from datetime import datetime, timedelta

from sqlmodel import Session, select

from core.domain.settings import invalidate_cache
from core.infra.config import BASE_DIR, PHOTOS_DIR
from core.models import Listing, Settings

FIXTURES_PATH = BASE_DIR / "fixtures" / "demo_listings.json"
FIXTURE_PHOTOS_DIR = BASE_DIR / "fixtures" / "demo" / "photos"

# A reference point in the middle of Katowice, added with the examples so the
# map has something to measure against - the commute feature is invisible
# until at least one point exists, and asking a brand-new user to go and
# configure one before they've seen why is the wrong order.
DEMO_COMMUTE_POINT = {"id": "demo-praca", "name": "Praca (przykład)", "lat": 50.2584, "lon": 19.0275}


def _settings_for(session: Session, user_id: str) -> Settings | None:
    return session.exec(select(Settings).where(Settings.user_id == user_id)).first()


def _add_demo_commute_point(session: Session, user_id: str) -> None:
    """Never touches points the user set themselves - it only appends, and
    only if this exact demo point isn't already there."""
    settings = _settings_for(session, user_id)
    if settings is None:
        return
    points = list(settings.commute_points or [])
    if any(p.get("id") == DEMO_COMMUTE_POINT["id"] for p in points):
        return
    settings.commute_points = points + [dict(DEMO_COMMUTE_POINT)]
    session.add(settings)


def _remove_demo_commute_point(session: Session, user_id: str) -> None:
    settings = _settings_for(session, user_id)
    if settings is None:
        return
    points = [p for p in (settings.commute_points or []) if p.get("id") != DEMO_COMMUTE_POINT["id"]]
    if len(points) != len(settings.commute_points or []):
        settings.commute_points = points
        session.add(settings)


def _copy_demo_photos(user_id: str, listing_id: str, src_slug: str) -> list[str]:
    """Copy a fixture photo set into this user's own photo tree.

    Demo photos live under one shared fixtures/ directory, but every listing's
    photos are served from data/photos/{user_id}/{listing_id}/ behind an
    ownership check (routers/photos.py) - so they have to be copied per user
    rather than referenced in place, or the demo would be the one thing in
    the app reachable across tenants.
    """
    src = FIXTURE_PHOTOS_DIR / src_slug
    if not src.is_dir():
        return []
    dest = PHOTOS_DIR / user_id / listing_id
    dest.mkdir(parents=True, exist_ok=True)
    rel_paths = []
    for photo in sorted(src.glob("*.webp")):
        shutil.copy2(photo, dest / photo.name)
        rel_paths.append(f"photos/{user_id}/{listing_id}/{photo.name}")
    return rel_paths


def load_demo_listings(session: Session, user_id: str) -> list[Listing]:
    data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    existing_urls = set(session.exec(
        select(Listing.url).where(Listing.user_id == user_id, Listing.is_demo == True)
    ))
    created = []
    for entry in data:
        if entry["url"] in existing_urls:
            continue
        entry = dict(entry)
        # Not a Listing column - it names which bundled photo set to use.
        photos_src = entry.pop("photos_src", None)
        # Nor is this one: a viewing date has to be relative, or the example
        # shows an appointment that quietly slid into the past. Resolved to a
        # real datetime here, rounded to a plausible hour.
        in_days = entry.pop("termin_ogledzin_in_days", None)
        if in_days is not None:
            entry["termin_ogledzin"] = (datetime.now() + timedelta(days=in_days)).replace(
                hour=17, minute=30, second=0, microsecond=0
            )
        listing = Listing(user_id=user_id, is_demo=True, **entry)
        session.add(listing)
        session.flush()  # assigns listing.id, needed for the photo path
        if photos_src:
            listing.photos = _copy_demo_photos(user_id, listing.id, photos_src)
            session.add(listing)
        created.append(listing)
    if created:
        _add_demo_commute_point(session, user_id)
    session.commit()
    # core.domain.settings caches Settings per user; without this the map
    # keeps reading the pre-seed commute_points until the process restarts.
    invalidate_cache(user_id)
    return created


def remove_demo_listings(session: Session, user_id: str) -> int:
    """Delete this user's demo listings and their copied photos.

    Scoped to is_demo rows on purpose. Per-listing deletion was removed from
    the app (see routers/listings_api.py) because it was an unrecoverable
    action on data the user collected themselves - but examples the app
    inserted are exactly the case where a real delete is right, and there is
    otherwise no way to clear them.
    """
    demo = list(session.exec(
        select(Listing).where(Listing.user_id == user_id, Listing.is_demo == True)
    ))
    for listing in demo:
        folder = PHOTOS_DIR / user_id / listing.id
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        session.delete(listing)
    _remove_demo_commute_point(session, user_id)
    session.commit()
    invalidate_cache(user_id)
    return len(demo)
