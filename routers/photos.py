"""Ownership-checked photo serving (SPEC §13: "Photos are served only to
their owner"). Replaces the old public `app.mount("/photos", ...)` -
listing photos are private data, not something any visitor could browse.
Path layout matches the on-disk namespacing from core/pipeline/scrape/images.py:
data/photos/{user_id}/{listing_id}/{file}."""
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from core.infra.config import PHOTOS_DIR
from core.infra.db import new_session
from core.models import User
from core.infra.deps import current_user, get_owned_listing

router = APIRouter(dependencies=[Depends(current_user)])


def _not_found():
    return JSONResponse({"error": "not found"}, status_code=404)


@router.get("/photos/{path_user_id}/{listing_id}/{filename}")
def get_photo(path_user_id: str, listing_id: str, filename: str, user: User = Depends(current_user)):
    if path_user_id != user.id:
        return _not_found()
    with new_session() as session:
        listing = get_owned_listing(session, user.id, listing_id)
        if not listing:
            return _not_found()
    # filename comes from a DB-stored path (never raw user input at request
    # time), but defend against traversal anyway since it's part of the URL.
    if "/" in filename or "\\" in filename or ".." in filename:
        return _not_found()
    path = PHOTOS_DIR / user.id / listing_id / filename
    if not path.is_file():
        return _not_found()
    return FileResponse(path)
