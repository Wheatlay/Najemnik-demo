"""
Rank cascade (SPEC §3): moving a listing to position N shifts everything
below it down by one. Typing a target number directly works the same way.
"""
from sqlmodel import Session, select

from core.models import Listing


def set_rank(session: Session, user_id: str, listing_id: str, new_rank: int | None) -> None:
    listings = list(session.exec(
        select(Listing).where(Listing.user_id == user_id, Listing.rank.is_not(None)).order_by(Listing.rank)
    ))
    target = session.get(Listing, listing_id)
    if not target or target.user_id != user_id:
        return
    ordered = [l for l in listings if l.id != listing_id]

    if new_rank is None:
        target.rank = None
        session.add(target)
        for i, l in enumerate(ordered, start=1):
            l.rank = i
            session.add(l)
        session.commit()
        return

    new_rank = max(1, min(new_rank, len(ordered) + 1))
    ordered.insert(new_rank - 1, target)
    for i, l in enumerate(ordered, start=1):
        l.rank = i
        session.add(l)
    session.commit()
