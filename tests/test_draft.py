import pytest

from gtm.draft import (
    QAError,
    QAResult,
    build_draft_prompt,
    build_redraft_prompt,
    check_reference_customer,
    check_tier_distinctness,
    has_pain_source,
    is_thin_signal,
    qa_check,
)
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
    assert "~450-700 characters" in prompt  # body length stated (Tier 1 default)
    assert "under 60 characters" in prompt  # subject cap stated


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


# --- pain grounding (voice guide Block 3) ---------------------------------------
# 2026-07-28: is_thin_signal counts case_evidence and buying_signals, but neither is
# evidence that anything HURTS — one is what they ship in today, the other a trigger
# event. Only community_signals and competitor_weaknesses record an actual complaint.

def test_has_pain_source_true_for_community_signals_alone():
    p = _rich_prospect(competitor_weaknesses=[], community_signals=["arms crack in transit"])
    assert has_pain_source(p) is True


def test_has_pain_source_true_for_competitor_weaknesses_alone():
    assert has_pain_source(_rich_prospect(community_signals=[])) is True


def test_has_pain_source_false_for_the_arcsky_shape():
    # cold-0727/Arcsky, live 2026-07-28: case_evidence + 4 buying_signals, both pain
    # fields empty. Clears is_thin_signal's 2-of-3 gate and still has nothing to write a
    # pain block from — so the draft invented "a cracked arm or a gimbal out of true".
    # Its case_evidence is a POSITIVE statement, which is why it licenses no pain at all.
    p = _rich_prospect(
        company="Arcsky",
        community_signals=[],
        competitor_weaknesses=[],
        case_evidence="packs nicely into one tough portable box",
    )
    assert is_thin_signal(p) is False
    assert has_pain_source(p) is False


def test_build_draft_prompt_drops_the_pain_block_when_no_pain_source():
    p = _rich_prospect(
        status="priority", community_signals=[], competitor_weaknesses=[],
        case_evidence="packs nicely into one tough portable box",
    )
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "SKIP" not in prompt              # still drafts — the trigger and value line stand
    assert "**The pain**" not in prompt
    assert "3. **Close**" in prompt          # renumbered from 4
    assert "~250-400 characters" in prompt
    assert "NO RESEARCHED PAIN" in prompt


def test_build_draft_prompt_keeps_the_pain_block_when_pain_source_present():
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(status="priority"), "c-suite")
    assert "**The pain**" in prompt
    assert "4. **Close**" in prompt
    assert "~450-700 characters" in prompt
    assert "NO RESEARCHED PAIN" not in prompt


def test_build_draft_prompt_keep_tier_keeps_its_shape_but_gains_the_prohibition():
    # _TIER_SHAPE["keep"] is already 3-block, so there is nothing to drop — but it folds
    # the pain into the value line, which is the same fabrication one block earlier.
    p = _rich_prospect(status="keep", community_signals=[], competitor_weaknesses=[])
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "~250-350 characters" in prompt   # keep's own shape, not _NO_PAIN_SHAPE
    assert "~250-400 characters" not in prompt
    assert "NO RESEARCHED PAIN" in prompt


def test_build_draft_prompt_pain_block_cites_only_the_two_pain_sources():
    # case_evidence used to appear here and licensed Arcsky's fabrication.
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(), "manager")
    pain_line = [ln for ln in prompt.splitlines() if "Ground it in" in ln][0]
    assert "community_signals" in pain_line
    assert "competitor_weaknesses" in pain_line
    assert "case_evidence" not in pain_line


def test_build_draft_prompt_skips_email_draft_when_signal_thin():
    p = Prospect(company="Ghost Drones", website="https://ghost.com")
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "SKIP" in prompt
    assert '"draft_initial": {}' in prompt
    assert "under 60 characters" not in prompt  # no email-format instructions when skipped


def test_build_draft_prompt_requests_draft_when_signal_rich():
    p = _rich_prospect()
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "SKIP" not in prompt
    assert "~450-700 characters" in prompt
    assert "under 60 characters" in prompt


# 2026-07-27 (user's 8 worked examples): body length is tier-driven — a Tier 2
# prospect has a thinner story, so the same length there reads as padding.
def test_build_draft_prompt_length_follows_fit_tier():
    priority = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(status="priority"), "c-suite")
    assert "Tier 1 (priority)" in priority
    assert "~450-700 characters" in priority
    assert "all four blocks" in priority

    keep = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(status="keep"), "c-suite")
    assert "Tier 2 (keep)" in keep
    assert "~250-350 characters" in keep
    assert "~450-700 characters" not in keep


def test_build_draft_prompt_defaults_to_tier_1_shape_when_status_unset():
    # segment/draft run before output sets any status in some flows — never emit a
    # prompt with no length instruction at all.
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(status=""), "c-suite")
    assert "Tier 1 (priority)" in prompt
    assert "~450-700 characters" in prompt


def test_build_draft_prompt_demands_the_pain_block_and_bans_the_one_liner_skeleton():
    # The ~150-char cap made block 3 structurally impossible — that, not model
    # disobedience, is why every draft read as a template.
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(), "manager")
    assert "**The pain**" in prompt
    assert "BANNED SKELETON" in prompt
    assert "Worth a quick\n  look?" in prompt  # the banned shape is quoted verbatim


def test_build_draft_prompt_offers_airframe_and_case_line_sources():
    p = _rich_prospect(drone_models=["Teal 2", "Black Widow"], best_case_line="AV-Field")
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite")
    assert "{{airframe_name}}" in prompt
    assert "Teal 2" in prompt
    assert "{{case_line}}" in prompt
    assert "AV-Field" in prompt


def test_build_draft_prompt_requires_the_reference_customer_token():
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, _rich_prospect(), "c-suite")
    assert "{{reference_customer}}" in prompt
    assert "NEVER a hardcoded company name" in prompt


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


# --- reference-customer guard (voice guide "Social proof" hard rule) -------------
# The user's own worked examples name "Teal Drones" as a customer — and Teal Drones is
# a priority prospect in this pipeline. An email to Teal citing Teal is the worst
# possible send, so named social proof is a token filled at send time, never literal.

def test_check_reference_customer_flags_a_run_mate_named_in_the_body():
    p = Prospect(company="AeroVironment", website="https://avinc.com")
    draft = DraftSet(
        initial_subject="Puma transport",
        initial_body="Teal Drones runs our AV-Field line across their tactical lineup.",
    )
    flag = check_reference_customer(p, draft, ["AeroVironment", "Teal Drones"])
    assert "Teal Drones" in flag
    assert "{{reference_customer}}" in flag


def test_check_reference_customer_also_scans_the_v2_body():
    p = Prospect(company="AeroVironment", website="https://avinc.com")
    draft = DraftSet(
        initial_subject="Puma transport",
        initial_body="{{reference_customer}} is a customer.",
        initial_body_alt="Defense makers (Teal Drones among them) use us.",
    )
    assert "Teal Drones" in check_reference_customer(p, draft, ["AeroVironment", "Teal Drones"])


def test_check_reference_customer_passes_when_the_token_is_used():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com")
    draft = DraftSet(
        initial_subject="Teal 2 field kit",
        initial_body="{{reference_customer}} runs our {{case_line}} line.",
        initial_body_alt="Defense sUAS makers ({{reference_customer}} among them) use us.",
    )
    assert check_reference_customer(p, draft, ["Teal Drones", "AeroVironment"]) == ""


def test_check_reference_customer_allows_naming_the_recipient_itself():
    # {{company_name}} resolves to the recipient — their own name in the body is
    # personalization, not a fabricated customer claim.
    p = Prospect(company="Teal Drones", website="https://tealdrones.com")
    draft = DraftSet(
        initial_subject="Teal 2 field kit",
        initial_body="Saw Teal Drones' SRR win — congrats.",
    )
    assert check_reference_customer(p, draft, ["Teal Drones", "AeroVironment"]) == ""


# --- cross-tier distinctness (voice guide "Banned skeleton" hard rule) ----------
# 2026-07-28, cold-0727/Arcsky: the unknown and c-suite tiers both shipped the
# subject "transport for the new Xplorer" and the same four-paragraph skeleton,
# and both came back qa_flag="passed" — qa_check reads one draft at a time and
# only fact-checks claims, so nothing in the pipeline compared the tiers.

def _tiered(subject, body):
    return DraftSet(initial_subject=subject, initial_body=body)


CSUITE_BODY = (
    "{{first_name}},\n\n"
    "Saw {{company_name}}'s {{trigger_event}} — congrats.\n\n"
    "We build cases with foam cut to a single airframe — aircraft, controller, batteries "
    "and payload each in their own cavity.\n\n"
    "{{airframe_name}} goes out in a tough portable box today. Every unit that arrives with "
    "a cracked arm is a warranty claim you pay for.\n\n"
    "Would it be a bad idea to spend 15 minutes on what a {{case_line}} build costs per unit?\n\n"
    "{{sender_name}}"
)
# Same skeleton, only wording swapped — the exact failure the guide bans.
UNKNOWN_BODY = (
    "{{first_name}},\n\n"
    "Saw {{company_name}}'s {{trigger_event}} — congrats.\n\n"
    "We build cases with foam cut to one airframe, so the aircraft, controller, batteries "
    "and payload each seat in their own cavity.\n\n"
    "{{airframe_name}} travels in a tough portable box today. That protects the outside of "
    "the load, but it lets the aircraft move.\n\n"
    "Would it be a bad idea to spend 15 minutes on what a {{case_line}} build looks like?\n\n"
    "{{sender_name}}"
)


def test_check_tier_distinctness_flags_an_identical_subject_across_tiers():
    p = Prospect(company="Arcsky", website="https://arcskytech.com", drafts_by_tier={
        "unknown": _tiered("transport for the new Xplorer", UNKNOWN_BODY),
        "c-suite": _tiered("transport for the new Xplorer", CSUITE_BODY),
    })
    flag = check_tier_distinctness(p, "c-suite", p.drafts_by_tier["c-suite"])
    assert "subject" in flag.lower()
    assert "unknown" in flag  # names the tier it collides with


def test_check_tier_distinctness_flags_a_reworded_but_identical_skeleton():
    p = Prospect(company="Arcsky", website="https://arcskytech.com", drafts_by_tier={
        "unknown": _tiered("how {{airframe_name}} ships today", UNKNOWN_BODY),
        "c-suite": _tiered("transport for the new Xplorer", CSUITE_BODY),
    })
    flag = check_tier_distinctness(p, "c-suite", p.drafts_by_tier["c-suite"])
    assert "skeleton" in flag.lower() or "structure" in flag.lower()


def test_check_tier_distinctness_passes_structurally_different_tiers():
    # Guide's own anchors: c-suite v1 leads with the congratulation, director v1
    # opens on a question about their current setup. Same company, same facts.
    question_led = (
        "{{first_name}},\n\n"
        "How does {{company_name}}'s field team pack {{airframe_name}} today — one kit, or "
        "separate bags for batteries and controller?\n\n"
        "Asking because we cut foam per airframe so setup and teardown is identical every "
        "time, no loose gear before a deployment.\n\n"
        "Is packing something your team has dialed in, or still ad hoc?\n\n"
        "{{sender_name}}"
    )
    p = Prospect(company="Arcsky", website="https://arcskytech.com", drafts_by_tier={
        "director": _tiered("kitting for {{airframe_name}}", question_led),
        "c-suite": _tiered("transport for the new Xplorer", CSUITE_BODY),
    })
    assert check_tier_distinctness(p, "c-suite", p.drafts_by_tier["c-suite"]) == ""


def test_check_tier_distinctness_passes_when_only_one_tier_exists():
    p = Prospect(company="Arcsky", website="https://arcskytech.com", drafts_by_tier={
        "c-suite": _tiered("transport for the new Xplorer", CSUITE_BODY),
    })
    assert check_tier_distinctness(p, "c-suite", p.drafts_by_tier["c-suite"]) == ""


def test_check_tier_distinctness_ignores_the_mandated_greeting_and_signature():
    # "{{first_name}}," and "{{sender_name}}" are REQUIRED identical by the guide
    # (Block 1 / Signature) — counting them as overlap would flag every pair.
    bare_a = "{{first_name}},\n\nCongrats on {{trigger_event}}.\n\n{{sender_name}}"
    bare_b = "{{first_name}},\n\nWhat protects {{airframe_name}} in transit today?\n\n{{sender_name}}"
    p = Prospect(company="Arcsky", website="https://arcskytech.com", drafts_by_tier={
        "director": _tiered("a", bare_a),
        "c-suite": _tiered("b", bare_b),
    })
    assert check_tier_distinctness(p, "c-suite", p.drafts_by_tier["c-suite"]) == ""


def test_check_tier_distinctness_skips_tiers_with_no_draft_written():
    # A thin-signal tier is talking-points-only (empty subject) — not a collision.
    p = Prospect(company="Arcsky", website="https://arcskytech.com", drafts_by_tier={
        "unknown": DraftSet(),
        "c-suite": _tiered("transport for the new Xplorer", CSUITE_BODY),
    })
    assert check_tier_distinctness(p, "c-suite", p.drafts_by_tier["c-suite"]) == ""


def test_draft_prompt_names_sibling_tiers_that_must_not_match():
    # Detection alone (check_tier_distinctness) costs a redraft round trip. Each
    # tier is prompted separately, so unless the prompt says who else is being
    # written from the same evidence, identical output is the likely outcome.
    p = Prospect(company="Arcsky", website="https://arcskytech.com",
                 status="priority", buying_signals=["launched the Xplorer"],
                 case_evidence="packs into one tough portable box")
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite",
                                sibling_tiers=["c-suite", "director", "unknown"])
    assert "director" in prompt and "unknown" in prompt
    assert "c-suite" in prompt


def test_draft_prompt_omits_sibling_warning_when_this_is_the_only_tier():
    p = Prospect(company="Arcsky", website="https://arcskytech.com",
                 status="priority", buying_signals=["launched the Xplorer"],
                 case_evidence="packs into one tough portable box")
    prompt = build_draft_prompt(VOICE_GUIDE_SAMPLE, p, "c-suite", sibling_tiers=["c-suite"])
    assert "also being written" not in prompt.lower()


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
