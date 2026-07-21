# Competitor Displacement + Persona-Tiered Drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the fit-scoring signal so a named competitor case scores as a displacement
opportunity (not a penalty), add a deterministic-detection + skill-driven research step that
turns that competitor into cited email ammo, and draft a distinct email sequence per persona
tier present at a company instead of one shared draft.

**Architecture:** Three additive changes to the existing `gtm/run.py` orchestrator pipeline
(scrape → extract → fit → enrich → signals → segment → draft → output), no new CLI stage.
Competitor detection is pure Python (regex against `case_evidence`, zero LLM cost); the
weakness research and the drafts themselves stay Claude-checkpoint prompts, same
round-trip pattern the pipeline already uses (`fit.json`, `signals.json`, `drafts.json`).

**Tech Stack:** Python, Pydantic v2, pytest, gpt-4o-mini (extraction only, unchanged),
gpt-4.1-mini (QA fact-check, unchanged), Claude (fit/signals/displacement/draft judgment,
orchestrator-side).

## Global Constraints

- Credit-efficient: no new LLM extraction call for competitor detection — reuse deterministic
  regex, not gpt-4o-mini (spec Part 2).
- No backwards-compat shims: `Prospect`'s flat `draft_*`/`qa_flag` fields are replaced
  outright by `drafts_by_tier: dict[str, DraftSet]`, not kept alongside it (spec Part 3).
- TDD throughout — every task writes/updates a failing test before touching implementation,
  per this repo's established convention (both prior sessions).
- Frequent, small commits — one per task, `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Sheet stays lean: `competitor`/`competitor_weaknesses`/`drafts_by_tier` are state-only —
  no new `SHEET_COLUMNS` entries (spec Part 2).
- Spec: `docs/superpowers/specs/2026-07-21-competitor-displacement-and-persona-drafts-design.md`
  — read it first; this plan implements it task-by-task and does not repeat its rationale.

---

## File Structure

New:
- `gtm/displace.py` — `detect_competitor()` (deterministic), `build_displacement_prompt()`.
- `tests/test_displace.py`
- `tests/test_voice_guide.py`

Modified:
- `company/ICP.md` — scoring table + paragraph rename/flip, new outreach-angle line.
- `gtm/segment.py` — routes competitor detection through `gtm.displace`, new
  `"competitor-displacement"` bucket.
- `gtm/schema.py` — new `DraftSet` model, `Prospect.drafts_by_tier`, `Prospect.competitor`,
  `Prospect.competitor_weaknesses`; removes the 8 flat `draft_*` fields + `qa_flag`.
- `gtm/persona.py` — new `distinct_tiers_present()`.
- `gtm/draft.py` — `build_draft_prompt`/`build_redraft_prompt`/`qa_check` become tier-aware
  (take an explicit `tier`/`DraftSet` instead of inferring from `Prospect.contact_title`).
- `gtm/run.py` — `cmd_enrich` prints displacement prompts + `merge_signals` merges
  `competitor_weaknesses`; `cmd_segment` prints one draft prompt per distinct tier;
  `merge_drafts`/`cmd_draft`/`cmd_redraft` operate per-tier.
- `gtm/output.py` — `build_contact_rows` picks the tier-matching `DraftSet` per contact.
- `company/voice-guide.md` — category-only social proof, new "Specificity" rule.
- `tests/test_fit.py`, `tests/test_segment.py`, `tests/test_schema.py`, `tests/test_persona.py`,
  `tests/test_draft.py`, `tests/test_run.py`, `tests/test_output.py` — updated per above.

---

## Task 1: ICP.md — flip the displacement-opportunity scoring

**Files:**
- Modify: `company/ICP.md:79`, `company/ICP.md:87-90`, `company/ICP.md:98-102`
- Test: `tests/test_fit.py` (new test appended)

**Interfaces:**
- Consumes: nothing (docs-only; `gtm/fit.py::build_fit_prompt` already interpolates
  `company/ICP.md`'s text verbatim, no code depends on the old wording).
- Produces: the ICP text later tasks' prompts read; Task 3's `"competitor-displacement"`
  segment name should read naturally against this file's new outreach-angle line.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_fit.py`:

```python
from pathlib import Path


def test_icp_uses_displacement_opportunity_not_upgrade_gap():
    text = Path("company/ICP.md").read_text()
    assert "Displacement opportunity" in text
    lowered = text.lower()
    assert "upgrade gap" not in lowered
    assert "upgrade-gap" not in lowered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_fit.py::test_icp_uses_displacement_opportunity_not_upgrade_gap -v`
Expected: FAIL (ICP.md still says "Upgrade gap").

- [ ] **Step 3: Edit company/ICP.md**

Replace the scoring table row (currently `| Ships in weak/generic case today (upgrade gap) | 15 | Scrape |`):

```markdown
| Displacement opportunity — named competitor case, or blank slate | 15 | Scrape + enrichment |
```

Replace the paragraph directly below the table (currently starting "Upgrade-gap scoring must cite case_evidence..."):

```markdown
Displacement-opportunity scoring must cite case_evidence: a named rugged-case competitor
(Pelican, Nanuk, SKB, Hardigg, Seahorse, Explorer, etc.) is a concrete displacement target —
score 12-15/15 and say so; a soft bag/generic case/no case at all is still an upgrade
opportunity but with no named incumbent to research — score 8-11/15. If case_evidence is
still unknown after the web hunt, score exactly 3/15 and write "unknown" — never award
midpoint points for missing evidence.
```

In the "Outreach angles" section, add one new bullet after the existing "Generic case today" line:

```markdown
- **Competitor detected** → named-competitor weakness, cited — displace with proof.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_fit.py -v`
Expected: PASS (all tests, including the new one).

- [ ] **Step 5: Commit**

```bash
git add company/ICP.md tests/test_fit.py
git commit -m "$(cat <<'EOF'
feat: flip displacement-opportunity fit scoring (competitor = opportunity)

A named incumbent case now scores 12-15/15 (concrete displacement target,
researched by gtm/displace.py) instead of 0-3/15 (penalty for "displacing
an established brand"). Renamed from "Upgrade gap".

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `gtm/displace.py` — deterministic competitor detection + research prompt

**Files:**
- Create: `gtm/displace.py`
- Test: `tests/test_displace.py`

**Interfaces:**
- Produces: `detect_competitor(case_evidence: str) -> str` (`""` if no known brand matches,
  else `"<Brand>"` or `"<Brand> <model>"`); `build_displacement_prompt(company: str,
  competitor: str) -> str`; `_RUGGED_BRANDS: tuple[str, ...]` (moved here from
  `gtm/segment.py`, canonical location — Task 3 imports it from here).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_displace.py`:

```python
"""New stage: deterministic competitor detection + displacement research prompt."""
from gtm.displace import build_displacement_prompt, detect_competitor


def test_detect_competitor_named_brand_with_model_number():
    assert detect_competitor("ships in a Pelican 1520 case") == "Pelican 1520"


def test_detect_competitor_named_brand_no_model_number():
    assert detect_competitor("upgraded to a Nanuk case") == "Nanuk"


def test_detect_competitor_case_insensitive():
    assert detect_competitor("ships in a PELICAN case") == "Pelican"


def test_detect_competitor_no_match_on_generic_case():
    assert detect_competitor("ships in a soft backpack") == ""


def test_detect_competitor_empty_evidence():
    assert detect_competitor("") == ""


def test_detect_competitor_explorer_case_brand():
    assert detect_competitor("uses an Explorer Case 5325") == "Explorer Case 5325"


def test_build_displacement_prompt_names_company_and_competitor():
    prompt = build_displacement_prompt("AeroVironment", "Pelican 1520")
    assert "AeroVironment" in prompt
    assert "Pelican 1520" in prompt
    assert "reddit-find" in prompt
    assert "company-research" in prompt
    assert "competitor_weaknesses" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_displace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gtm.displace'`.

- [ ] **Step 3: Write the implementation**

Create `gtm/displace.py`:

```python
"""New stage: turn a detected competitor case into cited email ammo.

detect_competitor() is pure Python (regex against case_evidence, already
extracted by gtm/extract.py) — zero extra LLM cost, credit-efficient per
CLAUDE.md. build_displacement_prompt() is a Claude-checkpoint prompt, same
pattern as gtm/enrich.py::build_signal_prompt — Claude does the research
judgment (via the reddit-find and company-research skills), Python only
builds the prompt and detects the trigger.
"""
from __future__ import annotations

import re

# Canonical home for the rugged-case-brand keyword list — gtm/segment.py
# imports this rather than keeping its own copy.
_RUGGED_BRANDS = ("pelican", "seahorse", "nanuk", "skb", "hardigg", "explorer case")

_MODEL_TOKEN = re.compile(r"\b[A-Za-z]*\d[\dA-Za-z-]*\b")


def detect_competitor(case_evidence: str) -> str:
    """Deterministic brand detection, no LLM call. Returns "<Brand>" or
    "<Brand> <model>" (e.g. "Pelican 1520") when a model-number-shaped token
    appears in the same short evidence string, "" if no known brand matches."""
    evidence = case_evidence or ""
    lowered = evidence.lower()
    for brand in _RUGGED_BRANDS:
        idx = lowered.find(brand)
        if idx == -1:
            continue
        name = "Explorer Case" if brand == "explorer case" else brand.title()
        model = _MODEL_TOKEN.search(evidence[idx + len(brand):])
        return f"{name} {model.group()}" if model else name
    return ""


def build_displacement_prompt(company: str, competitor: str) -> str:
    return f"""Research displacement ammo for {company}, whose drones currently ship in a
{competitor} case (a named competitor product, not ours).

Use the reddit-find and company-research skills — not a single search — to find 2-3
concrete, cited weaknesses or complaints about the {competitor} specifically (e.g. "too
heavy", "cracks in cold weather", reddit threads calling it out by name). Plain English,
one line per weakness: "<complaint> — <source/context>".

Reply with ONLY this JSON (no prose), keyed by company name:
{{"{company}": {{"competitor_weaknesses": ["...", "..."]}}}}"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_displace.py -v`
Expected: PASS (all 7 tests).

- [ ] **Step 5: Commit**

```bash
git add gtm/displace.py tests/test_displace.py
git commit -m "$(cat <<'EOF'
feat: deterministic competitor detection + displacement research prompt

detect_competitor() reuses regex-based brand matching (no new LLM call,
credit-efficient) so a named incumbent case becomes a Claude checkpoint
prompt instructing use of reddit-find/company-research to find cited
weaknesses — the email ammo the user asked for.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `gtm/segment.py` — route through `gtm.displace`, new bucket

**Files:**
- Modify: `gtm/segment.py` (full file, shown below)
- Test: `tests/test_segment.py`

**Interfaces:**
- Consumes: `gtm.displace.detect_competitor(case_evidence: str) -> str` (Task 2).
- Produces: `assign_segment(p: Prospect) -> str` — unchanged signature, new possible return
  value `"competitor-displacement"`, checked before `"generic-case-upgrade"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_segment.py`, replace `test_named_rugged_brand_does_not_count_as_upgrade_gap`
with:

```python
def test_named_competitor_brand_gives_displacement_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="upgraded to a soft-sided Pelican-branded case")
    assert assign_segment(p) == "competitor-displacement"


def test_ndaa_beats_competitor_displacement():
    # priority order: defense-ndaa-win beats competitor-displacement even when both match
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=True, case_evidence="ships in a Pelican 1520 case")
    assert assign_segment(p) == "defense-ndaa-win"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/pytest tests/test_segment.py -v`
Expected: FAIL — `assign_segment` still returns something other than `"competitor-displacement"`
(current code returns whatever the old brand-exclusion logic produces, not the new bucket name).

- [ ] **Step 3: Rewrite gtm/segment.py**

```python
"""New stage: deterministic bucketing into one of ICP.md's 4 outreach angles.

Pure Python, no LLM call — assign_segment() picks which angle draft's prompt
should lean into. Checked in priority order (first match wins): the highest-
weighted Fit signal (NDAA/defense) is the strongest hook when present; a named
competitor (gtm/displace.py) is a stronger, more specific hook than a blank
slate.
"""
from __future__ import annotations

from gtm.displace import detect_competitor
from gtm.schema import Prospect

_UPGRADE_KEYWORDS = ("soft bag", "backpack", "soft case", "generic case", "foam insert")
_LAUNCH_KEYWORDS = ("launch", "new model", "unveil", "announc")


def assign_segment(p: Prospect) -> str:
    if p.us_made_ndaa is True:
        return "defense-ndaa-win"

    if detect_competitor(p.case_evidence):
        return "competitor-displacement"

    evidence = p.case_evidence.lower()
    if any(kw in evidence for kw in _UPGRADE_KEYWORDS):
        return "generic-case-upgrade"

    if any(kw in s.lower() for s in p.buying_signals for kw in _LAUNCH_KEYWORDS):
        return "new-model-launch"

    return "field-harsh-environment"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_segment.py -v`
Expected: PASS (all tests, including the untouched ones — `defense-ndaa-win`,
`generic-case-upgrade`, `new-model-launch`, `field-harsh-environment` behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add gtm/segment.py tests/test_segment.py
git commit -m "$(cat <<'EOF'
feat: segment.py routes competitor detection through gtm.displace

New "competitor-displacement" bucket replaces the old brand-exclusion
logic in assign_segment — a named incumbent is now the strongest,
most specific outreach hook (checked before generic-case-upgrade),
consistent with the fit-scoring flip in Task 1.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `gtm/schema.py` — `DraftSet` model + `drafts_by_tier`, `competitor` fields

**Files:**
- Modify: `gtm/schema.py:56-101` (the `Prospect` class body — insert a new `DraftSet` class
  above it, replace the 8 flat `draft_*` fields + `qa_flag` with `drafts_by_tier`, add
  `competitor`/`competitor_weaknesses`)
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `class DraftSet(BaseModel)` with fields `initial_subject`, `initial_body`,
  `initial_subject_alt`, `initial_body_alt`, `followup_subject`, `followup_body`,
  `followup_subject_alt`, `followup_body_alt`, `qa_flag` (all `str = ""`).
  `Prospect.drafts_by_tier: dict[str, DraftSet] = {}`, `Prospect.competitor: str = ""`,
  `Prospect.competitor_weaknesses: list[str] = []`. Every later task (`gtm/draft.py`,
  `gtm/run.py`, `gtm/output.py`) imports `DraftSet` from `gtm.schema`.
- Removes: `Prospect.draft_initial_subject`, `draft_initial_body`, `draft_initial_subject_alt`,
  `draft_initial_body_alt`, `draft_followup_subject`, `draft_followup_body`,
  `draft_followup_subject_alt`, `draft_followup_body_alt`, `qa_flag` — no shim, nothing
  outside this codebase reads `prospects.json` directly.

- [ ] **Step 1: Write the failing tests**

In `tests/test_schema.py`, change the import line to:

```python
from gtm.schema import DraftSet, Prospect, SHEET_COLUMNS
```

Replace `test_outreach_drafts_qa_status_are_state_only_not_on_main_sheet` with:

```python
def test_outreach_drafts_qa_status_are_state_only_not_on_main_sheet():
    # 2026-07-21: main sheet = company…community_signals only. outreach_angle,
    # competitor/competitor_weaknesses, drafts_by_tier, source, date_processed,
    # and status all live on the Contacts tab (gtm/output.py) or in local state,
    # never on the main row.
    for col in (
        "outreach_angle", "competitor", "competitor_weaknesses",
        "drafts_by_tier", "source", "date_processed", "status",
    ):
        assert col not in SHEET_COLUMNS

    p = Prospect(
        company="X", website="https://x.com",
        outreach_angle="the hook",
        competitor="Pelican 1520",
        competitor_weaknesses=["too heavy — reddit thread"],
        drafts_by_tier={"c-suite": DraftSet(initial_subject="Case built for the Teal 2?", qa_flag="unsupported claim")},
        status="priority",
    )
    row = p.to_sheet_row()
    assert "Case built for the Teal 2?" not in row
    assert "Pelican 1520" not in row
    # fields still exist on the model for draft.py / hubspot.py / the Contacts tab
    assert p.drafts_by_tier["c-suite"].initial_subject == "Case built for the Teal 2?"
    assert p.drafts_by_tier["c-suite"].qa_flag == "unsupported claim"
    assert p.competitor == "Pelican 1520"
    assert p.status == "priority"
```

Append three new tests to `tests/test_schema.py`:

```python
def test_draft_set_defaults_all_blank():
    d = DraftSet()
    assert d.initial_subject == ""
    assert d.qa_flag == ""


def test_prospect_drafts_by_tier_defaults_empty_dict():
    p = Prospect(company="X", website="https://x.com")
    assert p.drafts_by_tier == {}


def test_drafts_by_tier_roundtrips_through_json():
    p = Prospect(
        company="X", website="https://x.com",
        drafts_by_tier={"director": DraftSet(initial_subject="Subj")},
    )
    again = Prospect.model_validate_json(p.model_dump_json())
    assert again.drafts_by_tier["director"].initial_subject == "Subj"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'DraftSet' from 'gtm.schema'`.

- [ ] **Step 3: Edit gtm/schema.py**

Insert this class immediately before `class Prospect(BaseModel):`:

```python
class DraftSet(BaseModel):
    """One 2-email (initial + follow-up), 2-version cold-email draft, plus its
    own fact-check flag. One of these per persona tier present at a company
    (gtm/persona.py::distinct_tiers_present) — a CFO and a director never
    share a draft."""
    initial_subject: str = ""
    initial_body: str = ""
    initial_subject_alt: str = ""
    initial_body_alt: str = ""
    followup_subject: str = ""
    followup_body: str = ""
    followup_subject_alt: str = ""
    followup_body_alt: str = ""
    qa_flag: str = ""
```

Replace the block from `linkedin: str = ""` (currently just above `outreach_angle`) through
the old `qa_flag: str = ""` line with:

```python
    linkedin: str = ""
    community_signals: list[str] = []
    outreach_angle: str = ""
    # stage "enrich" (displacement sub-step, gtm/displace.py) — state-only, feeds
    # draft's value-prop ammo; "" / [] when no named competitor was detected.
    competitor: str = ""
    competitor_weaknesses: list[str] = []
    # stage "segment" — deterministic bucketing, feeds draft's angle choice; not a sheet column
    segment: str = ""
    # stage "draft" — one DraftSet per distinct persona tier present among this
    # company's contacts (gtm/persona.py::distinct_tiers_present). Replaces the
    # old single flat draft_*/qa_flag fields — gtm/output.py::build_contact_rows
    # picks the matching-tier entry per contact row.
    drafts_by_tier: dict[str, DraftSet] = {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add gtm/schema.py tests/test_schema.py
git commit -m "$(cat <<'EOF'
feat: DraftSet model + Prospect.drafts_by_tier replace flat draft fields

Prepares the schema for persona-tiered drafts: one DraftSet per distinct
tier present at a company instead of one shared draft. No backwards-
compat shim — nothing outside this codebase reads prospects.json.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `gtm/persona.py` — `distinct_tiers_present()`

**Files:**
- Modify: `gtm/persona.py` (append helper + import)
- Test: `tests/test_persona.py`

**Interfaces:**
- Consumes: `Prospect.contact_title` shape — a `CONTACT_FIELD_SEP`-joined string
  (`gtm.schema.CONTACT_FIELD_SEP`, already `"; "`).
- Produces: `distinct_tiers_present(contact_titles: str) -> list[str]` — distinct
  `classify_persona()` results in first-seen order; `["unknown"]` for blank input, never `[]`.
  Task 8 (`gtm/run.py::cmd_segment`) and Task 9 (`gtm/output.py::build_contact_rows`, via
  `classify_persona` directly per-contact) both depend on this.

- [ ] **Step 1: Write the failing tests**

Replace the top import line of `tests/test_persona.py` (currently
`from gtm.persona import classify_persona`) with:

```python
from gtm.persona import classify_persona, distinct_tiers_present
from gtm.schema import CONTACT_FIELD_SEP
```

Append to `tests/test_persona.py`:

```python
def test_distinct_tiers_present_dedupes_same_tier():
    # real AeroVironment titles (2026-07-21 handoff) — both classify c-suite
    titles = CONTACT_FIELD_SEP.join(["Vice President and Chief Technologist", "VP Logistics Operations"])
    assert distinct_tiers_present(titles) == ["c-suite"]


def test_distinct_tiers_present_keeps_distinct_tiers_in_order():
    titles = CONTACT_FIELD_SEP.join(["Vice President and Chief Technologist", "Senior Director International Sales"])
    assert distinct_tiers_present(titles) == ["c-suite", "director"]


def test_distinct_tiers_present_blank_titles_default_to_unknown():
    assert distinct_tiers_present("") == ["unknown"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_persona.py -v`
Expected: FAIL — `ImportError: cannot import name 'distinct_tiers_present' from 'gtm.persona'`.

- [ ] **Step 3: Edit gtm/persona.py**

Add this import at the top (after the existing `import re`):

```python
from gtm.schema import CONTACT_FIELD_SEP
```

Add this function at the end of the file:

```python
def distinct_tiers_present(contact_titles: str) -> list[str]:
    """contact_titles: the CONTACT_FIELD_SEP-joined Prospect.contact_title field.
    Returns distinct classify_persona() tiers, in first-seen order. Blank/empty
    titles produce ["unknown"] (a single default draft, never zero)."""
    titles = [t.strip() for t in contact_titles.split(CONTACT_FIELD_SEP)] if contact_titles else [""]
    tiers: list[str] = []
    for t in titles:
        tier = classify_persona(t)
        if tier not in tiers:
            tiers.append(tier)
    return tiers
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_persona.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add gtm/persona.py tests/test_persona.py
git commit -m "$(cat <<'EOF'
feat: distinct_tiers_present() — which persona tiers a company's contacts span

Confirmed against the real AeroVironment titles from the prior session's
handoff: "Vice President and Chief Technologist" and "VP Logistics
Operations" both classify c-suite (bare "vp" match — a known quirk, not
fixed here), "Senior Director International Sales" classifies director.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `gtm/draft.py` — tier-aware prompts + competitor-ammo block

**Files:**
- Modify: `gtm/draft.py` (full file, shown below)
- Test: `tests/test_draft.py` (full file, shown below)

**Interfaces:**
- Consumes: `gtm.schema.DraftSet` (Task 4).
- Produces: `build_draft_prompt(voice_guide: str, p: Prospect, tier: str) -> str` (was:
  `(voice_guide, p)`, no `tier` arg, inferred persona from `p.contact_title`'s first entry).
  `build_redraft_prompt(voice_guide: str, p: Prospect, tier: str, draft: DraftSet) -> str`
  (was: `(voice_guide, p)`, read `p.qa_flag`). `qa_check(p: Prospect, draft: DraftSet, *,
  client=None, costlog=None) -> str` (was: `(p, *, client=None, costlog=None)`, read
  `p.draft_initial_subject` etc directly). Task 8 (`gtm/run.py`) calls all three with the
  new signatures.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_draft.py`:

```python
import pytest

from gtm.draft import QAError, QAResult, build_draft_prompt, build_redraft_prompt, qa_check
from gtm.schema import DraftSet, Prospect

VOICE_GUIDE_SAMPLE = "## Tone\nWarm, consultative.\n## Banned phrases\ncircle back"


def test_build_draft_prompt_embeds_voice_guide_and_prospect_fields():
    p = Prospect(
        company="Teal Drones", website="https://tealdrones.com",
        segment="defense-ndaa-win", outreach_angle="US-made, MIL-STD case to match your US-made drone.",
        buying_signals=["SRR win — US Army contract (source, 2026-05-01)"],
        key_news=["Teal wins SRR — ..."],
        fit_reason="NDAA/defense 15/15 — US Army SRR program",
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


def test_qa_check_flags_unsupported_claim_in_followup_email():
    draft = DraftSet(
        initial_subject="Case built for the Teal 2?",
        initial_body="{FIRST_NAME} — saw Teal's SRR win. Worth 10 min?",
        followup_subject="Following up on SRR opportunity",
        followup_body="Just checking if you saw our $5M contract offer — sounds like a fit?",
    )
    flag_text = "follow-up: references a $5M contract not in evidence"
    client = _FakeClient(QAResult(flag=flag_text))
    result = qa_check(_prospect(), draft, client=client)

    assert result == flag_text

    user_message = next((m["content"] for m in client.last_messages if m["role"] == "user"), None)
    assert user_message is not None
    assert "{FIRST_NAME} — saw Teal's SRR win. Worth 10 min?" in user_message
    assert "Just checking if you saw our $5M contract offer — sounds like a fit?" in user_message


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_draft.py -v`
Expected: FAIL — `TypeError: build_draft_prompt() missing 1 required positional argument: 'tier'`
(current signature is `(voice_guide, p)`).

- [ ] **Step 3: Rewrite gtm/draft.py**

```python
"""New stage: draft cold emails via a Claude checkpoint prompt (build_draft_prompt),
then automated gpt-4.1-mini fact-check (qa_check) once merged.

Claude does the judgment (drafting, matching company/voice-guide.md's tone) —
Python only builds the prompt and, after the human round-trip, fact-checks it.
One call per (prospect, persona tier present) pair — a CFO and a director at
the same company never get the same email.
"""
from __future__ import annotations

from pydantic import BaseModel

from gtm.costlog import CostLog
from gtm.schema import DraftSet, Prospect

MODEL = "gpt-4.1-mini"
# docs/tools/openai.md — confirmed live 2026-07-20, still API-accessible though
# retired from the ChatGPT consumer UI.
PRICE_IN, PRICE_OUT = 0.40 / 1e6, 1.60 / 1e6


class QAError(Exception):
    pass


class QAResult(BaseModel):
    flag: str = ""  # empty = every claim is supported; else a short note of what isn't


def build_draft_prompt(voice_guide: str, p: Prospect, tier: str) -> str:
    contact_block = ""
    if tier != "unknown":
        contact_block = (
            f"\n## This contact (tailor the pitch to their seniority)\n"
            f"- persona tier: {tier}\n"
            f"This draft is for every contact at {p.company} classified into the '{tier}' "
            f"tier (gtm/persona.py::classify_persona) — apply the matching rule from the "
            f"voice guide's \"Persona tailoring\" section.\n"
        )

    competitor_block = ""
    if p.competitor_weaknesses:
        weaknesses = "\n".join(f"- {w}" for w in p.competitor_weaknesses)
        competitor_block = (
            f"\n## Displacement ammo — {p.company} currently ships in a {p.competitor} case\n"
            f"Name {p.competitor} specifically in the value prop and cite ONE of these "
            f"researched weaknesses verbatim — never a generic \"better than X\" claim:\n"
            f"{weaknesses}\n"
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
{contact_block}{competitor_block}
## Structure (self-enforce — from the voice guide's "Email structure")
1. Open with a real, specific fact about {p.company} (drawn from outreach_angle /
   buying_signals / key_news) — never a generic greeting or banned opener.
2. Value prop: a use case + social proof (category-level only — AeroVault has no named
   customers to cite) + the pain it removes.
3. Close with ONE closed-ended (yes/no) ask or a low-pressure negative-CTA — never stack asks.
Tailor the value prop to the '{tier}' persona tier (see the voice guide's "Persona tailoring").

## Format (self-enforce — do not exceed)
- Subject line: under 40 characters, TRIGGER-FIRST — lead with the prospect's own
  event or pain (from outreach_angle / buying_signals / key_news), never with our
  product-line names (AV-Field, AV-Micro, AV-Ops, AV-Convoy) — the prospect has never
  heard them. Good: "Switchblade 400 field kit?". Bad: "AV-Field case for X?".
- Body: capped at ~150 characters — one or two sentences, no more.
- Personalization variables: {{FIRST_NAME}}, {{COMPANY}}.
- No links in the body. No banned phrases (see voice guide). Close with the signature block
  from the voice guide.

Reply with ONLY this JSON (no prose), keyed by company name then persona tier:
{{"{p.company}": {{"{tier}": {{"draft_initial": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}},
"draft_followup": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}}}}}}}}

Save the answer to drafts.json."""


def build_redraft_prompt(voice_guide: str, p: Prospect, tier: str, draft: DraftSet) -> str:
    """Same brief as build_draft_prompt, plus the QA fact-check failure reason
    (draft.qa_flag) so the rewrite fixes only the flagged claim, not a fresh draft."""
    base = build_draft_prompt(voice_guide, p, tier)
    return (
        f"{base}\n\n## QA rewrite required\n"
        f"The previous draft failed fact-check: {draft.qa_flag}\n"
        f"Rewrite to remove or fix that unsupported claim — keep everything else "
        f"(tone, structure, format) as specified above."
    )


def qa_check(p: Prospect, draft: DraftSet, *, client=None, costlog: CostLog | None = None) -> str:
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    evidence = (
        f"buying_signals: {p.buying_signals}\nkey_news: {p.key_news}\nfit_reason: {p.fit_reason}"
    )
    initial = f"Subject: {draft.initial_subject}\n{draft.initial_body}"
    followup = f"Subject: {draft.followup_subject}\n{draft.followup_body}"
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You fact-check a cold email sequence (initial + follow-up) against the "
                    "evidence used to write them. Flag ONLY if either email references a "
                    "specific stat, contract, certification, or event that is NOT supported by "
                    "the evidence. Do not flag tone, length, or phrasing. If you flag something, "
                    'say which email ("initial" or "follow-up") it came from. Reply with '
                    'flag="" if every claim in both emails is supported.'
                ),
            },
            {"role": "user", "content": f"Evidence:\n{evidence}\n\nInitial Email:\n{initial}\n\nFollow-up Email:\n{followup}"},
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_draft.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add gtm/draft.py tests/test_draft.py
git commit -m "$(cat <<'EOF'
feat: tier-aware draft prompts + competitor-ammo block

build_draft_prompt/build_redraft_prompt/qa_check take an explicit tier
(and DraftSet) instead of inferring persona from the top contact only.
When gtm/displace.py found a competitor, the prompt now requires citing
a specific researched weakness instead of the vague "better than X"
framing that prompted this whole design. Social proof forced category-
level (AeroVault has no real customers).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `gtm/run.py` — `cmd_enrich` prints displacement prompts

**Files:**
- Modify: `gtm/run.py:295-327` (`cmd_enrich`), `gtm/run.py:211-217` (`merge_signals`)
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `gtm.displace.detect_competitor(case_evidence: str) -> str`,
  `gtm.displace.build_displacement_prompt(company: str, competitor: str) -> str` (Task 2).
- Produces: `merge_signals(prospects, signals: dict)` now also sets
  `p.competitor_weaknesses` from `signals[company].get("competitor_weaknesses", [])`.
  `cmd_enrich` sets `p.competitor` on every `priority`/`keep` prospect and prints a
  displacement prompt block for the ones where it's truthy.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run.py`:

```python
def test_cmd_enrich_prints_displacement_prompt_when_competitor_detected(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(
        company="AeroVironment", website="https://avinc.com", fit_score=87, status="priority",
        case_evidence="ships in a Pelican 1520 case",
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_enrich("teal-demo-displace")

    out = capsys.readouterr().out
    assert "displacement: Pelican 1520" in out
    assert "Pelican 1520" in out

    saved = load_state(tmp_path)
    assert saved[0].competitor == "Pelican 1520"


def test_cmd_enrich_no_displacement_prompt_when_no_competitor(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(
        company="Teal Drones", website="https://tealdrones.com", fit_score=87, status="priority",
        case_evidence="ships in a soft backpack",
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_enrich("teal-demo-nodisplace")

    out = capsys.readouterr().out
    assert "displacement" not in out
```

Replace `test_merge_signals_by_company` with:

```python
def test_merge_signals_by_company():
    ps = [Prospect(company="A", website="https://a.com")]
    merge_signals(ps, {"A": {
        "buying_signals": ["won contract"], "outreach_angle": "case for new drone",
        "competitor_weaknesses": ["too heavy"],
    }})
    assert ps[0].buying_signals == ["won contract"]
    assert ps[0].outreach_angle == "case for new drone"
    assert ps[0].competitor_weaknesses == ["too heavy"]
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/pytest tests/test_run.py -k "displacement or merge_signals_by_company" -v`
Expected: FAIL — `AttributeError`/`AssertionError` (`p.competitor` doesn't exist yet on this
code path, `competitor_weaknesses` never merged, no displacement prompt printed).

- [ ] **Step 3: Edit gtm/run.py**

Replace `cmd_enrich`:

```python
def cmd_enrich(run: str) -> None:
    from gtm.contacts import find_contacts, top_contact_fields
    from gtm.displace import build_displacement_prompt, detect_competitor
    from gtm.enrich import build_signal_prompt, enrich

    with _track_stage(run, "enrich"):
        run_costlog(run)  # arms serper credit logging for enrich + contacts
        prospects = load_state(run_dir(run))
        for p in prospects:
            if p.status not in ("priority", "keep"):
                continue
            try:
                enrich(p)
                contacts = find_contacts(p.company)
                if contacts:
                    p.contact_name, p.contact_title, p.contact_linkedin = top_contact_fields(contacts)
                p.competitor = detect_competitor(p.case_evidence)
            except Exception as e:
                _log_error(ERROR_LOG, p.company, "enrich/contacts", e)
        save_state(prospects, run_dir(run))
        print("\n=== SIGNAL PROMPTS — Claude: answer each, save {company: {...}} to signals.json ===")
        needs_signals = False
        for p in prospects:
            if p.status in ("priority", "keep"):
                needs_signals = True
                print(f"\n----- {p.company} -----")
                print(build_signal_prompt(p))
                if p.competitor:
                    print(f"\n----- {p.company} [displacement: {p.competitor}] -----")
                    print(build_displacement_prompt(p.company, p.competitor))

        _print_cost_summary(run)
        if needs_signals:
            raise CheckpointPending(
                file="signals.json",
                action="answer signal prompts",
                resume=f"python -m gtm.run signals {run} signals.json",
            )
```

Replace `merge_signals`:

```python
def merge_signals(prospects: list[Prospect], signals: dict[str, dict]) -> None:
    for p in prospects:
        s = signals.get(p.company)
        if s:
            p.buying_signals = s.get("buying_signals", [])
            p.outreach_angle = s.get("outreach_angle", "")
            p.competitor_weaknesses = s.get("competitor_weaknesses", [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_run.py -v`
Expected: PASS (all tests — the unrelated `cmd_enrich`/`cmd_signals` tests are unaffected
since `detect_competitor("")` is `""`, so prospects without `case_evidence` behave exactly
as before).

- [ ] **Step 5: Commit**

```bash
git add gtm/run.py tests/test_run.py
git commit -m "$(cat <<'EOF'
feat: cmd_enrich prints displacement research prompts for detected competitors

Folded into the existing signals.json checkpoint round-trip (no new CLI
stage) per the spec's resolved design decision — one checkpoint, not two.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `gtm/run.py` — per-tier `cmd_segment`/`merge_drafts`/`cmd_draft`/`cmd_redraft`

**Files:**
- Modify: `gtm/run.py:33` (import), `gtm/run.py:219-232` (`merge_drafts`),
  `gtm/run.py:338-360` (`cmd_segment`), `gtm/run.py:363-397` (`cmd_draft`),
  `gtm/run.py:400-425` (`cmd_redraft`)
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `gtm.persona.distinct_tiers_present(contact_titles: str) -> list[str]` (Task 5),
  `gtm.draft.build_draft_prompt(voice_guide, p, tier)`,
  `gtm.draft.build_redraft_prompt(voice_guide, p, tier, draft)`,
  `gtm.draft.qa_check(p, draft, **kw)` (Task 6), `gtm.schema.DraftSet` (Task 4).
- Produces: `merge_drafts(prospects, raw: dict)` — `raw` shape is now
  `{"<company>": {"<tier>": {"draft_initial": {...}, "draft_followup": {...}}}}`. Task 9
  (`gtm/output.py::build_contact_rows`) reads the resulting `p.drafts_by_tier` directly.

**A non-obvious invariant this task must preserve** (write the test for it explicitly, don't
skip): `merge_drafts` must update an *existing* tier's `DraftSet` **content fields in place**
(`setdefault` + attribute assignment), never replace the object wholesale. If it replaced the
object, `cmd_redraft`'s re-merge of a fixed draft would silently reset that tier's `qa_flag`
back to `""` before the "skip already-passed" check runs, and the redraft QA loop would wrongly
skip re-checking the very tier it was supposed to fix. This mirrors the old code's behavior,
where draft content and `qa_flag` were separate fields with independent lifecycles.

- [ ] **Step 1: Write the failing tests**

In `tests/test_run.py`, add `DraftSet` to the `gtm.schema` import used by tests in this file
(add `from gtm.schema import DraftSet, Prospect` near the top, replacing the existing
`from gtm.schema import Prospect`).

Replace `test_merge_drafts_writes_v1_to_surfaced_fields_v2_to_alt_fields` and
`test_merge_drafts_skips_companies_not_in_raw` with:

```python
def test_merge_drafts_writes_v1_to_surfaced_fields_v2_to_alt_fields():
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    raw = {
        "Teal Drones": {
            "c-suite": {
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
    }
    merge_drafts(prospects, raw)
    draft = prospects[0].drafts_by_tier["c-suite"]
    assert draft.initial_subject == "Case built for the Teal 2?"
    assert draft.initial_body == "hook v1"
    assert draft.initial_subject_alt == "US-made case, Teal-sized"
    assert draft.initial_body_alt == "hook v2"
    assert draft.followup_subject == "Following up"
    assert draft.followup_body_alt == "follow v2"


def test_merge_drafts_skips_companies_not_in_raw():
    prospects = [Prospect(company="Untouched Co", website="https://x.com", status="priority")]
    merge_drafts(prospects, {})
    assert prospects[0].drafts_by_tier == {}


def test_merge_drafts_multiple_tiers_land_in_separate_draft_sets():
    prospects = [Prospect(company="AeroVironment", website="https://avinc.com", status="priority")]
    raw = {
        "AeroVironment": {
            "c-suite": {"draft_initial": {"v1": {"subject": "C-suite subject", "body": "b"}}, "draft_followup": {}},
            "director": {"draft_initial": {"v1": {"subject": "Director subject", "body": "b"}}, "draft_followup": {}},
        }
    }
    merge_drafts(prospects, raw)
    assert prospects[0].drafts_by_tier["c-suite"].initial_subject == "C-suite subject"
    assert prospects[0].drafts_by_tier["director"].initial_subject == "Director subject"


def test_merge_drafts_preserves_qa_flag_on_existing_tier_content_update():
    # Redraft round-trip: re-merging new content for an already-flagged tier must
    # NOT reset its qa_flag — cmd_redraft's "already checked" skip logic depends
    # on the flag surviving until its own QA loop overwrites it.
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    merge_drafts(prospects, {"Teal Drones": {"c-suite": {"draft_initial": {"v1": {"subject": "Old", "body": "b"}}, "draft_followup": {}}}})
    prospects[0].drafts_by_tier["c-suite"].qa_flag = "unsupported claim"

    merge_drafts(prospects, {"Teal Drones": {"c-suite": {"draft_initial": {"v1": {"subject": "Fixed", "body": "b2"}}, "draft_followup": {}}}})

    draft = prospects[0].drafts_by_tier["c-suite"]
    assert draft.initial_subject == "Fixed"
    assert draft.qa_flag == "unsupported claim"  # untouched by content-only merge
```

Replace `test_cmd_segment_assigns_and_raises_checkpoint_for_draft_prompts` (keep it as-is —
no change needed, `contact_title` is blank so it still exercises the `"unknown"`-tier single
prompt path) and add a new test after it:

```python
def test_cmd_segment_prints_one_draft_prompt_block_per_distinct_tier(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="AeroVironment", website="https://avinc.com", status="priority",
        contact_title="Vice President and Chief Technologist; Senior Director International Sales",
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_segment("teal-demo-tiers")

    out = capsys.readouterr().out
    assert "[c-suite]" in out
    assert "[director]" in out
```

Replace `test_cmd_draft_flags_unsupported_claim_and_raises_redraft_checkpoint`:

```python
def test_cmd_draft_flags_unsupported_claim_and_raises_redraft_checkpoint(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority", segment="defense-ndaa-win")]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "Case built for the Teal 2?", "body": "hook"}, "v2": {"subject": "s2", "body": "b2"}},
                "draft_followup": {"v1": {"subject": "Following up", "body": "f1"}, "v2": {"subject": "s4", "body": "b4"}},
            }
        }
    }))

    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "unsupported $1M claim")

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_draft("teal-demo-10", str(drafts_path))

    cp = exc_info.value
    assert cp.file == "drafts.json"
    assert "redraft" in cp.action
    assert "teal-demo-10" in cp.resume
    assert "redraft" in cp.resume

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].initial_subject == "Case built for the Teal 2?"
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "unsupported $1M claim"  # pending retry, not finalized

    out = capsys.readouterr().out
    assert "REDRAFT" in out
    assert "unsupported $1M claim" in out
```

Replace `test_cmd_draft_qa_failure_logs_and_skips_not_crashes`:

```python
def test_cmd_draft_qa_failure_logs_and_skips_not_crashes(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    monkeypatch.setattr(run_mod, "ERROR_LOG", tmp_path / "errors.log")
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "s", "body": "b"}, "v2": {"subject": "s2", "body": "b2"}},
                "draft_followup": {"v1": {"subject": "s3", "body": "b3"}, "v2": {"subject": "s4", "body": "b4"}},
            }
        }
    }))

    def _raise(p, draft, **kw):
        raise RuntimeError("API down")

    monkeypatch.setattr(run_mod, "qa_check", _raise)

    cmd_draft("teal-demo-11", str(drafts_path))  # must NOT raise

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == ""  # left blank, not blocked
    assert (tmp_path / "errors.log").exists()
```

Replace `test_cmd_redraft_merges_and_finalizes_qa_passed`,
`test_cmd_redraft_keeps_flag_text_if_still_failing_after_retry`, and
`test_cmd_redraft_does_not_recheck_already_passed_prospects`:

```python
def test_cmd_redraft_merges_and_finalizes_qa_passed(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Teal Drones", website="https://tealdrones.com", status="priority",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="old subject", qa_flag="unsupported $1M claim")},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "Fixed subject", "body": "fixed hook"}, "v2": {"subject": "s2", "body": "b2"}},
                "draft_followup": {"v1": {"subject": "Following up", "body": "f1"}, "v2": {"subject": "s4", "body": "b4"}},
            }
        }
    }))
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "")

    cmd_redraft("teal-demo-13", str(drafts_path))  # must NOT raise — single retry cap

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].initial_subject == "Fixed subject"
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "passed"


def test_cmd_redraft_keeps_flag_text_if_still_failing_after_retry(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Teal Drones", website="https://tealdrones.com", status="priority",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="old subject", qa_flag="unsupported $1M claim")},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "Still bad", "body": "still bad hook"}, "v2": {"subject": "s2", "body": "b2"}},
                "draft_followup": {"v1": {"subject": "Following up", "body": "f1"}, "v2": {"subject": "s4", "body": "b4"}},
            }
        }
    }))
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "still references unsupported claim")

    cmd_redraft("teal-demo-14", str(drafts_path))  # must NOT raise — no infinite retry loop

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "still references unsupported claim"


def test_cmd_redraft_does_not_recheck_already_passed_prospects(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Already Fine Co", website="https://x.com", status="priority",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="Fine subject", qa_flag="passed")},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({}))  # nothing to merge — this company wasn't flagged

    def _fail(p, draft, **kw):
        raise AssertionError("qa_check must not be called for an already-passed prospect")

    monkeypatch.setattr(run_mod, "qa_check", _fail)

    cmd_redraft("teal-demo-15", str(drafts_path))  # must NOT raise / must NOT call qa_check

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "passed"
```

Replace `test_cmd_segment_then_cmd_draft_resumes_cleanly`:

```python
def test_cmd_segment_then_cmd_draft_resumes_cleanly(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "")
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
            "unknown": {
                "draft_initial": {"v1": {"subject": "Case built for the Teal 2?", "body": "hook"}, "v2": {"subject": "s2", "body": "b2"}},
                "draft_followup": {"v1": {"subject": "Following up", "body": "f1"}, "v2": {"subject": "s4", "body": "b4"}},
            }
        }
    }))

    cmd_draft("teal-demo-12", str(drafts_path))  # exactly what the resume command runs

    saved = load_state(tmp_path)
    assert len(saved) == 1
    p = saved[0]
    assert p.segment == "defense-ndaa-win"  # survived the round-trip from cmd_segment
    assert p.drafts_by_tier["unknown"].initial_subject == "Case built for the Teal 2?"
    assert p.drafts_by_tier["unknown"].qa_flag == "passed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_run.py -v`
Expected: FAIL — multiple errors (`merge_drafts` still writes flat fields that no longer
exist on `Prospect`, `qa_check`/`build_draft_prompt` signature mismatches, etc).

- [ ] **Step 3: Edit gtm/run.py**

Change the schema import (currently `from gtm.schema import Prospect`) to:

```python
from gtm.schema import DraftSet, Prospect
```

Replace `merge_drafts`:

```python
def merge_drafts(prospects: list[Prospect], raw: dict) -> None:
    for p in prospects:
        tiers = raw.get(p.company)
        if not tiers:
            continue
        for tier, d in tiers.items():
            initial, followup = d.get("draft_initial", {}), d.get("draft_followup", {})
            # setdefault + in-place attribute writes (not a fresh DraftSet) so an
            # existing tier's qa_flag survives a content-only re-merge — the
            # cmd_redraft round-trip depends on this (see Task 8's docstring note).
            draft = p.drafts_by_tier.setdefault(tier, DraftSet())
            draft.initial_subject = initial.get("v1", {}).get("subject", "")
            draft.initial_body = initial.get("v1", {}).get("body", "")
            draft.initial_subject_alt = initial.get("v2", {}).get("subject", "")
            draft.initial_body_alt = initial.get("v2", {}).get("body", "")
            draft.followup_subject = followup.get("v1", {}).get("subject", "")
            draft.followup_body = followup.get("v1", {}).get("body", "")
            draft.followup_subject_alt = followup.get("v2", {}).get("subject", "")
            draft.followup_body_alt = followup.get("v2", {}).get("body", "")
```

Replace `cmd_segment`:

```python
def cmd_segment(run: str) -> None:
    from gtm.persona import distinct_tiers_present

    with _track_stage(run, "segment"):
        prospects = load_state(run_dir(run))
        for p in prospects:
            if p.status in ("priority", "keep"):
                p.segment = assign_segment(p)
        save_state(prospects, run_dir(run))

        voice_guide = VOICE_GUIDE.read_text()
        print("\n=== DRAFT PROMPTS — Claude: draft each, save {company: {tier: {...}}} to drafts.json ===")
        needs_draft = False
        for p in prospects:
            if p.status in ("priority", "keep"):
                needs_draft = True
                for tier in distinct_tiers_present(p.contact_title):
                    print(f"\n----- {p.company} [{tier}] -----")
                    print(build_draft_prompt(voice_guide, p, tier))

        if needs_draft:
            raise CheckpointPending(
                file="drafts.json",
                action="draft emails",
                resume=f"python -m gtm.run draft {run} drafts.json",
            )
```

Replace `cmd_draft`:

```python
def cmd_draft(run: str, drafts_json: str) -> None:
    with _track_stage(run, "draft"):
        prospects = load_state(run_dir(run))
        merge_drafts(prospects, json.loads(Path(drafts_json).read_text()))
        save_state(prospects, run_dir(run))

        costlog = run_costlog(run)
        n, flagged = 0, 0
        for p in prospects:
            for tier, draft in p.drafts_by_tier.items():
                if not draft.initial_subject:
                    continue
                n += 1
                try:
                    flag = qa_check(p, draft, costlog=costlog)
                    draft.qa_flag = flag or "passed"
                    if flag:
                        flagged += 1
                except Exception as e:
                    _log_error(ERROR_LOG, p.company, "qa", e)
        save_state(prospects, run_dir(run))
        print(f"{n} drafted, {flagged} flagged")
        _print_cost_summary(run)

        needs_redraft = [
            (p, tier, draft)
            for p in prospects
            for tier, draft in p.drafts_by_tier.items()
            if draft.qa_flag and draft.qa_flag != "passed"
        ]
        if needs_redraft:
            voice_guide = VOICE_GUIDE.read_text()
            print("\n=== REDRAFT PROMPTS — Claude: fix the flagged claim, save {company: {tier: {...}}} to drafts.json ===")
            for p, tier, draft in needs_redraft:
                print(f"\n----- {p.company} [{tier}] (flagged: {draft.qa_flag}) -----")
                print(build_redraft_prompt(voice_guide, p, tier, draft))
            raise CheckpointPending(
                file="drafts.json",
                action="redraft flagged emails (qa fact-check failed)",
                resume=f"python -m gtm.run redraft {run} drafts.json",
            )
```

Replace `cmd_redraft`:

```python
def cmd_redraft(run: str, drafts_json: str) -> None:
    """Single retry after a qa_check failure (cmd_draft's checkpoint): merges the
    fixed drafts, re-checks only the previously-flagged (prospect, tier) pairs,
    and finalizes each qa_flag to "passed" or the (final) failure text — no
    further checkpoint, so this never loops more than once."""
    with _track_stage(run, "redraft"):
        prospects = load_state(run_dir(run))
        merge_drafts(prospects, json.loads(Path(drafts_json).read_text()))
        save_state(prospects, run_dir(run))

        costlog = run_costlog(run)
        n, still_flagged = 0, 0
        for p in prospects:
            for tier, draft in p.drafts_by_tier.items():
                if not draft.initial_subject or draft.qa_flag in ("", "passed"):
                    continue
                n += 1
                try:
                    flag = qa_check(p, draft, costlog=costlog)
                    draft.qa_flag = flag or "passed"
                    if flag:
                        still_flagged += 1
                except Exception as e:
                    _log_error(ERROR_LOG, p.company, "qa", e)
        save_state(prospects, run_dir(run))
        print(f"{n} redrafted, {still_flagged} still flagged after retry")
        _print_cost_summary(run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_run.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add gtm/run.py tests/test_run.py
git commit -m "$(cat <<'EOF'
feat: per-persona-tier draft/redraft/QA round-trip

cmd_segment prints one draft prompt per distinct tier present at a
company (not just the top contact's); merge_drafts/cmd_draft/cmd_redraft
operate on Prospect.drafts_by_tier. merge_drafts updates an existing
tier's DraftSet content in place (never replaces the object) so a
redraft's re-merge doesn't reset the qa_flag cmd_redraft's skip-logic
depends on — see the new merge_drafts regression test.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `gtm/output.py` — `build_contact_rows` picks the tier-matching draft

**Files:**
- Modify: `gtm/output.py:1-114` (import line + `build_contact_rows`)
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `gtm.persona.classify_persona(title: str) -> str` (existing), `gtm.schema.DraftSet`
  (Task 4).
- Produces: `build_contact_rows(prospect: Prospect) -> list[dict]` — unchanged signature and
  return shape (`CONTACT_COLUMNS` keys), but `draft_initial_subject`/`draft_initial_body`/
  `draft_followup_subject`/`draft_followup_body`/`qa_flag` now vary per contact row based on
  that contact's own classified tier, not a single shared draft.

- [ ] **Step 1: Write the failing tests**

In `tests/test_output.py`, change the import line to:

```python
from gtm.schema import DraftSet, SHEET_COLUMNS, Prospect
```

Replace the `MULTI` fixture:

```python
MULTI = Prospect(
    company="Teal Drones",
    website="https://tealdrones.com",
    source="serper",
    date_processed="2026-07-21",
    status="priority",
    contact_name="Blake Resnick; Manoj Mohan; Steven Butler",
    contact_title="CEO; VP Engineering; Field Technician",
    contact_linkedin=(
        "https://linkedin.com/in/blake; "
        "https://linkedin.com/in/manoj; "
        "https://linkedin.com/in/steven"
    ),
    contact_emails="blake@tealdrones.com (verified); manoj@tealdrones.com (risky); -",
    outreach_angle="Teal's SRR win shows momentum in defense — AeroVault's NDAA case fits their next RFP cycle.",
    drafts_by_tier={
        # CEO + VP Engineering both classify c-suite (gtm/persona.py); Field
        # Technician classifies ic — two distinct draft sets, not a shared one.
        "c-suite": DraftSet(
            initial_subject="Case built for the Teal 2?",
            initial_body="{FIRST_NAME} — saw Teal's SRR win.",
            followup_subject="Following up",
            followup_body="Just circling back.",
            qa_flag="passed",
        ),
        "ic": DraftSet(
            initial_subject="Field kit for the Teal 2?",
            initial_body="{FIRST_NAME} — Teal's SRR win means more units in the field.",
            followup_subject="Quick follow-up",
            followup_body="Still curious what you use today.",
            qa_flag="passed",
        ),
    },
)
```

Replace `test_build_contact_rows_drafts_repeat_on_every_contact_row` with:

```python
def test_build_contact_rows_picks_draft_matching_each_contacts_persona_tier():
    # c-suite (Blake: CEO, Manoj: VP Engineering) gets the c-suite draft;
    # ic (Steven: Field Technician) gets its own distinct draft — not the same
    # email for every contact, per the persona-tiered drafts design.
    rows = build_contact_rows(MULTI)
    assert rows[0]["draft_initial_subject"] == "Case built for the Teal 2?"  # Blake, CEO -> c-suite
    assert rows[1]["draft_initial_subject"] == "Case built for the Teal 2?"  # Manoj, VP Eng -> c-suite
    assert rows[2]["draft_initial_subject"] == "Field kit for the Teal 2?"   # Steven, Field Tech -> ic
    assert rows[0]["qa_flag"] == "passed"
    assert rows[2]["qa_flag"] == "passed"


def test_build_contact_rows_falls_back_to_unknown_tier_draft_when_contacts_tier_has_no_draft():
    p = MULTI.model_copy(update={
        "drafts_by_tier": {"unknown": DraftSet(initial_subject="Generic subject", initial_body="Hi {FIRST_NAME}.")},
    })
    rows = build_contact_rows(p)
    # none of CEO/VP Engineering/Field Technician classify as "unknown", but no
    # tier-specific draft exists for them either — falls back to "unknown"
    assert all(r["draft_initial_subject"] == "Generic subject" for r in rows)


def test_build_contact_rows_blank_draft_when_no_matching_or_unknown_tier():
    p = MULTI.model_copy(update={"drafts_by_tier": {}})
    rows = build_contact_rows(p)
    assert all(r["draft_initial_subject"] == "" for r in rows)
    assert all(r["qa_flag"] == "" for r in rows)
```

Replace `test_build_contact_rows_merges_first_name_per_row`:

```python
def test_build_contact_rows_merges_first_name_per_row():
    # 2026-07-21 (user): {FIRST_NAME} must never ship literal — merge each
    # contact's own first name into their (tier-matched) draft body.
    rows = build_contact_rows(MULTI)
    assert rows[0]["draft_initial_body"] == "Blake — saw Teal's SRR win."
    assert rows[1]["draft_initial_body"] == "Manoj — saw Teal's SRR win."
    assert rows[2]["draft_initial_body"] == "Steven — Teal's SRR win means more units in the field."
    for r in rows:
        assert "{FIRST_NAME}" not in r["draft_initial_body"]
```

Replace `test_build_contact_rows_merges_company_variable`:

```python
def test_build_contact_rows_merges_company_variable():
    p = MULTI.model_copy(update={
        "drafts_by_tier": {
            **MULTI.drafts_by_tier,
            "c-suite": MULTI.drafts_by_tier["c-suite"].model_copy(
                update={"initial_body": "Hi {FIRST_NAME}, {COMPANY} ships tough."}
            ),
        }
    })
    rows = build_contact_rows(p)
    assert rows[0]["draft_initial_body"] == "Hi Blake, Teal Drones ships tough."
```

Replace `test_build_contact_rows_single_contact_carries_company_meta`:

```python
def test_build_contact_rows_single_contact_carries_company_meta():
    p = Prospect(
        company="X", website="https://x.com",
        date_processed="2026-07-21", status="priority",
        contact_name="Jane Doe", contact_title="VP Ops",
        contact_linkedin="https://linkedin.com/in/jane",
        contact_emails="jane@x.com (verified)",
        outreach_angle="angle text",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="Subject A")},
    )
    rows = build_contact_rows(p)
    assert len(rows) == 1
    assert rows[0]["contact_title"] == "VP Ops"
    assert rows[0]["outreach_angle"] == "angle text"
    assert rows[0]["draft_initial_subject"] == "Subject A"
    assert rows[0]["date_processed"] == "2026-07-21"
```

Leave every other test in `tests/test_output.py` unchanged — `TEAL`, the write/push tests,
`test_build_contact_rows_keeps_all_contacts_including_email_miss`,
`test_build_contact_rows_company_level_fields_repeat_on_every_row`,
`test_build_contact_rows_blank_name_falls_back_to_there`,
`test_build_contact_rows_trims_long_outreach_angle`,
`test_build_contact_rows_zero_contacts_returns_empty_list`, and the CSV/sheet-push tests
that use `MULTI` don't reference the old flat draft fields and keep working unmodified
(the new `MULTI` still has 3 contacts).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_output.py -v`
Expected: FAIL — `TypeError`/`ValidationError` constructing `MULTI` (`Prospect` has no
`draft_initial_subject` field anymore) until the fixture change lands, then assertion
failures against `build_contact_rows`'s current (pre-Task-9) behavior.

- [ ] **Step 3: Edit gtm/output.py**

Change the schema import (currently
`from gtm.schema import CONTACT_FIELD_SEP, SHEET_COLUMNS, Prospect, _trim`) to:

```python
from gtm.schema import CONTACT_FIELD_SEP, SHEET_COLUMNS, DraftSet, Prospect, _trim
```

Replace `build_contact_rows`:

```python
def build_contact_rows(prospect: Prospect) -> list[dict]:
    """Reconstructs one dict per tracked contact from the CONTACT_FIELD_SEP-joined
    parallel fields (contact_name/contact_title/contact_linkedin/contact_emails).
    Every index is kept, including email misses. Company-level fields
    (company/outreach_angle/date_processed) repeat on every row so each contact
    row is self-contained; per-contact fields (name/title/linkedin/email/
    email_status) vary by index, and so does the draft — each contact's own
    title is classified into a persona tier (gtm/persona.py::classify_persona)
    and matched against prospect.drafts_by_tier, falling back to the "unknown"
    tier's draft if that contact's classified tier has no draft of its own."""
    from gtm.persona import classify_persona

    names = prospect.contact_name.split(CONTACT_FIELD_SEP) if prospect.contact_name else []
    titles = prospect.contact_title.split(CONTACT_FIELD_SEP) if prospect.contact_title else []
    linkedins = (
        prospect.contact_linkedin.split(CONTACT_FIELD_SEP) if prospect.contact_linkedin else []
    )
    emails = prospect.contact_emails.split(CONTACT_FIELD_SEP) if prospect.contact_emails else []

    rows = []
    for i, name in enumerate(names):
        email, status = _parse_email_entry(emails[i]) if i < len(emails) else ("", "miss")
        name = name.strip()
        first = name.split()[0] if name else ""
        title = titles[i].strip() if i < len(titles) else ""
        tier = classify_persona(title)
        draft = prospect.drafts_by_tier.get(tier) or prospect.drafts_by_tier.get("unknown") or DraftSet()

        def merge(text: str) -> str:
            # {FIRST_NAME}/{COMPANY} are drafted once per company, substitute this
            # contact's own first name so no placeholder ever ships literal.
            return text.replace("{FIRST_NAME}", first or "there").replace(
                "{COMPANY}", prospect.company
            )

        rows.append({
            "company": prospect.company,
            "contact_name": name,
            "contact_title": title,
            "contact_linkedin": linkedins[i].strip() if i < len(linkedins) else "",
            "contact_email": email,
            "email_status": status,
            "outreach_angle": _trim(prospect.outreach_angle, _OUTREACH_ANGLE_MAX_CHARS),
            "draft_initial_subject": merge(draft.initial_subject),
            "draft_initial_body": merge(draft.initial_body),
            "draft_followup_subject": merge(draft.followup_subject),
            "draft_followup_body": merge(draft.followup_body),
            "qa_flag": draft.qa_flag,
            "date_processed": prospect.date_processed,
        })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_output.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add gtm/output.py tests/test_output.py
git commit -m "$(cat <<'EOF'
feat: build_contact_rows picks each contact's own persona-tier draft

A CFO and a director at the same company now get their own drafted
email on the Contacts tab/CSV instead of one shared draft — closes
the loop on the persona-tiered drafts design. Falls back to the
"unknown" tier's draft when a contact's classified tier has none.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `company/voice-guide.md` — category-only social proof + specificity rule

**Files:**
- Modify: `company/voice-guide.md:63-66` (Email structure step 2), and a new "Specificity"
  section inserted after "Banned phrases / openers" (currently ends at line 31, before
  "## Signature")
- Create: `tests/test_voice_guide.py`

**Interfaces:**
- Consumes: nothing (docs-only; `gtm/draft.py::build_draft_prompt` already interpolates
  `company/voice-guide.md`'s text verbatim — Task 6 already added its own
  "category-level only" wording directly in the prompt template as a belt-and-suspenders
  instruction, independent of this file).
- Produces: the voice-guide text `build_draft_prompt` embeds for Claude to follow.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_voice_guide.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_voice_guide.py -v`
Expected: FAIL — neither "category-level only" nor "Specificity" exist in the current file.

- [ ] **Step 3: Edit company/voice-guide.md**

Replace the "Email structure" section's step 2 (currently `2. **Value prop** — a use case +
social proof (a comparable, well-known customer) + the pain it removes. Example framing: "We
saw companies similar to you have {xyz}."`) with:

```markdown
2. **Value prop** — a use case + social proof + the pain it removes. AeroVault Cases is a
   demo company with no real customers: social proof must be **category-level only**
   ("other defense sUAS makers ship in our cases") — never a named client or logo. Also
   name a concrete mechanism or spec difference (a MIL-STD-810H drop-test spec, a cited
   competitor weakness, an exact dimension) — never a bare comparative like "protects
   better" with nothing backing it. Example framing: "Other {segment} drone makers run
   into {xyz} — our {mechanism} fixes it."
```

Insert this new section immediately after the "Banned phrases / openers" section (before
"## Signature"):

```markdown
## Specificity (no vague value-prop claims)
Every value-prop claim must name a concrete mechanism or spec difference — a MIL-STD-810H
drop-test rating, an exact dimension, a cited competitor weakness (`competitor_weaknesses`,
from `gtm/displace.py`'s research step). Never a bare comparative with nothing behind it:
banned — "protects better", "keeps your gear safe", "built for reliability" — unless
immediately followed by the specific fact that backs it.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_voice_guide.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add company/voice-guide.md tests/test_voice_guide.py
git commit -m "$(cat <<'EOF'
feat: voice guide bans vague value-prop claims, forces category-only proof

Directly addresses the user's complaint about "Custom-foam cases protect
each unit better than the stock Pelican 1520" — vague claims now require
a concrete mechanism/spec backing them. Social proof can no longer imply
a real customer AeroVault (a fictional demo company) doesn't have.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Full-suite regression + rollout

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: PASS, all tests green (no `xfail`/`skip` newly introduced by this plan). If
anything outside the files this plan touched fails, stop and investigate before proceeding —
it means an assumption in this plan (e.g. about which tests reference the removed flat draft
fields) missed a call site.

- [ ] **Step 2: Grep for any leftover references to the removed API**

Run:
```bash
grep -rn "draft_initial_subject\b" gtm/ tests/ | grep -v "drafts_by_tier\|DraftSet\|initial_subject"
grep -rn "p\.qa_flag\b" gtm/ tests/
```
Expected: no output from either (both are dead code if anything remains — the flat fields
were removed from `Prospect` in Task 4).

- [ ] **Step 3: Rollout note (manual, not part of this commit)**

After this plan's tasks are all merged, re-run the live pipeline for `us-drone-3`:

```bash
python -m gtm.run enrich us-drone-3
# ... answer signal + displacement prompts, save signals.json ...
python -m gtm.run signals us-drone-3 signals.json
python -m gtm.run segment us-drone-3
# ... answer one draft prompt per (company, tier), save drafts.json ...
python -m gtm.run draft us-drone-3 drafts.json
python -m gtm.run output us-drone-3
```

Fit scores will shift for any prospect with a named competitor case (Part 1's flip is
expected to change numbers, not a bug). Clear the `Companies`/`Contacts` Sheet tabs by hand
before `output` — `push_to_sheet`/`push_contacts_to_sheet` are still append-only with no
dedupe-by-company (a known gap carried over from the prior session's handoff, out of scope
for this plan).

No commit for this task — it's a verification checkpoint, not a code change.

---
