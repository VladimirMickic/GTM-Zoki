"""Doc-content regression checks — company/voice-guide.md drives gtm/draft.py's
prompt; these guard specific claims we told the user we'd add against silent
drift."""
from pathlib import Path

VOICE_GUIDE = Path("company/voice-guide.md")


def test_voice_guide_requires_category_level_social_proof_only():
    text = VOICE_GUIDE.read_text()
    assert "category-level only" in text
    assert "named client" in text.lower() or "no real customers" in text.lower()


def test_voice_guide_bans_vague_value_prop_claims():
    text = VOICE_GUIDE.read_text()
    assert "Specificity" in text
    assert "protects better" in text.lower()


def test_voice_guide_grounds_the_pain_block_in_pain_sources_only():
    text = VOICE_GUIDE.read_text()
    block3 = text.split("**Block 3")[1].split("**Block 4")[0]
    assert "community_signals" in block3
    assert "competitor_weaknesses" in block3
    # case_evidence is what they ship in today, not evidence anything hurts — listing it
    # here is what licensed the cold-0727/Arcsky fabrication.
    assert "case_evidence" not in block3
    assert "omit Block 3" in block3
