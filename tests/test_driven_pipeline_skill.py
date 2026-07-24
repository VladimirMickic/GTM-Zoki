"""Doc-content regression checks — the driven-pipeline skill is how future
sessions learn to run gtm.run end-to-end with only two human checkpoints;
these guard the checkpoint count and the exact CLI stage order against
silent drift."""
from pathlib import Path

CLAUDE_SKILL = Path(".claude/skills/driven-pipeline/SKILL.md")
CODEX_SKILL = Path(".agents/skills/driven-pipeline/SKILL.md")
CLAUDE_MD = Path("CLAUDE.md")

STAGES_IN_ORDER = ["start", "fit", "enrich", "signals", "segment", "draft", "redraft", "output"]


def test_skill_exists_in_both_claude_and_codex_locations():
    assert CLAUDE_SKILL.exists()
    assert CODEX_SKILL.exists()


def test_skill_names_exactly_two_checkpoints():
    text = CLAUDE_SKILL.read_text()
    assert "Checkpoint 1" in text
    assert "Checkpoint 2" in text
    assert "Checkpoint 3" not in text


def test_skill_lists_cli_stages_in_pipeline_order():
    text = CLAUDE_SKILL.read_text()
    positions = [text.index(f"gtm.run {stage}") for stage in STAGES_IN_ORDER]
    assert positions == sorted(positions)


def test_skill_fact_check_pass_is_explicit():
    text = CLAUDE_SKILL.read_text()
    assert "Fact-check pass" in text
    assert "case_evidence" in text
    assert "no LLM call" in text.lower() or "no llm call" in text.lower()


def test_claude_and_codex_copies_match_except_tool_name():
    claude_text = CLAUDE_SKILL.read_text()
    codex_text = CODEX_SKILL.read_text()
    normalized_codex = codex_text.replace("Codex", "Claude Code")
    assert claude_text == normalized_codex


def test_claude_md_references_driven_pipeline_skill():
    text = CLAUDE_MD.read_text()
    assert "driven-pipeline" in text
