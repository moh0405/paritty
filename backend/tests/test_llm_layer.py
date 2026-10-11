import pytest

from app.llm import cache, prompts
from app.llm.client import LLMClient, LLMResult, RecordingClient, ReplayClient
from app.llm.schemas import QueryDraft


class FakeLive:
    """Stands in for GeminiClient inside RecordingClient."""
    def __init__(self, draft):
        self.calls, self.draft = 0, draft

    def structured(self, job, prompt, schema, *, model=None, prompt_version="v1", conn=None):
        self.calls += 1
        return LLMResult(self.draft, model=model or "m", input_tokens=10, output_tokens=5)


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "ROOT", tmp_path)
    return tmp_path


def test_cache_key_depends_on_every_input():
    k = cache.cache_key("j", "m", "v1", "p")
    assert k == cache.cache_key("j", "m", "v1", "p")
    assert len({k, cache.cache_key("j2", "m", "v1", "p"), cache.cache_key("j", "m2", "v1", "p"),
                cache.cache_key("j", "m", "v2", "p"), cache.cache_key("j", "m", "v1", "p2")}) == 5


def test_replay_miss_returns_labeled_stub(tmp_cache):
    res = ReplayClient().structured("query_draft", "never cached", QueryDraft, model="m")
    assert res.is_stub and res.parsed is None and not res.cache_hit


def test_recording_then_replay_round_trip(tmp_cache, monkeypatch):
    draft = QueryDraft(query_text="Please verify 300.", claims=[])
    rec = RecordingClient.__new__(RecordingClient)
    rec.live = FakeLive(draft)
    first = rec.structured("query_draft", "prompt A", QueryDraft, model="m")
    again = rec.structured("query_draft", "prompt A", QueryDraft, model="m")
    assert first.parsed == draft and not first.cache_hit and again.cache_hit and rec.live.calls == 1   # second call served from cache
    replayed = ReplayClient().structured("query_draft", "prompt A", QueryDraft, model="m")
    assert replayed.parsed == draft and replayed.cache_hit and not replayed.is_stub


def test_prompts_have_versions_and_shared_rules():
    version, text = prompts.render("query_draft", check_description="d", expected="e", observed="o", evidence_json="[]")
    assert version == "v1" and "Never mention or infer the treatment arm" in text and "{{" not in text


def test_unfilled_placeholder_is_an_error():
    with pytest.raises(ValueError):
        prompts.render("query_draft", check_description="d")


def test_prompts_forbid_accusatory_wording():
    _, text = prompts.load("query_draft")
    assert "Never use the words fraud or misconduct" in text
