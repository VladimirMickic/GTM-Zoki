# Cold-Email Segment/Draft/QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three pipeline stages — `segment` (deterministic bucketing), `draft` (Claude-checkpoint
email generation), `qa` (automated fact-check, folded into `draft`) — between the existing
`signals` and `output` stages, per the approved design at
`docs/superpowers/specs/2026-07-20-cold-email-segment-qa-design.md`.

**Architecture:** Three vertical slices. Slice 1 is schema-only (foundation). Slice 2 builds the
pure, file-free functions (`assign_segment`, `build_draft_prompt`, `qa_check`) in isolation —
each independently unit-testable with no `gtm/run.py` wiring yet, avoiding import-order problems
between the two new CLI commands. Slice 3 wires everything into `gtm/run.py`
(`merge_drafts`, `cmd_segment`, `cmd_draft`, `STAGE_NAMES`, CLI dispatch) and live-smokes the
full checkpoint round-trip. Each slice fully built + tested before the next (project convention).

**Tech Stack:** Python 3.12, Pydantic, pytest, openai (`gpt-4.1-mini` for QA — confirmed live via
API docs as of 2026-07-20: retired from the ChatGPT consumer UI but fully supported via the API,
$0.40/1M input tokens, $1.60/1M output tokens, structured outputs supported). No new external
service — `OPENAI_API_KEY` already configured and documented at `docs/tools/openai.md`.

## Global Constraints

- **TDD mandatory** — RED (watch it fail) → GREEN for every code change (CLAUDE.md, no exceptions).
- **Vertical slices** — one slice fully built + tested before the next.
- **Log & skip** — a stage/provider failure logs to `data/errors.log` and falls through; never
  aborts the whole run (CLAUDE.md).
- **Schema is the contract** — cross-stage data changes go through `gtm/schema.py` (Pydantic).
- **Git identity** — commits as `Vladimir Mickic <mickicvladimir98@gmail.com>`, no
  `Co-Authored-By` trailer (CLAUDE.md). `git push` is run by the user, never the agent.
- **Voice guide already exists** — `company/voice-guide.md` was written and committed
  (`22f0f9d`) during the brainstorming session; no task in this plan creates it.
- **Segment taxonomy reuses `ICP.md`'s 4 outreach angles** — `defense-ndaa-win`,
  `generic-case-upgrade`, `new-model-launch`, `field-harsh-environment` — no new vocabulary.
- **Mechanical format rules (150-char body, 40-char subject, banned phrases) are the `draft`
  prompt's job, self-enforced by the LLM** — not checked in code anywhere in this plan.
- **QA never blocks `output`** — `qa_flag` is informational only; a flagged prospect still flows
  through to the Sheet/CSV/HubSpot exactly like any other priority/keep prospect.

---

## Slice 1 — Schema changes

`Prospect` gains 9 new fields (1 state-only segment field, 4 surfaced draft fields + their 4
state-only `_alt` siblings, 1 surfaced `qa_flag`). `SHEET_COLUMNS` gains 5 entries. This is the
only slice that touches `gtm/schema.py` — everything downstream depends on it existing first.

**Files:**
- Modify: `gtm/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `Prospect.segment: str = ""`, `Prospect.draft_initial_subject/body: str = ""`,
  `Prospect.draft_followup_subject/body: str = ""`, `Prospect.draft_initial_subject_alt/body_alt: str = ""`,
  `Prospect.draft_followup_subject_alt/body_alt: str = ""`, `Prospect.qa_flag: str = ""`.
- Produces: `SHEET_COLUMNS` with 5 new entries inserted after `"outreach_angle"`, before
  `"contact_name"`: `"draft_initial_subject"`, `"draft_initial_body"`, `"draft_followup_subject"`,
  `"draft_followup_body"`, `"qa_flag"`.

### Task 1.1: Add segment/draft/qa fields to Prospect + SHEET_COLUMNS

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py (additions)
def test_segment_field_is_state_only_not_on_sheet():
    assert "segment" not in SHEET_COLUMNS
    p = Prospect(company="X", website="https://x.com", segment="defense-ndaa-win")
    assert p.segment == "defense-ndaa-win"


def test_draft_v1_fields_surface_on_sheet_v2_alt_fields_do_not():
    for col in ("draft_initial_subject", "draft_initial_body", "draft_followup_subject", "draft_followup_body"):
        assert col in SHEET_COLUMNS
    for col in ("draft_initial_subject_alt", "draft_initial_body_alt", "draft_followup_subject_alt", "draft_followup_body_alt"):
        assert col not in SHEET_COLUMNS
    i = SHEET_COLUMNS.index("outreach_angle")
    assert SHEET_COLUMNS[i + 1] == "draft_initial_subject"
    assert SHEET_COLUMNS[i + 5] == "contact_name"

    p = Prospect(
        company="X", website="https://x.com",
        draft_initial_subject="Case built for the Teal 2?",
        draft_initial_body="{FIRST_NAME} — saw Teal's SRR win.",
        draft_initial_subject_alt="alt subject — not on sheet",
    )
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("draft_initial_subject")] == "Case built for the Teal 2?"
    assert p.draft_initial_subject_alt == "alt subject — not on sheet"  # exists on model, just not in row


def test_qa_flag_defaults_empty_and_is_on_sheet():
    assert "qa_flag" in SHEET_COLUMNS
    p = Prospect(company="X", website="https://x.com")
    assert p.qa_flag == ""
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("qa_flag")] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py -k "segment_field or draft_v1_fields or qa_flag_defaults" -v`
Expected: FAIL — `Prospect` has no field `segment` (or similar `ValidationError`/`AttributeError`).

- [ ] **Step 3: Write minimal implementation**

In `gtm/schema.py`, add to `SHEET_COLUMNS` (insert after `"outreach_angle"`, before `"contact_name"`):

```python
    "outreach_angle",
    "draft_initial_subject",
    "draft_initial_body",
    "draft_followup_subject",
    "draft_followup_body",
    "qa_flag",
    "contact_name",
```

Add to `Prospect` (after the `outreach_angle` field, before the `# stage 6 — output / feedback` comment):

```python
    # stage "segment" — deterministic bucketing, feeds draft's angle choice; not a sheet column
    segment: str = ""
    # stage "draft" — v1 (primary) variant, surfaced on the sheet
    draft_initial_subject: str = ""
    draft_initial_body: str = ""
    draft_followup_subject: str = ""
    draft_followup_body: str = ""
    # stage "draft" — v2 (alternate) variant, state-only; open drafts.json for it
    draft_initial_subject_alt: str = ""
    draft_initial_body_alt: str = ""
    draft_followup_subject_alt: str = ""
    draft_followup_body_alt: str = ""
    # stage "draft" (qa sub-step) — empty when clean, else a short unsupported-claim note
    qa_flag: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (all tests in the file, including the 3 new ones and every pre-existing one).

- [ ] **Step 5: Commit**

```bash
git add gtm/schema.py tests/test_schema.py
git commit -m "feat: add segment/draft/qa_flag fields to Prospect schema"
```

---

## Slice 2 — Pure functions: assign_segment, build_draft_prompt, qa_check

No `gtm/run.py` changes in this slice — every function here takes explicit arguments and returns
a value, matching the existing `build_fit_prompt`/`apply_fit` (`gtm/fit.py`) and
`build_signal_prompt` (`gtm/enrich.py`) pattern. This ordering means Slice 3's `cmd_segment` (which
calls `build_draft_prompt`) and `cmd_draft` (which calls `qa_check`) can import already-complete,
already-tested functions instead of the two files growing in lockstep.

**Files:**
- Create: `gtm/segment.py`
- Create: `gtm/draft.py`
- Modify: `docs/tools/openai.md` (add the `gpt-4.1-mini` pricing/model note used by `qa_check`)
- Test: `tests/test_segment.py`, `tests/test_draft.py`

**Interfaces:**
- Produces: `assign_segment(p: Prospect) -> str` (`gtm/segment.py`) — one of
  `"defense-ndaa-win"`, `"generic-case-upgrade"`, `"new-model-launch"`, `"field-harsh-environment"`.
- Produces: `build_draft_prompt(voice_guide: str, p: Prospect) -> str` (`gtm/draft.py`).
- Produces: `class QAResult(BaseModel)` with `flag: str = ""`, and
  `qa_check(p: Prospect, *, client=None, costlog: CostLog | None = None) -> str` (`gtm/draft.py`)
  — mirrors `gtm.extract.extract()`'s client-injection pattern exactly; raises `QAError` (defined
  in `gtm/draft.py`) if the model returns no parsed result.
- Consumes: `gtm.schema.Prospect`, `gtm.costlog.CostLog` (for `qa_check`'s optional cost logging).

### Task 2.1: assign_segment (gtm/segment.py)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_segment.py
from gtm.schema import Prospect
from gtm.segment import assign_segment


def test_ndaa_true_wins_defense_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=True)
    assert assign_segment(p) == "defense-ndaa-win"


def test_ndaa_and_upgrade_evidence_both_present_ndaa_wins():
    # priority order: defense-ndaa-win beats generic-case-upgrade even when both match
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=True, case_evidence="ships in a soft backpack")
    assert assign_segment(p) == "defense-ndaa-win"


def test_soft_case_evidence_gives_upgrade_gap_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="ships in a soft backpack today")
    assert assign_segment(p) == "generic-case-upgrade"


def test_named_rugged_brand_does_not_count_as_upgrade_gap():
    # evidence names an incumbent rugged-case brand alongside upgrade language — excluded
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="upgraded to a soft-sided Pelican-branded case")
    assert assign_segment(p) != "generic-case-upgrade"


def test_launch_signal_gives_new_model_launch_segment():
    p = Prospect(
        company="X", website="https://x.com", us_made_ndaa=False, case_evidence="",
        buying_signals=["Teal launches new Golden Eagle model — expands into mapping (source, 2026-06-01)"],
    )
    assert assign_segment(p) == "new-model-launch"


def test_no_signals_falls_back_to_field_harsh_environment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="", buying_signals=[])
    assert assign_segment(p) == "field-harsh-environment"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_segment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gtm.segment'`.

- [ ] **Step 3: Write minimal implementation**

```python
# gtm/segment.py
"""New stage: deterministic bucketing into one of ICP.md's 4 outreach angles.

Pure Python, no LLM call — assign_segment() picks which angle draft's prompt
should lean into. Checked in priority order (first match wins): the highest-
weighted Fit signal (NDAA/defense) is the strongest hook when present.
"""
from __future__ import annotations

from gtm.schema import Prospect

_UPGRADE_KEYWORDS = ("soft bag", "backpack", "soft case", "generic case", "foam insert")
_RUGGED_BRANDS = ("pelican", "seahorse", "nanuk", "skb", "hardigg", "explorer case")
_LAUNCH_KEYWORDS = ("launch", "new model", "unveil", "announc")


def assign_segment(p: Prospect) -> str:
    if p.us_made_ndaa is True:
        return "defense-ndaa-win"

    evidence = p.case_evidence.lower()
    has_upgrade_kw = any(kw in evidence for kw in _UPGRADE_KEYWORDS)
    has_brand = any(brand in evidence for brand in _RUGGED_BRANDS)
    if has_upgrade_kw and not has_brand:
        return "generic-case-upgrade"

    if any(kw in s.lower() for s in p.buying_signals for kw in _LAUNCH_KEYWORDS):
        return "new-model-launch"

    return "field-harsh-environment"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_segment.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add gtm/segment.py tests/test_segment.py
git commit -m "feat: gtm/segment.py deterministic outreach-angle bucketing"
```

### Task 2.2: build_draft_prompt (gtm/draft.py)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_draft.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gtm.draft'`.

- [ ] **Step 3: Write minimal implementation**

```python
# gtm/draft.py
"""New stage: draft cold emails via a Claude checkpoint prompt (build_draft_prompt),
then automated gpt-4.1-mini fact-check (qa_check) once merged.

Claude does the judgment (drafting, matching company/voice-guide.md's tone) —
Python only builds the prompt and, after the human round-trip, fact-checks it.
"""
from __future__ import annotations

from pydantic import BaseModel

from gtm.costlog import CostLog
from gtm.schema import Prospect

MODEL = "gpt-4.1-mini"
# docs/tools/openai.md — confirmed live 2026-07-20, still API-accessible though
# retired from the ChatGPT consumer UI.
PRICE_IN, PRICE_OUT = 0.40 / 1e6, 1.60 / 1e6


class QAError(Exception):
    pass


class QAResult(BaseModel):
    flag: str = ""  # empty = every claim is supported; else a short note of what isn't


def build_draft_prompt(voice_guide: str, p: Prospect) -> str:
    return f"""Draft a 2-email cold sequence (initial + follow-up), 2 versions each, for
{p.company}. Follow company/voice-guide.md exactly — its tone, banned phrases, signature,
and format rules below are non-negotiable:

## Voice guide
{voice_guide}

## This prospect
- outreach_angle (the hook — use this, don't invent a new one): {p.outreach_angle}
- segment (which angle category to lean into): {p.segment}
- buying_signals: {p.buying_signals}
- key_news: {p.key_news}
- fit_reason: {p.fit_reason}

## Format (self-enforce — do not exceed)
- Subject line: under 40 characters.
- Body: capped at ~150 characters — one or two sentences, no more.
- Personalization variables: {{FIRST_NAME}}, {{COMPANY}}.
- No links in the body. No banned phrases (see voice guide). Close with the signature block
  from the voice guide.

Reply with ONLY this JSON (no prose), keyed by company name:
{{"{p.company}": {{"draft_initial": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}},
"draft_followup": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}}}}}}

Save the answer to drafts.json."""


def qa_check(p: Prospect, *, client=None, costlog: CostLog | None = None) -> str:
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    evidence = (
        f"buying_signals: {p.buying_signals}\nkey_news: {p.key_news}\nfit_reason: {p.fit_reason}"
    )
    email = f"Subject: {p.draft_initial_subject}\n{p.draft_initial_body}"
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You fact-check a cold email against the evidence used to write it. Flag "
                    "ONLY if the email references a specific stat, contract, certification, or "
                    "event that is NOT supported by the evidence. Do not flag tone, length, or "
                    'phrasing. Reply with flag="" if every claim is supported.'
                ),
            },
            {"role": "user", "content": f"Evidence:\n{evidence}\n\nEmail:\n{email}"},
        ],
        response_format=QAResult,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="qa",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    msg = completion.choices[0].message
    if msg.parsed is None:
        raise QAError(f"no parsed result (refusal={msg.refusal!r}, finish={completion.choices[0].finish_reason})")
    return msg.parsed.flag
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_draft.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gtm/draft.py tests/test_draft.py
git commit -m "feat: gtm/draft.py build_draft_prompt"
```

### Task 2.3: qa_check (gtm/draft.py, same file as 2.2) + openai.md update

- [ ] **Step 1: Write the failing test**

```python
# tests/test_draft.py (additions)
from gtm.draft import QAError, QAResult, qa_check


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

    def _parse(self, **kw):
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
```

Add `import pytest` and `from gtm.schema import Prospect` to the top of `tests/test_draft.py` if
not already present from Task 2.2.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft.py -v`
Expected: FAIL — `ImportError: cannot import name 'QAError'` (or similar; `qa_check`/`QAResult`
already exist from Task 2.2's implementation step, so this confirms the test harness wiring,
not the function itself — if Task 2.2 already implemented `qa_check` correctly these 3 tests
should mostly pass immediately; still run this step to confirm the fixtures work).

- [ ] **Step 3: Confirm implementation** — `qa_check`, `QAResult`, `QAError` were written in Task
  2.2's Step 3 already (single-file task, split for review granularity only). No new code here.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_draft.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Add the gpt-4.1-mini note to docs/tools/openai.md**

Append to the `## 3. Pricing (for cost log)` section in `docs/tools/openai.md`:

```markdown

`gpt-4.1-mini`: $0.40 / 1M input tokens, $1.60 / 1M output tokens. Retired from the ChatGPT
consumer UI (2026-02-13) but confirmed still fully supported via the API as of 2026-07-20,
including structured outputs (`response_format` with a Pydantic model via
`client.chat.completions.parse`). Used by `gtm/draft.py`'s `qa_check` (QA fact-check stage).
```

- [ ] **Step 6: Commit**

```bash
git add gtm/draft.py tests/test_draft.py docs/tools/openai.md
git commit -m "feat: gtm/draft.py qa_check via gpt-4.1-mini fact-check"
```

---

## Slice 3 — CLI wiring: merge_drafts, cmd_segment, cmd_draft

Wires Slice 2's pure functions into `gtm/run.py`, following the exact shape of the existing
`fit`/`enrich`/`signals` checkpoint chain: `cmd_segment` does real work then prints the next
stage's prompts and raises `CheckpointPending` (mirrors `cmd_enrich`); `cmd_draft` merges the
answer file then keeps working — running QA inline — before returning cleanly (mirrors
`cmd_fit`/`cmd_signals`, but with an extra automated step after the merge).

**Files:**
- Modify: `gtm/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `assign_segment` (`gtm/segment.py`), `build_draft_prompt`, `qa_check`, `QAResult`
  (`gtm/draft.py`) — all from Slice 2.
- Produces: `merge_drafts(prospects: list[Prospect], raw: dict) -> None` (`gtm/run.py`, same
  file/pattern as `merge_fit`/`merge_signals`).
- Produces: `cmd_segment(run: str) -> None`, `cmd_draft(run: str, drafts_json: str) -> None`
  (`gtm/run.py`).
- Produces: `STAGE_NAMES` gains `"segment"`, `"draft"`.
- Produces: `VOICE_GUIDE = Path("company/voice-guide.md")` module constant (mirrors `ICP`).

### Task 3.1: merge_drafts

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py (additions)
from gtm.run import merge_drafts  # add to the existing import block from gtm.run


def test_merge_drafts_writes_v1_to_surfaced_fields_v2_to_alt_fields():
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    raw = {
        "Teal Drones": {
            "draft_initial": {
                "v1": {"subject": "Case built for the Teal 2?", "body": "hook v1"},
                "v2": {"subject": "US-made case, Teal-sized", "body": "hook v2"},
            },
            "draft_followup": {
                "v1": {"subject": "Following up", "body": "follow v1"},
                "v2": {"subject": "One more try", "body": "follow v2"},
            },
        }
    }
    merge_drafts(prospects, raw)
    p = prospects[0]
    assert p.draft_initial_subject == "Case built for the Teal 2?"
    assert p.draft_initial_body == "hook v1"
    assert p.draft_initial_subject_alt == "US-made case, Teal-sized"
    assert p.draft_initial_body_alt == "hook v2"
    assert p.draft_followup_subject == "Following up"
    assert p.draft_followup_body_alt == "follow v2"


def test_merge_drafts_skips_companies_not_in_raw():
    prospects = [Prospect(company="Untouched Co", website="https://x.com", status="priority")]
    merge_drafts(prospects, {})
    assert prospects[0].draft_initial_subject == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run.py -k merge_drafts -v`
Expected: FAIL — `ImportError: cannot import name 'merge_drafts' from 'gtm.run'`.

- [ ] **Step 3: Write minimal implementation**

In `gtm/run.py`, add right after `merge_signals` (around line 195):

```python
def merge_drafts(prospects: list[Prospect], raw: dict) -> None:
    for p in prospects:
        d = raw.get(p.company)
        if not d:
            continue
        initial, followup = d.get("draft_initial", {}), d.get("draft_followup", {})
        p.draft_initial_subject = initial.get("v1", {}).get("subject", "")
        p.draft_initial_body = initial.get("v1", {}).get("body", "")
        p.draft_initial_subject_alt = initial.get("v2", {}).get("subject", "")
        p.draft_initial_body_alt = initial.get("v2", {}).get("body", "")
        p.draft_followup_subject = followup.get("v1", {}).get("subject", "")
        p.draft_followup_body = followup.get("v1", {}).get("body", "")
        p.draft_followup_subject_alt = followup.get("v2", {}).get("subject", "")
        p.draft_followup_body_alt = followup.get("v2", {}).get("body", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run.py -k merge_drafts -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gtm/run.py tests/test_run.py
git commit -m "feat: merge_drafts writes v1/v2 draft fields onto Prospect"
```

### Task 3.2: cmd_segment + STAGE_NAMES + CLI wiring

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py (additions)
from gtm.run import cmd_segment  # add to the existing import block


def test_cmd_segment_assigns_and_raises_checkpoint_for_draft_prompts(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", us_made_ndaa=True, status="priority")]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_segment("teal-demo-8")

    cp = exc_info.value
    assert cp.file == "drafts.json"
    assert cp.action == "draft emails"
    assert "teal-demo-8" in cp.resume
    assert "drafts.json" in cp.resume

    saved = load_state(tmp_path)
    assert saved[0].segment == "defense-ndaa-win"  # assigned before the checkpoint fired


def test_cmd_segment_no_checkpoint_when_no_priority_or_keep(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Dropped Co", website="https://x.com", status="drop")]
    save_state(prospects, tmp_path)

    cmd_segment("teal-demo-9")  # must NOT raise — nothing needs a draft prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run.py -k cmd_segment -v`
Expected: FAIL — `ImportError: cannot import name 'cmd_segment' from 'gtm.run'`.

- [ ] **Step 3: Write minimal implementation**

In `gtm/run.py`:

1. Update the import block: change `from gtm.fit import FitResult, apply_fit, build_fit_prompt, check_disqualifiers`
   — no change needed there — and add two new imports near the top:

```python
from gtm.draft import build_draft_prompt
from gtm.segment import assign_segment
```

2. Add `VOICE_GUIDE = Path("company/voice-guide.md")` next to the existing `ICP = Path("company/ICP.md")` line.

3. Update `STAGE_NAMES`:

```python
STAGE_NAMES = {"start", "fit", "enrich", "signals", "segment", "draft", "output", "emails"}
```

4. Add `cmd_segment`, right after `cmd_signals`:

```python
def cmd_segment(run: str) -> None:
    with _track_stage(run, "segment"):
        prospects = load_state(run_dir(run))
        for p in prospects:
            if p.status in ("priority", "keep"):
                p.segment = assign_segment(p)
        save_state(prospects, run_dir(run))

        voice_guide = VOICE_GUIDE.read_text()
        print("\n=== DRAFT PROMPTS — Claude: draft each, save {company: {...}} to drafts.json ===")
        needs_draft = False
        for p in prospects:
            if p.status in ("priority", "keep"):
                needs_draft = True
                print(f"\n----- {p.company} -----")
                print(build_draft_prompt(voice_guide, p))

        if needs_draft:
            raise CheckpointPending(
                file="drafts.json",
                action="draft emails",
                resume=f"python -m gtm.run draft {run} drafts.json",
            )
```

5. Add to `main()`'s `match args:` block, right after the `case ["signals", run, signals_json]:` case:

```python
            case ["segment", run]:
                cmd_segment(run)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run.py -v`
Expected: PASS (all tests, including the 2 new ones and every pre-existing test in the file —
confirms `STAGE_NAMES` addition didn't break `_validate_stage_status`).

- [ ] **Step 5: Commit**

```bash
git add gtm/run.py tests/test_run.py
git commit -m "feat: cmd_segment — bucket priority/keep prospects, checkpoint for drafts.json"
```

### Task 3.3: cmd_draft + CLI wiring

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py (additions)
from gtm.run import cmd_draft  # add to the existing import block


def test_cmd_draft_merges_and_runs_qa_flagging_unsupported_claims(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority", segment="defense-ndaa-win")]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "draft_initial": {"v1": {"subject": "Case built for the Teal 2?", "body": "hook"}, "v2": {"subject": "s2", "body": "b2"}},
            "draft_followup": {"v1": {"subject": "Following up", "body": "f1"}, "v2": {"subject": "s4", "body": "b4"}},
        }
    }))

    monkeypatch.setattr(run_mod, "qa_check", lambda p, **kw: "unsupported $1M claim")

    cmd_draft("teal-demo-10", str(drafts_path))

    saved = load_state(tmp_path)
    assert saved[0].draft_initial_subject == "Case built for the Teal 2?"
    assert saved[0].qa_flag == "unsupported $1M claim"


def test_cmd_draft_qa_failure_logs_and_skips_not_crashes(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    monkeypatch.setattr(run_mod, "ERROR_LOG", tmp_path / "errors.log")
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "draft_initial": {"v1": {"subject": "s", "body": "b"}, "v2": {"subject": "s2", "body": "b2"}},
            "draft_followup": {"v1": {"subject": "s3", "body": "b3"}, "v2": {"subject": "s4", "body": "b4"}},
        }
    }))

    def _raise(p, **kw):
        raise RuntimeError("API down")

    monkeypatch.setattr(run_mod, "qa_check", _raise)

    cmd_draft("teal-demo-11", str(drafts_path))  # must NOT raise

    saved = load_state(tmp_path)
    assert saved[0].qa_flag == ""  # left blank, not blocked
    assert (tmp_path / "errors.log").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run.py -k cmd_draft -v`
Expected: FAIL — `ImportError: cannot import name 'cmd_draft' from 'gtm.run'`.

- [ ] **Step 3: Write minimal implementation**

Add `qa_check` to the `from gtm.draft import build_draft_prompt` line, making it
`from gtm.draft import build_draft_prompt, qa_check`. Then add `cmd_draft`, right after
`cmd_segment`:

```python
def cmd_draft(run: str, drafts_json: str) -> None:
    with _track_stage(run, "draft"):
        prospects = load_state(run_dir(run))
        merge_drafts(prospects, json.loads(Path(drafts_json).read_text()))
        save_state(prospects, run_dir(run))

        n, flagged = 0, 0
        for p in prospects:
            if not p.draft_initial_subject:
                continue
            n += 1
            try:
                p.qa_flag = qa_check(p)
                if p.qa_flag:
                    flagged += 1
            except Exception as e:
                _log_error(ERROR_LOG, p.company, "qa", e)
        save_state(prospects, run_dir(run))
        print(f"{n} drafted, {flagged} flagged")
```

Add to `main()`'s `match args:` block, right after the new `case ["segment", run]:` case:

```python
            case ["draft", run, drafts_json]:
                cmd_draft(run, drafts_json)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run.py -v`
Expected: PASS (full file, all pre-existing + 4 new tests from Tasks 3.2/3.3).

- [ ] **Step 5: Commit**

```bash
git add gtm/run.py tests/test_run.py
git commit -m "feat: cmd_draft — merge drafts.json, run QA fact-check inline"
```

### Task 3.4: checkpoint round-trip test (cmd_segment → cmd_draft resumes cleanly)

Mirrors `test_cmd_start_then_cmd_fit_resumes_cleanly` and
`test_cmd_enrich_then_cmd_signals_resumes_cleanly` — the second half of the checkpoint contract:
feeding `drafts.json` to `cmd_draft` (literally what `cmd_segment`'s printed resume command
invokes) must complete cleanly end to end.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py (additions)
def test_cmd_segment_then_cmd_draft_resumes_cleanly(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    monkeypatch.setattr(run_mod, "qa_check", lambda p, **kw: "")
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", us_made_ndaa=True, status="priority")]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_segment("teal-demo-12")

    cp = exc_info.value
    assert "teal-demo-12" in cp.resume
    assert cp.file == "drafts.json"

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "draft_initial": {"v1": {"subject": "Case built for the Teal 2?", "body": "hook"}, "v2": {"subject": "s2", "body": "b2"}},
            "draft_followup": {"v1": {"subject": "Following up", "body": "f1"}, "v2": {"subject": "s4", "body": "b4"}},
        }
    }))

    cmd_draft("teal-demo-12", str(drafts_path))  # exactly what the resume command runs

    saved = load_state(tmp_path)
    assert len(saved) == 1
    p = saved[0]
    assert p.segment == "defense-ndaa-win"  # survived the round-trip from cmd_segment
    assert p.draft_initial_subject == "Case built for the Teal 2?"
    assert p.qa_flag == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run.py -k resumes_cleanly -v`
Expected: FAIL only if Tasks 3.2/3.3 have a wiring bug — if they're correct this test should
PASS immediately since it exercises already-implemented code. Run it to confirm before
proceeding; if it fails, the failure output identifies which prior task's wiring is broken.

- [ ] **Step 3: No new implementation** — this test exercises Tasks 3.2 and 3.3's code as-is.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run.py -v`
Expected: PASS (full suite).

- [ ] **Step 5: Commit**

```bash
git add tests/test_run.py
git commit -m "test: cmd_segment → cmd_draft checkpoint round-trip"
```

### Task 3.5: CLI docstring update + live smoke

- [ ] **Step 1:** Update the `gtm/run.py` module docstring's usage block (top of file) to insert
  the two new commands in pipeline order, right after the `signals` line and before `output`:

```
  python -m gtm.run segment <run>                    # bucket passers → draft prompts
  python -m gtm.run draft <run> <drafts.json>        # apply Claude's drafts → auto QA
```

- [ ] **Step 2: Run the full test suite one more time**

Run: `pytest -q`
Expected: PASS, full suite (all pre-existing tests + every test added in this plan).

- [ ] **Step 3: Live smoke**

Pick an existing run directory with priority/keep prospects and real `signals` data already
merged (e.g. `data/runs/discover-3` or `data/runs/github-smoke` — check
`.superpowers/sdd/progress.md` for which runs have real state). Run:

```bash
python -m gtm.run segment <chosen-run>
```

Expected: prints each priority/keep prospect's assigned `segment`, then `=== DRAFT PROMPTS ===`
with one real prompt per prospect (confirm it embeds real `company/voice-guide.md` content —
check for "Alex Rivera" and the banned-phrases list in the printed output), exits 5
(`ExitCode.CHECKPOINT`), and prints the `draft` resume command.

In a live Claude session (this one), answer the printed prompts for real — draft actual emails
per the prompt's instructions — and save the answer to
`data/runs/<chosen-run>/drafts.json`. Then run:

```bash
python -m gtm.run draft <chosen-run> drafts.json
```

Expected: `N drafted, M flagged` printed with real numbers; `python -m gtm.run output <chosen-run> --dry-run`
afterward shows `draft_initial_subject`/`draft_initial_body`/`qa_flag` populated in the CSV for
each drafted prospect. If any `qa_flag` fired, manually confirm it's a real unsupported claim
(true positive) or note a false positive in `data/feedback.jsonl` — either way this is a real,
non-mocked `gpt-4.1-mini` API call, log the actual cost via `CostLog` output if printed.

- [ ] **Step 4:** `superpowers:verification-before-completion` before calling the slice done; log
  any API surprise (e.g. `gpt-4.1-mini` behaving differently than the mocked tests assumed) to
  `data/feedback.jsonl`.

- [ ] **Step 5:** Nothing to commit from the smoke itself (`data/` is gitignored). Ask the user
  whether to `git push` the full plan's commits.

---

## Self-review notes

- **Spec coverage:** architecture (pipeline order + CLI commands) → Slice 3; schema → Slice 1;
  segment stage (rules + priority order) → Task 2.1; draft stage (prompt + merge + QA, inline
  not separate CLI) → Tasks 2.2/2.3/3.3; error handling (log-and-skip on QA failure) → Task 3.3's
  second test; testing plan (unit + checkpoint round-trip + live smoke) → all of Slice 2 + Tasks
  3.4/3.5. Every spec section has a task.
- **Type consistency checked:** `assign_segment(p: Prospect) -> str` (2.1) is the exact signature
  `cmd_segment` (3.2) calls; `build_draft_prompt(voice_guide: str, p: Prospect) -> str` (2.2)
  matches `cmd_segment`'s call site; `qa_check(p: Prospect, *, client=None, costlog=None) -> str`
  (2.3) matches `cmd_draft`'s call site (3.3, called with no kwargs — `client`/`costlog` default);
  `merge_drafts(prospects: list[Prospect], raw: dict) -> None` (3.1) matches `cmd_draft`'s call.
- **No placeholders** — every step has runnable code, not a description of code.
