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
