"""
The two whole-listing AI actions - comparative analysis (/compare/analyze)
and tag suggestion (/listings/{id}/tags/suggest) - which had no coverage at
all until both broke.

They call `generate_json(prompt)` with a single argument, relying on the
provider's default timeout, while the field-by-field pipeline passes its own
shorter one. Making `timeout` required in the LLMProvider wrapper broke both
with a TypeError that 257 passing tests did not notice, because nothing
exercised these two paths. The signature test below is the specific guard;
the rest drive the functions end-to-end against a fake provider.
"""
import inspect
from unittest.mock import patch

from sqlmodel import Session

import core.pipeline.enrich.llm as llm_module
from core.models import Listing, Status
from core.pipeline.enrich.enrich import comparative_analysis, suggest_tags


def _seed(user_id: str, **overrides) -> str:
    from core.infra.db import get_engine
    defaults = dict(
        url="https://example.com/1", title="Testowe", city="Katowice",
        rent_owner=2000, czynsz_admin=400, area_m2=45.0, rooms=2, status=Status.NOWE,
    )
    defaults.update(overrides)
    with Session(get_engine()) as session:
        listing = Listing(user_id=user_id, **defaults)
        session.add(listing)
        session.commit()
        return listing.id


def test_generate_json_timeout_is_optional():
    """Regression guard. Both callers below invoke generate_json(prompt) with
    one argument - if `timeout` ever loses its default again, they raise
    TypeError at runtime and nothing else in the suite notices."""
    sig = inspect.signature(llm_module.generate_json)
    assert sig.parameters["timeout"].default is not inspect.Parameter.empty

    provider_sig = inspect.signature(llm_module.OllamaProvider().complete_json)
    assert provider_sig.parameters["timeout"].default is not inspect.Parameter.empty


def test_comparative_analysis_writes_ai_comment(db, user):
    a = _seed(user.id, url="https://example.com/a", title="Mieszkanie A")
    b = _seed(user.id, url="https://example.com/b", title="Mieszkanie B")

    fake = {
        a: {"porownanie": "Tańsze", "plusy": ["niski czynsz"], "minusy": ["daleko"]},
        b: {"porownanie": "Bliżej centrum", "plusy": ["lokalizacja"], "minusy": []},
    }
    with patch("core.pipeline.enrich.enrich.generate_json", return_value=fake) as gen:
        result = comparative_analysis([a, b])

    assert result == fake
    # Called positionally with just the prompt - the exact shape that broke.
    assert len(gen.call_args.args) == 1

    with Session(db.get_engine()) as session:
        assert "niski czynsz" in session.get(Listing, a).ai_comment
        assert "Bliżej centrum" in session.get(Listing, b).ai_comment


def test_comparative_analysis_returns_none_when_ai_offline(db, user):
    a = _seed(user.id, url="https://example.com/a")
    with patch("core.pipeline.enrich.enrich.generate_json", side_effect=llm_module.LLMUnavailable()):
        assert comparative_analysis([a]) is None


def test_comparative_analysis_with_no_valid_ids_returns_empty(db, user):
    assert comparative_analysis(["nonexistent-id"]) == {}


def test_suggest_tags_returns_confirmed_tags(db, user):
    lid = _seed(user.id)
    with patch("core.pipeline.enrich.enrich.generate_json", return_value={"answer": "tak"}) as gen:
        tags = suggest_tags(lid)

    assert tags  # every vocabulary tag answered "tak"
    assert len(gen.call_args.args) == 1


def test_suggest_tags_returns_none_when_ai_offline(db, user):
    lid = _seed(user.id)
    with patch("core.pipeline.enrich.enrich.generate_json", side_effect=llm_module.LLMUnavailable()):
        assert suggest_tags(lid) is None


def test_suggest_tags_skips_unparseable_answers(db, user):
    lid = _seed(user.id)
    with patch("core.pipeline.enrich.enrich.generate_json", side_effect=llm_module.LLMBadOutput()):
        assert suggest_tags(lid) == []
