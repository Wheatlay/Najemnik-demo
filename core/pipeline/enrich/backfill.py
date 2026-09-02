"""
Re-enrichment job runner - lets the user re-run the current AI pipeline over
listings that were enriched by an older prompt version (or never enriched
because Ollama was offline at ingest time). Mirrors the `_jobs` polling
pattern in core/pipeline/ingest.py (single-user, single-process app - an in-memory
dict is enough, no task queue needed).
"""
import threading
import uuid

from sqlmodel import Session, select

from core.infra.db import get_engine
from core.pipeline.enrich.enrich import enrich_listing, suggest_tags
from core.models import Listing

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _set_job(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        _jobs[job_id].update(kwargs)


def get_job(job_id: str, user_id: str) -> dict | None:
    """Returns None (not the job) if job_id exists but belongs to another
    user - job ids are unguessable UUIDs, but this is defense in depth
    against someone who obtained one anyway (SPEC §17 isolation)."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job.get("user_id") != user_id:
            return None
        return dict(job)


def _reenrich(job_id: str, listing_ids: list[str]) -> None:
    total = len(listing_ids)
    _set_job(job_id, total=total, done=0, status="running", current="")
    engine = get_engine()

    for i, listing_id in enumerate(listing_ids, start=1):
        with Session(engine) as session:
            listing = session.get(Listing, listing_id)
            title = listing.title if listing else listing_id

        def _progress(label: str, step: int, step_total: int, _title=title, _i=i, _total=total) -> None:
            _set_job(job_id, current=f"({_i}/{_total}) {_title}: {label}")

        ok = enrich_listing(listing_id, progress=_progress)
        if ok:
            suggested = suggest_tags(listing_id)
            if suggested:
                with Session(engine) as session:
                    listing = session.get(Listing, listing_id)
                    if listing:
                        listing.tags = sorted(set(listing.tags) | set(suggested))
                        session.add(listing)
                        session.commit()

        with _jobs_lock:
            _jobs[job_id]["done"] = i
            if not ok:
                _jobs[job_id]["offline"] = True

    _set_job(job_id, status="done", current="")


def start_reenrich_job(user_id: str, listing_ids: list[str]) -> str:
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "total": len(listing_ids), "done": 0, "status": "pending", "offline": False,
            "user_id": user_id,
        }
    thread = threading.Thread(target=_reenrich, args=(job_id, listing_ids), daemon=True)
    thread.start()
    return job_id


def active_listing_ids(user_id: str) -> list[str]:
    engine = get_engine()
    with Session(engine) as session:
        # STILL_LISTED only: a rejected listing keeps its analysis, so that
        # un-rejecting it later doesn't leave a half-filled row.
        from core.domain.queries import STILL_LISTED
        stmt = select(Listing.id).where(Listing.user_id == user_id, *STILL_LISTED)
        return list(session.exec(stmt).all())
