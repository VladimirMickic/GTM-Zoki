# Driven-Pipeline Two-Checkpoint Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture the driven-pipeline operating procedure (Claude drives `gtm.run` end-to-end via Bash, surfacing exactly two human checkpoints) as a durable local skill, so it survives context compaction and future sessions instead of living only in this conversation.

**Architecture:** No `gtm/` pipeline code changes — this plan produces one new skill file (mirrored for Claude Code and Codex, per the existing convention in `.claude/skills/company-research`), a content-regression test guarding its key claims against silent drift (same pattern as `tests/test_voice_guide.py`), and a one-line addition to CLAUDE.md's "Skills (local)" list.

**Tech Stack:** Markdown skill file, pytest content assertions.

## Global Constraints

- Exactly two human-facing checkpoints, no more: (1) company count, asked once up front, only if unspecified; (2) draft approval, before the Sheet push. Every other stage (fit, signals, displacement research, draft, QA/redraft) is answered by Claude directly, no stop.
- No changes to `gtm/` pipeline code — this is a documented operating procedure only, per `docs/superpowers/specs/2026-07-24-driven-pipeline-checkpoints-design.md`.
- Exact CLI commands, verbatim from `gtm/run.py`'s `main()` dispatch: `start`, `fit`, `enrich`, `signals`, `segment`, `draft`, `redraft`, `output` (optionally `--dry-run`).
- Fact-check pass is a deterministic string check (grep draft text against `case_evidence`/`competitor_weaknesses` on the same prospect) — no LLM call, no added cost.
- Local skills that exist in both `.claude/skills/` and `.agents/skills/` must stay in sync except for the tool-name wording that intentionally differs (`Claude Code` vs `Codex`), per the self-improvement note in `.claude/skills/company-research/SKILL.md`.

---

### Task 1: `driven-pipeline` skill (mirrored) + content-regression test

**Files:**
- Create: `.claude/skills/driven-pipeline/SKILL.md`
- Create: `.agents/skills/driven-pipeline/SKILL.md` (identical except two wording spots, see Step 5)
- Create: `tests/test_driven_pipeline_skill.py`
- Modify: `CLAUDE.md:67-68` (append `driven-pipeline` to the "Skills (local)" list)

**Interfaces:**
- Consumes: nothing (docs-only skill; references `gtm/run.py`'s existing CLI, `company/ICP.md`, `company/voice-guide.md`, `company-research` and `reddit-find` skills — all already exist, no new interfaces).
- Produces: the skill text future sessions read via the `Skill` tool when the user says "hey zoki, find me N drone companies" or similar.

- [ ] **Step 1: Write the failing test**

Create `tests/test_driven_pipeline_skill.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_driven_pipeline_skill.py -v`
Expected: FAIL — `.claude/skills/driven-pipeline/SKILL.md` doesn't exist yet (collection error or `FileNotFoundError` on `read_text()`), and `"driven-pipeline"` isn't in `CLAUDE.md`.

- [ ] **Step 3: Write `.claude/skills/driven-pipeline/SKILL.md`**

```markdown
---
name: driven-pipeline
description: Drive the full gtm.run pipeline (start → fit → enrich → signals → segment → draft → redraft → output) end-to-end via Bash, answering every judgment checkpoint directly instead of surfacing it to the user. Use when the user says "hey zoki, find me drone companies" (or similar) or otherwise asks to run/start a GTM pipeline. Reduces the human-facing checkpoints to exactly two: an up-front company-count question (only if unspecified) and a final draft-approval gate before the Sheet push.
allowed-tools: Read, Write, Edit, Bash
---

# driven-pipeline

Procedure for running `gtm/run.py` end-to-end in one session, per
`docs/superpowers/specs/2026-07-24-driven-pipeline-checkpoints-design.md`.
CLAUDE.md's own architecture states it: "Claude does judgment between
commands (prompts print to stdout, answers go in a JSON file)" — this skill
is that judgment loop, driven directly instead of relayed through the user.

## Checkpoint 1: company count

Before starting, check whether the user's ask already states a count
("find me 3 companies"). If not, ask once: "How many companies do you want
me to find?" Do not ask again mid-run.

## Stage-by-stage (no further stops until Checkpoint 2)

1. `python -m gtm.run start data/runs/<run>/brief.md` — discover/scrape/extract, raises a `CheckpointPending` fit prompt.
2. Answer the fit prompt yourself: score each company vs `company/ICP.md`, write the JSON to `data/runs/<run>/fit.json`, then `python -m gtm.run fit <run> fit.json`.
3. `python -m gtm.run enrich <run>` — prints a signal prompt and, for any prospect with a detected `competitor`, a separate displacement research prompt, one block per company. Research both using the `company-research` and `reddit-find` skills where real data is needed. Write one merged entry per company to `data/runs/<run>/signals.json` — always include `competitor_weaknesses` explicitly for any company that has one, even though an omitted key preserves the prior value rather than resetting it. Then `python -m gtm.run signals <run> signals.json`.
4. `python -m gtm.run segment <run>` — assigns a segment bucket per company and prints one draft prompt per (company, tier) pair for every tier present. Write copy per `company/voice-guide.md` (category-only social proof, every value-prop claim backed by a concrete mechanism/spec — no bare comparatives) to `data/runs/<run>/drafts.json`, then `python -m gtm.run draft <run> drafts.json`.
5. Any tier QA-flags: re-answer just those tiers in a new JSON, `python -m gtm.run redraft <run> drafts.json`. Repeat until no `qa_flag` remains. No stop.

## Fact-check pass (before Checkpoint 2)

For every drafted tier, pull that prospect's `case_evidence` and
`competitor`/`competitor_weaknesses` fields (in `data/runs/<run>/prospects.json`)
and check the draft's `initial_body`/`initial_body_alt` for every named
competitor, spec rating, or dimension. Anything in the draft text that
doesn't appear in those source fields gets rewritten (via `redraft`) before
it reaches the table below. Deterministic string check — no LLM call.

## Checkpoint 2: draft approval

Present one compact table: company, contact, tier, subject line, one-line
angle. Offer full draft text for any row on request. Wait for the user to
approve all or flag specific rows. On a flagged row, rewrite just that tier
and redraft, then re-show the table (loop until approved).

## Output

Only after approval: `python -m gtm.run output <run>` (add `--dry-run` first
if the user wants to inspect the CSV before a live Sheet push). Sheet tabs
are append-only with no dedupe-by-company — remind the user to clear the
`Companies`/`Contacts` tabs by hand first if this isn't the first run against
that Sheet.

## Errors

Log-and-skip, unchanged: a company erroring at any stage lands in
`data/errors.log` with `status="error"` and drops out — never stops the rest
of the run.
```

- [ ] **Step 4: Run tests to verify Steps 1-3 pass so far**

Run: `.venv/bin/pytest tests/test_driven_pipeline_skill.py -v`
Expected: `test_skill_exists_in_both_claude_and_codex_locations` still FAILS
(Codex copy doesn't exist yet — expected at this point), all other tests
against the Claude copy PASS.

- [ ] **Step 5: Mirror to `.agents/skills/driven-pipeline/SKILL.md`**

Unlike `company-research` (whose body names "Claude Code's own `WebSearch`/
`WebFetch`" and needs a `Codex` swap in the mirror), this skill's body never
names the host tool — confirm with:

```bash
grep -n "Claude Code" .claude/skills/driven-pipeline/SKILL.md
```

Expected: no output. Since there's no host-tool wording to swap, copy the
file directly:

```bash
mkdir -p .agents/skills/driven-pipeline
cp .claude/skills/driven-pipeline/SKILL.md .agents/skills/driven-pipeline/SKILL.md
```

- [ ] **Step 6: Update CLAUDE.md's "Skills (local)" list**

Modify `CLAUDE.md:67-68`, currently:

```markdown
company-research (enrichment) · prospect-research · reddit-find · cold-email (later) ·
agent-browser (browser fallback) · youtube-transcript.
```

Replace with:

```markdown
company-research (enrichment) · prospect-research · reddit-find · cold-email (later) ·
agent-browser (browser fallback) · youtube-transcript · driven-pipeline (run the
full pipeline end-to-end with only 2 human checkpoints).
```

- [ ] **Step 7: Run the full test file to verify all tests pass**

Run: `.venv/bin/pytest tests/test_driven_pipeline_skill.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 8: Run the full suite to confirm no regressions**

Run: `.venv/bin/pytest -q`
Expected: PASS, 300 passed (294 baseline + 6 new tests in
`tests/test_driven_pipeline_skill.py`).

- [ ] **Step 9: Commit**

```bash
git add .claude/skills/driven-pipeline/SKILL.md .agents/skills/driven-pipeline/SKILL.md tests/test_driven_pipeline_skill.py CLAUDE.md
git commit -m "$(cat <<'EOF'
feat: add driven-pipeline skill — two-checkpoint end-to-end run procedure

Captures the operating procedure from
docs/superpowers/specs/2026-07-24-driven-pipeline-checkpoints-design.md
as a durable skill (mirrored for Claude Code and Codex) so it survives
context compaction instead of living only in one conversation.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---
