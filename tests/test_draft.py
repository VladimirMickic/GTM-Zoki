import pytest

from gtm.draft import QAError, QAResult, build_draft_prompt, qa_check
from gtm.schema import Prospect

VOICE_GUIDE_SAMPLE = "## Tone\nWarm, consultative.\n## Banned phrases\ncircle back"


def test_build_draft_prompt_embeds_voice_guide_and_prospect_fields():
    p = Prospect(
        company="Teal Drones", website="https://tealdrones.com",
        segment="defense-ndaa-win", outreach_angle="US-made, MIL-STD case to match your US-made drone.",
        buying_signals=["SRR win — US Army contract (source, 2026-05-01)"],
        key_news=["Teal wins SRR — ..."],
        fit_reason="NDAA/defense 15/15 — US Army SRR program",
    )
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p)
    assert "Teal Drones" in prompt
    assert "defense-ndaa-win" in prompt
    assert "US-made, MIL-STD case to match your US-made drone." in prompt
    assert "SRR win" in prompt
    assert "Warm, consultative" in prompt  # voice guide content is embedded verbatim
    assert "circle back" in prompt
    assert "drafts.json" in prompt
    assert "150" in prompt  # body cap stated
    assert "40" in prompt  # subject cap stated


class _FakeCompletion:
    def __init__(self, parsed, refusal=None, finish_reason="stop"):
        msg = type("M", (), {"parsed": parsed, "refusal": refusal})()
        choice = type("C", (), {"message": msg, "finish_reason": finish_reason})()
        self.choices = [choice]
        self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 5})()


class _FakeClient:
    def __init__(self, parsed):
        self._parsed = parsed
        self.chat = type("Chat", (), {"completions": type("Comp", (), {"parse": self._parse})()})()
        self.last_messages = None

    def _parse(self, **kw):
        self.last_messages = kw.get("messages", [])
        return _FakeCompletion(self._parsed)


def _prospect():
    return Prospect(
        company="Teal Drones", website="https://tealdrones.com",
        buying_signals=["SRR win — US Army contract"], key_news=[], fit_reason="NDAA 15/15",
        draft_initial_subject="Case built for the Teal 2?",
        draft_initial_body="{FIRST_NAME} — saw Teal's SRR win. Worth 10 min?",
    )


def test_qa_check_returns_empty_flag_when_clean():
    client = _FakeClient(QAResult(flag=""))
    assert qa_check(_prospect(), client=client) == ""


def test_qa_check_returns_flag_text_when_unsupported_claim_found():
    client = _FakeClient(QAResult(flag="references a $1M contract not in evidence"))
    assert qa_check(_prospect(), client=client) == "references a $1M contract not in evidence"


def test_qa_check_raises_qa_error_on_refusal():
    client = _FakeClient(None)
    with pytest.raises(QAError):
        qa_check(_prospect(), client=client)


def test_qa_check_flags_unsupported_claim_in_followup_email():
    # Create a prospect with supported claims in initial email but unsupported in follow-up
    p = Prospect(
        company="Teal Drones", website="https://tealdrones.com",
        buying_signals=["SRR win — US Army contract"], key_news=[], fit_reason="NDAA 15/15",
        draft_initial_subject="Case built for the Teal 2?",
        draft_initial_body="{FIRST_NAME} — saw Teal's SRR win. Worth 10 min?",
        draft_followup_subject="Following up on SRR opportunity",
        draft_followup_body="Just checking if you saw our $5M contract offer — sounds like a fit?",
    )
    # Mock client returns a flag indicating the follow-up contains an unsupported claim
    flag_text = "follow-up: references a $5M contract not in evidence"
    client = _FakeClient(QAResult(flag=flag_text))
    result = qa_check(p, client=client)

    # Verify the flag is returned (proving the follow-up was checked)
    assert result == flag_text

    # Verify both email bodies are in the user message
    user_message = next((m["content"] for m in client.last_messages if m["role"] == "user"), None)
    assert user_message is not None
    assert "{FIRST_NAME} — saw Teal's SRR win. Worth 10 min?" in user_message
    assert "Just checking if you saw our $5M contract offer — sounds like a fit?" in user_message


def test_draft_prompt_injects_persona_tier_from_top_contact():
    p = Prospect(company="Teal", website="https://tealdrones.com", contact_title="VP of Operations; Field Technician")
    prompt = build_draft_prompt("VOICE", p)
    assert "## This contact" in prompt
    assert "c-suite" in prompt          # VP → c-suite, top-ranked contact wins
    assert "VP of Operations" in prompt


def test_draft_prompt_omits_persona_block_when_no_contact():
    p = Prospect(company="Teal", website="https://tealdrones.com", contact_title="")
    prompt = build_draft_prompt("VOICE", p)
    assert "## This contact" not in prompt
