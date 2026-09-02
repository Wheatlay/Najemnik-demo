import io

import requests
from PIL import Image

from core.infra.config import HTTP_HEADERS, PHOTOS_DIR

MAX_PHOTOS = 20
MAX_LONG_EDGE = 1600
WEBP_QUALITY = 85


def download_photos(user_id: str, listing_id: str, image_urls: list[str]) -> list[str]:
    """Downloads up to MAX_PHOTOS images to
    data/photos/<user_id>/<listing_id>/NN.webp, re-encoded to WebP with a
    1600px long-edge cap (SPEC §7) - hosted URLs expire, so nothing else is
    ever kept. Returns the ordered list of paths relative to the project
    root (what gets stored on Listing.photos)."""
    if not image_urls:
        return []
    folder = PHOTOS_DIR / user_id / listing_id
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, url in enumerate(image_urls[:MAX_PHOTOS], start=1):
        dest = folder / f"{i:02d}.webp"
        if not dest.exists():
            try:
                r = requests.get(url, headers=HTTP_HEADERS, timeout=25)
                if r.status_code != 200:
                    continue
                _save_as_webp(r.content, dest)
            except (requests.RequestException, OSError):
                continue
        paths.append(f"photos/{user_id}/{listing_id}/{dest.name}")
    return paths


def _save_as_webp(raw_bytes: bytes, dest) -> None:
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE))
        img.save(dest, format="WEBP", quality=WEBP_QUALITY)
