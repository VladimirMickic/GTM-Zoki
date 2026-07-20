# Persona-Based Email Tailoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tailor cold-email drafts to the recipient's seniority (C-suite → ROI, manager → process/team, IC → day-to-day), using the contact rank the pipeline already computes.

**Architecture:** A new pure module `gtm/persona.py` classifies a job title into a seniority tier. `company/voice-guide.md` gains the messaging doctrine (email structure, template lines, and per-tier persona rules) as the single source of truth. `build_draft_prompt` derives the top contact's tier and injects a "This contact" block telling the model which voice-guide persona rule to apply. No new dependencies, no new pipeline stage, no schema change — the `contact_title` field already carries the data.

**Tech Stack:** Python 3, Pydantic (existing), pytest. No new libraries.

## Global Constraints

- Git identity: `Vladimir Mickic <mickicvladimir98@gmail.com>`. NO `Co-Authored-By` trailer.
- Work directly on `main` (established project convention — no feature branch). Never push unless the user explicitly asks.
- TDD: RED → GREEN per task. Recorded fixtures, no live API call in these tasks (all pure Python).
- Emails ship in **English** (US market / AeroVault), regardless of note language.
- Persona doctrine lives in `company/voice-guide.md` ONLY. `gtm/persona.py` classifies; it does NOT duplicate the doctrine text. One source of truth.
- Keep it lean (CLAUDE.md): no speculative generality, hardcoded AeroVault stays.

---

### Task 1: `gtm/persona.py` — seniority classifier

**Files:**
- Create: `gtm/persona.py`
- Test: `tests/test_persona.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces: `classify_persona(title: str) -> str` returning exactly one of `"c-suite"`, `"manager"`, `"ic"`, `"unknown"`. Empty/whitespace title → `"unknown"`. Non-empty but unmatched → `"ic"`. Checked high-to-low, first match wins.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_persona.py
from gtm.persona import classify_persona


def test_c_suite_titles():
    assert classify_persona("CEO") == "c-suite"
    assert classify_persona("VP of Operations") == "c-suite"
    assert classify_persona("Founder & CEO") == "c-suite"


def test_manager_titles():
    assert classify_persona("Director of Logistics") == "manager"
    assert classify_persona("Operations Manager") == "manager"


def test_ic_titles():
    assert classify_persona("Field Technician") == "ic"
    assert classify_persona("Procurement Buyer") == "ic"


def test_unknown_when_empty():
    assert classify_persona("") == "unknown"
    assert classify_persona("   ") == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_persona.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gtm.persona'`

- [ ] **Step 3: Write minimal implementation**

```python
# gtm/persona.py
"""Classify a contact's job title into a seniority tier for persona-based email
tailoring. Pure Python, no LLM. The *doctrine* for each tier (what to pitch) lives
in company/voice-guide.md — this module only labels the tier."""
from __future__ import annotations

import re

# checked high-to-low, first match wins. VP/president = exec tier deliberately.
_C_SUITE = (
    "founder", "owner", "ceo", "cto", "coo", "cfo", "chief",
    "president", "vice president", "vp",
)
_MANAGER = ("director", "head of", "manager", "operations", "program", "logistics", "lead")


def classify_persona(title: str) -> str:
    t = title.lower().strip()
    if not t:
        return "unknown"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _C_SUITE):
        return "c-suite"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _MANAGER):
        return "manager"
    return "ic"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_persona.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add gtm/persona.py tests/test_persona.py
git commit -m "feat: gtm/persona.py — classify contact title into seniority tier"
```

---

### Task 2: `company/voice-guide.md` — persona doctrine + email structure + templates

**Files:**
- Modify: `company/voice-guide.md` (append two new sections)

**Interfaces:**
- Consumes: nothing (doc file).
- Produces: two new `##` sections that Task 3's prompt block references by name — `## Email structure` and `## Persona tailoring`. The persona section MUST contain the three tier labels verbatim: `c-suite`, `manager`, `ic` (so the model can match the tier label the prompt injects).

- [ ] **Step 1: Append the two sections**

Add to the end of `company/voice-guide.md`:

```markdown
## Email structure (per email)
1. **Opening line** — a real, specific fact about the prospect (a win, launch, or shipping gap), not a generic greeting.
2. **Value prop** — a use case + social proof (a comparable, well-known customer) + the pain it removes. Example framing: "We saw companies similar to you have {xyz}."
3. **Close** — one closed-ended (yes/no) call to action. Never stack asks. Prefer a low-pressure ask, e.g. a negative-CTA: "Do you think it'd be a bad idea to sit and chat for 15 min?" or a single real question: "Do you run into {problem}, and how do you handle it today?"

## Persona tailoring (pitch by seniority)
The `draft` prompt injects the top contact's **persona tier** (from `gtm/persona.py`). Lean the value prop toward the matching rule:

- **c-suite** — pitch the **business outcome**: ROI, cost, what the case program wins or saves them. Skip process detail. They care about the number, not the workflow.
- **manager** — pitch **process and team**: smoother logistics, less firefighting, a team that isn't fighting broken gear. Do NOT lead with money saved — it's not their metric.
- **ic** — pitch the **day-to-day**: easier handling, less hassle in the field, people happier doing the work.
- **unknown** — no contact tier available; write to the company's segment/angle generically, no seniority lean.
```

- [ ] **Step 2: Verify the draft prompt still builds with the enlarged guide**

Run: `python -c "from gtm.draft import build_draft_prompt; from gtm.schema import Prospect; print(len(build_draft_prompt(open('company/voice-guide.md').read(), Prospect(company='X'))))"`
Expected: prints an integer (prompt length), no exception. Confirms the larger voice-guide embeds cleanly.

- [ ] **Step 3: Commit**

```bash
git add company/voice-guide.md
git commit -m "docs: voice-guide — email structure, templates, persona-by-seniority doctrine"
```

---

### Task 3: `build_draft_prompt` — inject the contact's persona tier

**Files:**
- Modify: `gtm/draft.py` (`build_draft_prompt`, add `gtm.persona` import)
- Test: `tests/test_draft.py` (add two tests)

**Interfaces:**
- Consumes: `classify_persona(title: str) -> str` (Task 1); the `## Persona tailoring` section in `voice-guide.md` (Task 2).
- Produces: `build_draft_prompt(voice_guide: str, p: Prospect) -> str` — unchanged signature. When `p.contact_title` is non-empty, the returned prompt contains a `## This contact` block naming the top contact's title and persona tier. When `p.contact_title` is empty, no such block is added (tier would be `unknown`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_draft.py — add these two tests
from gtm.draft import build_draft_prompt
from gtm.schema import Prospect


def test_draft_prompt_injects_persona_tier_from_top_contact():
    p = Prospect(company="Teal", contact_title="VP of Operations; Field Technician")
    prompt = build_draft_prompt("VOICE", p)
    assert "## This contact" in prompt
    assert "c-suite" in prompt          # VP → c-suite, top-ranked contact wins
    assert "VP of Operations" in prompt


def test_draft_prompt_omits_persona_block_when_no_contact():
    p = Prospect(company="Teal", contact_title="")
    prompt = build_draft_prompt("VOICE", p)
    assert "## This contact" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_draft.py -k persona -v`
Expected: FAIL — `test_draft_prompt_injects_persona_tier_from_top_contact` fails on `"## This contact" in prompt` (block not built yet).

- [ ] **Step 3: Implement the injection**

In `gtm/draft.py`, add the import near the top (after the existing `from gtm.schema import Prospect`):

```python
from gtm.persona import classify_persona
```

Then replace `build_draft_prompt` with:

```python
def build_draft_prompt(voice_guide: str, p: Prospect) -> str:
    top_title = p.contact_title.split(";")[0].strip() if p.contact_title else ""
    persona = classify_persona(top_title)
    contact_block = ""
    if persona != "unknown":
        contact_block = (
            f"\n## This contact (tailor the pitch to their seniority)\n"
            f"- top contact title: {top_title}\n"
            f"- persona tier: {persona}\n"
            f"Apply the matching rule from the voice guide's \"Persona tailoring\" section.\n"
        )
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
{contact_block}
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_draft.py -k persona -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite for no regression**

Run: `pytest -q`
Expected: all pass (existing count + 6 new: 4 persona, 2 draft).

- [ ] **Step 6: Commit**

```bash
git add gtm/draft.py tests/test_draft.py
git commit -m "feat: build_draft_prompt injects contact persona tier for seniority tailoring"
```

---

## Live smoke (after Task 3)

Run `segment` against a real run with contacts (per the ledger, `discover-3` has BRINC/Paladin with real titles):

```bash
python -m gtm.run segment discover-3
```

Expected: the printed DRAFT PROMPTS now include a `## This contact` block with a real persona tier for at least one prospect. Confirm the tier matches the contact's actual title. No code change from the smoke.

## Self-review notes

- **Spec coverage:** persona classification (Task 1), doctrine as single source of truth in voice-guide (Task 2), prompt injection driven by existing `contact_title` (Task 3), email structure + template lines from the user's notes (Task 2). All confirmed decisions covered.
- **No duplication:** doctrine text is ONLY in voice-guide.md; persona.py returns a label. The prompt references the section by name.
- **Type consistency:** `classify_persona` returns the same four labels everywhere; the prompt block only renders for non-`unknown`.
