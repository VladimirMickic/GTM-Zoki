from gtm.draft import build_draft_prompt
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
