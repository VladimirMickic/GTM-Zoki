import pytest

from gtm.draft import QAError, QAResult, build_draft_prompt, build_redraft_prompt, is_thin_signal, qa_check
from gtm.schema import DraftSet, Prospect

VOICE_GUIDE_SAMPLE = "## Tone\nWarm, consultative.\n## Banned phrases\ncircle back"


def test_build_draft_prompt_embeds_voice_guide_and_prospect_fields():
    p = Prospect(
        company="Teal Drones", website="https://tealdrones.com",
        segment="defense-ndaa-win", outreach_angle="US-made, MIL-STD case to match your US-made drone.",
        buying_signals=["SRR win — US Army contract (source, 2026-05-01)"],
        key_news=["Teal wins SRR — ..."],
        fit_reason="NDAA/defense 15/15 — US Army SRR program",
        case_evidence="ships in a soft duffel bag today",
        competitor="Pelican 1520", competitor_weaknesses=["too heavy for field carry"],
    )
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "Teal Drones" in prompt
    assert "defense-ndaa-win" in prompt
    assert "US-made, MIL-STD case to match your US-made drone." in prompt
    assert "SRR win" in prompt
    assert "Warm, consultative" in prompt  # voice guide content is embedded verbatim
    assert "circle back" in prompt
    assert "drafts.json" in prompt
    assert "150" in prompt  # body cap stated
    assert "40" in prompt  # subject cap stated


def test_build_draft_prompt_injects_the_given_tier():
    p = Prospect(company="Teal", website="https://tealdrones.com")
    prompt = build_draft_prompt("VOICE", p, "director")
    assert "## This contact" in prompt
    assert "persona tier: director" in prompt


def test_build_draft_prompt_omits_persona_block_for_unknown_tier():
    p = Prospect(company="Teal", website="https://tealdrones.com")
    prompt = build_draft_prompt("VOICE", p, "unknown")
    assert "## This contact" not in prompt


def test_build_draft_prompt_omits_persona_tailoring_reference_for_unknown_tier():
    # The voice guide has no "unknown" tier doctrine — the prompt must not tell
    # Claude to consult a "Persona tailoring" section that doesn't cover it.
    p = Prospect(company="Teal", website="https://tealdrones.com")
    prompt = build_draft_prompt("VOICE", p, "unknown")
    assert "Persona tailoring" not in prompt
    assert "unknown' persona tier" not in prompt


def test_build_draft_prompt_keeps_persona_tailoring_reference_for_known_tier():
    p = Prospect(company="Teal", website="https://tealdrones.com")
    prompt = build_draft_prompt("VOICE", p, "c-suite")
    assert "Persona tailoring" in prompt
    assert "c-suite' persona tier" in prompt


def test_build_draft_prompt_includes_competitor_ammo_when_present():
    p = Prospect(
        company="AeroVironment", website="https://avinc.com",
        competitor="Pelican 1520", competitor_weaknesses=["too heavy for field carry — reddit r/drones"],
    )
    prompt = build_draft_prompt("VOICE", p, "c-suite")
    assert "Pelican 1520" in prompt
    assert "too heavy for field carry — reddit r/drones" in prompt
    assert "Displacement ammo" in prompt


def test_build_draft_prompt_omits_competitor_block_when_no_weaknesses():
    p = Prospect(company="Teal", website="https://tealdrones.com")
    prompt = build_draft_prompt("VOICE", p, "c-suite")
    assert "Displacement ammo" not in prompt


def _rich_prospect(**overrides):
    defaults = dict(
        company="Teal Drones", website="https://tealdrones.com",
        buying_signals=["SRR win — US Army contract"],
        case_evidence="ships in a soft duffel bag today",
        competitor="Pelican 1520", competitor_weaknesses=["too heavy for field carry"],
    )
    defaults.update(overrides)
    return Prospect(**defaults)


def test_is_thin_signal_true_when_two_or_more_sources_missing():
    # 2026-07-27 decision: 2-of-3 gate. The strict all-three gate skipped 100% of
    # contacts on the us-drone-6 run — drone makers essentially never name their case
    # vendor, so competitor_weaknesses is almost always empty and it alone blocked
    # every draft. Two present is enough specific ammo to beat a generic email.
    assert is_thin_signal(Prospect(company="X", website="https://x.com")) is True
    assert is_thin_signal(_rich_prospect(case_evidence="", competitor_weaknesses=[])) is True
    assert is_thin_signal(_rich_prospect(case_evidence="", buying_signals=[])) is True
    assert is_thin_signal(_rich_prospect(competitor_weaknesses=[], buying_signals=[])) is True


def test_is_thin_signal_false_when_any_two_of_three_present():
    assert is_thin_signal(_rich_prospect()) is False
    # the real us-drone-6 shape: case evidence + buying signals, no named competitor
    assert is_thin_signal(_rich_prospect(competitor_weaknesses=[])) is False
    assert is_thin_signal(_rich_prospect(case_evidence="")) is False
    assert is_thin_signal(_rich_prospect(buying_signals=[])) is False


def test_build_draft_prompt_skips_email_draft_when_signal_thin():
    p = Prospect(company="Ghost Drones", website="https://ghost.com")
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "SKIP" in prompt
    assert '"draft_initial": {}' in prompt
    assert "150" not in prompt  # no email-format instructions when skipped


def test_build_draft_prompt_requests_draft_when_signal_rich():
    p = _rich_prospect()
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "SKIP" not in prompt
    assert "150" in prompt
    assert "40" in prompt


def test_build_draft_prompt_always_requests_pain_points_and_talking_points():
    # primary deliverable regardless of thin/rich — position-specific either way
    thin_prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, Prospect(company="X", website="https://x.com"), "manager")
    rich_prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(), "manager")
    for prompt in (thin_prompt, rich_prompt):
        assert '"pain_points"' in prompt
        assert '"talking_points"' in prompt
        assert "manager" in prompt


def test_build_draft_prompt_no_longer_asks_for_a_followup():
    p = _rich_prospect()
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "draft_followup" not in prompt
    assert "no follow-up" in prompt.lower()


def test_build_draft_prompt_reply_json_keys_by_company_then_tier():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com")
    prompt = build_draft_prompt("VOICE", p, "director")
    assert '"Teal Drones"' in prompt
    assert '"director"' in prompt
    assert '"draft_initial"' in prompt


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
    )


def _draft():
    return DraftSet(
        initial_subject="Case built for the Teal 2?",
        initial_body="{FIRST_NAME} — saw Teal's SRR win. Worth 10 min?",
    )


def test_qa_check_returns_empty_flag_when_clean():
    client = _FakeClient(QAResult(flag=""))
    assert qa_check(_prospect(), _draft(), client=client) == ""


def test_qa_check_returns_flag_text_when_unsupported_claim_found():
    client = _FakeClient(QAResult(flag="references a $1M contract not in evidence"))
    assert qa_check(_prospect(), _draft(), client=client) == "references a $1M contract not in evidence"


def test_qa_check_raises_qa_error_on_refusal():
    client = _FakeClient(None)
    with pytest.raises(QAError):
        qa_check(_prospect(), _draft(), client=client)


def test_build_redraft_prompt_includes_qa_flag_reason_and_original_prompt():
    p = Prospect(
        company="Teal Drones", website="https://tealdrones.com",
        buying_signals=["SRR win — US Army contract"], fit_reason="NDAA 15/15",
    )
    draft = DraftSet(qa_flag="references a $1M contract not in evidence")
    prompt = build_redraft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite", draft)
    assert "Teal Drones" in prompt
    assert "references a $1M contract not in evidence" in prompt
    assert "drafts.json" in prompt
