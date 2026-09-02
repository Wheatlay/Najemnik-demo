from unittest.mock import patch

import requests
from sqlmodel import Session

from core.pipeline.enrich import enrich
from core.pipeline.enrich.ollama_client import BadModelOutput, OllamaUnavailable, generate_json
from core.pipeline.enrich.prompts import comparative, tags
from core.domain.fields import TAG_VOCABULARY
from core.models import Listing


def make_listing(user_id: str = "dummy-user-id", **overrides) -> Listing:
    defaults = dict(
        url="https://example.com/1", title="2 pokoje Koszutka", address="ul. Testowa 5",
        city="Katowice", district="Koszutka", rent_owner=2100, czynsz_admin=1045,
        deposit="", area_m2=52.0, rooms=2, floor=1,
        raw_text="2 pokoje Koszutka\nŁadne mieszkanie, ogrzewanie miejskie.",
    )
    defaults.update(overrides)
    return Listing(user_id=user_id, **defaults)


def test_tags_prompt_includes_raw_text_and_the_one_tag_asked():
    listing = make_listing()
    prompt = tags.build_prompt(listing, TAG_VOCABULARY[0])
    assert "ogrzewanie miejskie" in prompt
    assert TAG_VOCABULARY[0] in prompt


def test_comparative_prompt_lists_all_ids():
    a = make_listing(url="https://example.com/a")
    b = make_listing(url="https://example.com/b", title="3 pokoje")
    prompt = comparative.build_prompt([a, b])
    assert a.id in prompt
    assert b.id in prompt


def test_generate_json_raises_ollama_unavailable_when_offline():
    with patch("core.pipeline.enrich.ollama_client.requests.post", side_effect=requests.ConnectionError()):
        try:
            generate_json("test prompt")
            assert False, "expected OllamaUnavailable"
        except OllamaUnavailable:
            pass


def test_generate_json_raises_bad_model_output_on_garbage_response():
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "not json"}

    with patch("core.pipeline.enrich.ollama_client.requests.post", return_value=FakeResp()):
        try:
            generate_json("test prompt")
            assert False, "expected BadModelOutput"
        except BadModelOutput:
            pass


def test_enrich_listing_returns_false_when_ollama_offline(db, user):
    listing = make_listing(user_id=user.id)
    with Session(db.get_engine()) as session:
        session.add(listing)
        session.commit()
        session.refresh(listing)
        lid = listing.id

    with patch("core.pipeline.enrich.pipeline.generate_json", side_effect=OllamaUnavailable("offline")):
        assert enrich.enrich_listing(lid) is False


def test_suggest_tags_asks_one_yes_no_question_per_vocabulary_tag(db, user):
    listing = make_listing(user_id=user.id)
    with Session(db.get_engine()) as session:
        session.add(listing)
        session.commit()
        session.refresh(listing)
        lid = listing.id

    # Only confirm the first vocabulary tag; everything else answers "nie".
    def fake_generate_json(prompt, timeout=None):
        answer = "tak" if f'"{TAG_VOCABULARY[0]}"' in prompt else "nie"
        return {"answer": answer}

    with patch("core.pipeline.enrich.enrich.generate_json", side_effect=fake_generate_json) as mock:
        result = enrich.suggest_tags(lid)
    assert result == [TAG_VOCABULARY[0]]
    assert mock.call_count == len(TAG_VOCABULARY)


def test_suggest_tags_treats_bad_model_output_as_no_for_that_tag(db, user):
    listing = make_listing(user_id=user.id)
    with Session(db.get_engine()) as session:
        session.add(listing)
        session.commit()
        session.refresh(listing)
        lid = listing.id

    with patch("core.pipeline.enrich.enrich.generate_json", side_effect=BadModelOutput("garbage")):
        result = enrich.suggest_tags(lid)
    assert result == []
