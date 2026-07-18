"""S2 — gpt-4o-mini extraction: markdown → structured drone fields."""
import pytest

from gtm.costlog import CostLog
from gtm.extract import MAX_MARKDOWN_CHARS, DroneExtraction, ExtractError, extract


class FakeCompletions:
    def __init__(self, parsed, prompt_tokens=100, completion_tokens=20):
        self.parsed = parsed
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.last_kwargs = None

    def parse(self, **kwargs):
        self.last_kwargs = kwargs

        class Usage:
            prompt_tokens = self.prompt_tokens
            completion_tokens = self.completion_tokens

        class Msg:
            parsed = self.parsed
            refusal = None if self.parsed else "refused"

        class Choice:
            message = Msg()
            finish_reason = "stop"

        class Completion:
            choices = [Choice()]
            usage = Usage()

        return Completion()


class FakeClient:
    def __init__(self, parsed, **kw):
        self.completions = FakeCompletions(parsed, **kw)
        self.chat = self

    # client.chat.completions.parse — self.chat is self, so expose .completions


TEAL = DroneExtraction(
    company_description="US maker of military sUAS",
    drone_models=["Teal 2"],
    drone_dimensions=["13.7 x 9.8 x 3.5 in folded"],
    drone_weights=["2.75 lbs (1.25 kg)"],
    us_made_ndaa=True,
)


def test_extract_returns_parsed_fields():
    client = FakeClient(TEAL)
    result = extract("# Teal Drones\nBlue UAS certified...", client=client)
    assert result.drone_models == ["Teal 2"]
    assert result.us_made_ndaa is True
    assert client.completions.last_kwargs["model"] == "gpt-4o-mini"


def test_markdown_is_trimmed_to_cap():
    client = FakeClient(TEAL)
    extract("x" * (MAX_MARKDOWN_CHARS + 5000), client=client)
    sent = client.completions.last_kwargs["messages"][-1]["content"]
    assert len(sent) <= MAX_MARKDOWN_CHARS + 100  # small overhead ok


def test_cost_is_logged(tmp_path):
    log = CostLog(tmp_path / "costs.jsonl")
    extract("markdown", client=FakeClient(TEAL), costlog=log)
    total = log.total()
    assert total["entries"] == 1
    assert total["tokens_in"] == 100
    assert log.by_stage()["extract"]["cost_usd"] > 0


def test_refusal_raises():
    with pytest.raises(ExtractError, match="no parsed result"):
        extract("markdown", client=FakeClient(None))


def test_prompt_asks_for_dims_and_weights_separately_excluding_perf_specs():
    from gtm.extract import SYSTEM_PROMPT

    assert "drone_dimensions" in SYSTEM_PROMPT
    assert "drone_weights" in SYSTEM_PROMPT
    assert "drone_sizes" not in SYSTEM_PROMPT
    # perf specs polluted the old field (altitude/speed/range) — must be excluded
    for banned in ("speed", "range", "altitude"):
        assert banned in SYSTEM_PROMPT.lower()


def test_extraction_captures_case_evidence_field():
    # feedback 2026-07-18: upgrade-gap signal needs evidence, not an 8/15 placeholder
    from gtm.extract import DroneExtraction, SYSTEM_PROMPT

    assert DroneExtraction().case_evidence == ""
    low = SYSTEM_PROMPT.lower()
    assert "case_evidence" in SYSTEM_PROMPT
    assert "ship" in low  # what do they ship/pack the drone in
