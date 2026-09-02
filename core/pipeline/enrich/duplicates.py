"""
Duplicate detection (SPEC §9.4): flags likely re-listings of the same
physical apartment. A structured heuristic (normalized address + area
within tolerance) is more reliable here than an LLM call, and keeps this
check free to run on every page load rather than being Ollama-gated.
"""
import re

from sqlmodel import Session, select

from core.domain.queries import STILL_LISTED
from core.models import Listing


def _addr_key(listing: Listing) -> str:
    text = f"{listing.address} {listing.district}".lower()
    text = re.sub(r"[^\wąćęłńóśźż]+", "", text)
    return text


def find_duplicate_groups(session: Session, user_id: str) -> list[list[str]]:
    """Returns groups (lists of listing ids) that look like the same
    apartment: near-identical address and area within 2 m2."""
    listings = session.exec(
        select(Listing).where(
            # STILL_LISTED only: rejected listings stay in scope on purpose,
            # because being told a new ad duplicates one you already turned
            # down is exactly the useful case.
            Listing.user_id == user_id, *STILL_LISTED,
        )
    ).all()
    groups: list[list[Listing]] = []
    for listing in listings:
        if not listing.address or listing.area_m2 is None:
            continue
        key = _addr_key(listing)
        if not key:
            continue
        placed = False
        for group in groups:
            other = group[0]
            if _addr_key(other) == key and other.area_m2 is not None \
                    and abs(other.area_m2 - listing.area_m2) <= 2:
                group.append(listing)
                placed = True
                break
        if not placed:
            groups.append([listing])
    return [[l.id for l in g] for g in groups if len(g) > 1]
