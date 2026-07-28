# Fabricated-Pain Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the draft stage asserting a pain the prospect has no evidence for, by never
requesting the pain block when no pain evidence exists and flagging one if it appears anyway.

**Architecture:** Prevention plus detection, mirroring the existing `check_tier_distinctness`
fix. A new `has_pain_source` predicate defines pain evidence as `community_signals` or
`competitor_weaknesses` only. When it is false, `build_draft_prompt` drops the four-block
shape to three and emits an explicit prohibition; `check_pain_grounding` — a free,
no-model guard armed only in that case — backstops it in `cmd_draft` and `cmd_redraft`.
Separately, `qa_check` is given the three evidence fields it was never passed.

**Tech Stack:** Python 3, Pydantic (`gtm/schema.py`), pytest, OpenAI SDK (`gpt-4.1-mini`).

**Spec:** `docs/superpowers/specs/2026-07-28-fabricated-pain-gate-design.md`

## Global Constraints

- Pain sources are `community_signals` and `competitor_weaknesses` **only**. `case_evidence`
  and `buying_signals` never license a pain claim.
- `qa_check`'s system-prompt flag scope stays *stat / contract / certification / event*.
  Do NOT widen it. That judgment stays off `gpt-4.1-mini` by explicit decision.
- `is_thin_signal`'s 2-of-3 threshold does not change.
- Guards return `""` when clean, else flag text — same contract as `check_reference_customer`.
- Free deterministic guards run before, and short-circuit, the paid `qa_check`.
- TDD: failing test first, then minimal implementation, then passing test, then commit.
- Never commit without a fresh explicit go-ahead from the user. Stop and ask at each
  commit step.
- Full suite baseline is **397 passed**. It must never go down.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `gtm/draft.py` | Prompt construction, deterministic guards, QA call | Modify — add `has_pain_source`, `_NO_PAIN_SHAPE`, `_NO_PAIN_RULE`, `_CONSEQUENCE_WORDS`, `_ATTRIBUTION_PATTERNS`, `check_pain_grounding`; edit `build_draft_prompt` and `qa_check` |
| `gtm/run.py` | Stage orchestration | Modify — import and wire `check_pain_grounding` into the two guard chains |
| `company/voice-guide.md` | Interpolated verbatim into every draft prompt | Modify — Block 3 grounding rule, length table |
| `tests/test_draft.py` | Unit tests for the above | Modify |
| `tests/test_run.py` | Wiring tests | Modify |

---

### Task 1: `has_pain_source` predicate

**Files:**
- Modify: `gtm/draft.py` (insert after `is_thin_signal`, ends line 160)
- Test: `tests/test_draft.py`

**Interfaces:**
- Consumes: `Prospect` from `gtm.schema`.
- Produces: `has_pain_source(p: Prospect) -> bool`. Tasks 2 and 3 both call it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_draft.py` after `test_is_thin_signal_false_when_any_two_of_three_present`
(ends line 113). Add `has_pain_source` to the `from gtm.draft import (...)` block at line 3,
keeping the list alphabetical (it goes after `check_tier_distinctness`).

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_draft.py -k has_pain_source -v`
Expected: FAIL at import — `ImportError: cannot import name 'has_pain_source' from 'gtm.draft'`

- [ ] **Step 3: Write minimal implementation**

Insert in `gtm/draft.py` immediately after `is_thin_signal` (after line 160):

```python
def has_pain_source(p: Prospect) -> bool:
    """Whether any researched evidence of a pain exists for this prospect.

    The voice guide's Block 3 asserts a consequence the prospect feels; only these two
    fields record one. case_evidence describes what they ship in today and buying_signals
    describe a trigger event — neither is evidence that anything hurts, and treating them
    as such is what let cold-0727/Arcsky ship "a cracked arm or a gimbal out of true"
    with nothing behind it (2026-07-28).
    """
    return bool(p.community_signals or p.competitor_weaknesses)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_draft.py -k has_pain_source -v`
Expected: 3 passed

- [ ] **Step 5: Full suite**

Run: `python -m pytest -q`
Expected: 400 passed

- [ ] **Step 6: Commit** — ask the user for go-ahead first

```bash
git add gtm/draft.py tests/test_draft.py
git commit -m "feat(draft): add has_pain_source, the Block 3 grounding predicate"
```

---

### Task 2: Drop the pain block when no pain source exists

**Files:**
- Modify: `gtm/draft.py` — add constants near `_TIER_SHAPE` (lines 43-55), rewrite the
  `else` branch of `build_draft_prompt` (lines 219-259)
- Test: `tests/test_draft.py`

**Interfaces:**
- Consumes: `has_pain_source` from Task 1.
- Produces: no new public names. `build_draft_prompt`'s signature is unchanged; only the
  emitted prompt text changes.

**Behaviour being built** — shape and prohibition key off different conditions:

| `p.status` | pain source | shape | prohibition line |
|---|---|---|---|
| `priority` or unset | yes | `_TIER_SHAPE`/`_DEFAULT_SHAPE`, 4 blocks | no |
| `priority` or unset | no | `_NO_PAIN_SHAPE`, 3 blocks | **yes** |
| `keep` | yes | `_TIER_SHAPE["keep"]`, 3 blocks | no |
| `keep` | no | `_TIER_SHAPE["keep"]`, 3 blocks (unchanged) | **yes** |

The `keep` row matters: that shape describes itself as folding the pain into the value line,
so without the prohibition a no-pain `keep` prospect fabricates in Block 2 instead.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_draft.py` after the Task 1 tests:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_draft.py -k "no_pain_source or pain_block or keep_tier_keeps" -v`
Expected: FAIL — `assert '~250-400 characters' in prompt` and `assert 'NO RESEARCHED PAIN' in prompt`

- [ ] **Step 3: Add the two constants**

Insert in `gtm/draft.py` immediately after `_DEFAULT_SHAPE` (line 55):

```python
# 2026-07-28: a priority prospect with no researched pain still gets an email — it just
# loses Block 3. Requesting a pain block with no pain evidence is what forces the model
# to invent one (cold-0727/Arcsky). Tier 2 is already 3-block and keeps its own shape.
_NO_PAIN_SHAPE = (
    "Tier 1 (priority), no researched pain",
    "three blocks — opener · what we build · close",
    "~250-400 characters",
)

_NO_PAIN_RULE = (
    "\n- NO RESEARCHED PAIN: community_signals and competitor_weaknesses are both empty for "
    "this prospect. Do NOT assert any consequence they experience (damage, cracked or bent "
    "airframes, warranty claims, downtime, lost jobs), and do NOT attribute a claim to "
    "operators, buyers, customers, forums, or groups — nothing in the evidence supports one. "
    "The trigger and the value line carry this email."
)
```

- [ ] **Step 4: Rewrite the `else` branch**

In `build_draft_prompt`, replace line 220 (`band, blocks, length = _TIER_SHAPE.get(...)`) with:

```python
        pain = has_pain_source(p)
        if pain:
            band, blocks, length = _TIER_SHAPE.get(p.status, _DEFAULT_SHAPE)
        elif p.status == "keep":
            band, blocks, length = _TIER_SHAPE["keep"]
        else:
            band, blocks, length = _NO_PAIN_SHAPE

        pain_block, close_num = "", 3
        if pain:
            close_num = 4
            pain_block = (
                f"3. **The pain** — the consequence THIS tier ('{tier}') feels, per the voice "
                f'guide\'s "Persona\n   tailoring". Ground it in community_signals / '
                f"competitor_weaknesses. Without this\n   block the email is just a product "
                f"description.\n"
            )
        no_pain_rule = "" if pain else _NO_PAIN_RULE
```

- [ ] **Step 5: Make the f-string conditional**

Still inside the `else` branch, in the `draft_section` f-string: delete the literal blocks 3
and 4 (currently lines 233-238, from `3. **The pain** —` through `nothing after.`) and put in
their place:

```
{pain_block}{close_num}. **Close** — ONE low-pressure closed-ended ask, negative-CTA preferred ("Would it be a bad
   idea for us to grab 15 minutes...?"). A single genuine question may precede it. Never
   stack asks. Then {{{{sender_name}}}} on its own line, nothing after.
```

Then change the final line of that same f-string from `- No banned phrases (see voice guide).{sibling_block}"""`
to:

```
- No banned phrases (see voice guide).{sibling_block}{no_pain_rule}"""
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_draft.py -v`
Expected: all pass, including the pre-existing
`test_build_draft_prompt_demands_the_pain_block_and_bans_the_one_liner_skeleton` and
`test_build_draft_prompt_length_follows_fit_tier` — both use `_rich_prospect()`, which carries
`competitor_weaknesses`, so they stay on the four-block path.

- [ ] **Step 7: Full suite**

Run: `python -m pytest -q`
Expected: 404 passed

- [ ] **Step 8: Commit** — ask the user for go-ahead first

```bash
git add gtm/draft.py tests/test_draft.py
git commit -m "feat(draft): drop the pain block when no pain evidence exists"
```

---

### Task 3: `check_pain_grounding` guard

**Files:**
- Modify: `gtm/draft.py` (insert after `has_pain_source` from Task 1)
- Test: `tests/test_draft.py`

**Interfaces:**
- Consumes: `has_pain_source` from Task 1; `re` (already imported at line 11).
- Produces: `check_pain_grounding(p: Prospect, draft: DraftSet) -> str`. Task 4 wires it.
  Note the signature takes no `tier` — unlike `check_tier_distinctness`, it needs no
  cross-tier context.

**Word lists are already validated.** Both were run against every stored
`data/runs/*/prospects.json` on 2026-07-28. Result: both Arcsky tiers flag, nothing else does.
Two findings that must survive into the implementation:

1. **The attribution list is load-bearing.** Arcsky's `c-suite` draft contains *no* consequence
   word — it fabricates purely by attribution (*"buyers … in the mapping groups are asking"*).
   Consequence words alone would miss it entirely.
2. **The `has_pain_source` disarm is load-bearing.** Four of the seven drafts that *do* have
   pain evidence contain "damage"/"damaged" legitimately. An always-on guard would produce
   four false positives out of seven. Never scan without checking the disarm first.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_draft.py`. Add `check_pain_grounding` to the import block at line 3
(alphabetically, after `check_reference_customer`). Bodies are copied verbatim from live
`data/runs/cold-0727/prospects.json`.

```python
# --- fabricated-pain guard ------------------------------------------------------
# Both bodies below are the real cold-0727/Arcsky drafts, which shipped qa_flag="passed".

_ARCSKY_CONSEQUENCE_BODY = (
    "{{first_name}},\n\n"
    "Saw {{company_name}}'s {{trigger_event}} — congrats.\n\n"
    "We build cases with foam cut to one airframe. IP67 and MIL-STD-810H rated.\n\n"
    "{{airframe_name}} travels in a tough portable box today. That protects the outside of "
    "the load, but it lets the aircraft move against its own accessories on every drive to a "
    "site — which surfaces later as a cracked arm or a gimbal out of true.\n\n"
    "Would it be a bad idea to spend 15 minutes on it?\n\n{{sender_name}}"
)

_ARCSKY_ATTRIBUTION_BODY = (
    "{{first_name}},\n\n"
    "Saw {{company_name}}'s {{trigger_event}} — congrats.\n\n"
    "We cut foam to one airframe, IP67 and MIL-STD-810H rated, US-made.\n\n"
    "A launch is the one moment the transport standard is still open. Your site says the "
    "aircraft packs into one tough portable box today, and the surveying buyers comparing "
    "NDAA packages in the mapping groups are asking what comes in the box before they "
    "commit.\n\n"
    "Would it be a bad idea to spend 15 minutes on it?\n\n{{sender_name}}"
)


def _no_pain_prospect(**overrides):
    defaults = dict(
        company="Arcsky", website="https://arcsky.com",
        buying_signals=["Launched the Xplorer, a new compact rugged UAV"],
        case_evidence="packs nicely into one tough portable box",
        community_signals=[], competitor_weaknesses=[],
    )
    defaults.update(overrides)
    return Prospect(**defaults)


def test_check_pain_grounding_flags_an_asserted_consequence():
    draft = DraftSet(
        initial_subject="transport for the new Xplorer",
        initial_body=_ARCSKY_CONSEQUENCE_BODY,
    )
    flag = check_pain_grounding(_no_pain_prospect(), draft)
    assert "cracked" in flag
    assert "Arcsky" in flag


def test_check_pain_grounding_flags_a_fabricated_attribution():
    # This body contains no consequence word at all — attribution is the only signal.
    draft = DraftSet(
        initial_subject="the Xplorer's case is still unspecified",
        initial_body=_ARCSKY_ATTRIBUTION_BODY,
    )
    flag = check_pain_grounding(_no_pain_prospect(), draft)
    assert flag != ""
    assert "third parties" in flag


def test_check_pain_grounding_passes_a_clean_no_pain_body():
    draft = DraftSet(
        initial_subject="transport for the new Xplorer",
        initial_body=(
            "{{first_name}},\n\n"
            "Saw {{company_name}}'s {{trigger_event}} — congrats.\n\n"
            "We cut foam to one airframe: aircraft, controller, batteries and payload each "
            "seated in their own cavity, IP67 and MIL-STD-810H rated, US-made. "
            "{{reference_customer}} ships that way.\n\n"
            "Would it be a bad idea to spend 15 minutes on what a {{case_line}} build looks "
            "like for {{airframe_name}}?\n\n{{sender_name}}"
        ),
    )
    assert check_pain_grounding(_no_pain_prospect(), draft) == ""


def test_check_pain_grounding_is_disarmed_when_pain_evidence_exists():
    # Four of the seven stored drafts that DO have pain evidence say "damage" legitimately.
    # Without this disarm the guard is a false-positive machine.
    p = _no_pain_prospect(community_signals=["operators report arms cracking in transit"])
    draft = DraftSet(
        initial_subject="transport for the new Xplorer",
        initial_body=_ARCSKY_CONSEQUENCE_BODY,
    )
    assert check_pain_grounding(p, draft) == ""


def test_check_pain_grounding_scans_the_v2_body():
    draft = DraftSet(
        initial_subject="transport for the new Xplorer",
        initial_body="{{first_name}},\n\nClean body, no claims.\n\n{{sender_name}}",
        initial_body_alt=_ARCSKY_CONSEQUENCE_BODY,
    )
    assert check_pain_grounding(_no_pain_prospect(), draft) != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_draft.py -k pain_grounding -v`
Expected: FAIL at import — `ImportError: cannot import name 'check_pain_grounding'`

- [ ] **Step 3: Write the implementation**

Insert in `gtm/draft.py` after `has_pain_source`:

```python
# Validated 2026-07-28 against every stored data/runs/*/prospects.json: these flag both
# cold-0727/Arcsky tiers and nothing else. The attribution list is not optional — Arcsky's
# c-suite draft contains no consequence word at all and fabricates purely by attributing a
# claim ("the surveying buyers ... in the mapping groups are asking").
_CONSEQUENCE_WORDS = (
    "cracked", "crack", "snapped", "broken", "breaks", "damaged", "damage", "dented",
    "bent", "shattered", "scratched", "warranty", "rma", "downtime", "grounded",
    "out of true", "failure", "fails", "replacement cost", "insurance claim",
)
_ATTRIBUTION_PATTERNS = (
    r"operators? (say|report|complain)",
    r"buyers?[^.]{0,40}(are )?asking",
    r"customers? (say|report)",
    r"crews? (say|report)",
    r"we hear",
    r"on reddit",
    r"in the [a-z ]{0,20}(groups|forums|threads|subreddit)",
)


def check_pain_grounding(p: Prospect, draft: DraftSet) -> str:
    """Deterministic guard for the voice guide's Block 3 grounding rule: a draft may not
    assert a pain the prospect has no researched evidence for.

    qa_check cannot catch this — its flag scope is stats, contracts, certifications, and
    events, and a fabricated consequence is none of those. The failure this exists to catch
    (cold-0727/Arcsky, 2026-07-28): both tiers shipped qa_flag="passed" while
    community_signals and competitor_weaknesses were empty, one asserting "a cracked arm or
    a gimbal out of true" and the other attributing a claim to "buyers ... in the mapping
    groups". A prior hand-rewrite reworded both rather than removing them.

    Armed ONLY when no pain evidence exists, which keeps the blast radius small: four of the
    seven stored drafts that do have evidence use "damage" legitimately in the value line.
    A false positive costs one pass through the existing redraft loop.

    Returns "" when clean, else the flag text (same contract as check_reference_customer).
    """
    if has_pain_source(p):
        return ""
    body = f"{draft.initial_body}\n{draft.initial_body_alt}".lower()
    hits = sorted({w for w in _CONSEQUENCE_WORDS if w in body})
    if hits:
        return (
            f"asserts a consequence ({', '.join(hits[:3])}) with no pain evidence — "
            f"community_signals and competitor_weaknesses are both empty for {p.company}, "
            f"so nothing supports it; drop the claim"
        )
    for pat in _ATTRIBUTION_PATTERNS:
        m = re.search(pat, body)
        if m:
            return (
                f'attributes a claim to third parties ("{m.group(0)}") with no pain '
                f"evidence — community_signals is empty for {p.company}, so no operator or "
                f"buyer complaint was ever researched; drop the claim"
            )
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_draft.py -k pain_grounding -v`
Expected: 5 passed

- [ ] **Step 5: Full suite**

Run: `python -m pytest -q`
Expected: 409 passed

- [ ] **Step 6: Commit** — ask the user for go-ahead first

```bash
git add gtm/draft.py tests/test_draft.py
git commit -m "feat(draft): flag a pain claim with no evidence behind it"
```

---

### Task 4: Wire the guard into `cmd_draft` and `cmd_redraft`

**Files:**
- Modify: `gtm/run.py` — import block (lines 35-37), `cmd_draft` (lines 435-439),
  `cmd_redraft` (lines 487-491)
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `check_pain_grounding(p, draft) -> str` from Task 3.
- Produces: nothing new. Behaviour change only.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_run.py`. Both follow the fixture style of the existing tests at lines 666
and 758. `_FABRICATED_BODY` below is the live cold-0727/Arcsky text.

```python
_FABRICATED_BODY = (
    "{{first_name}},\n\nSaw {{company_name}}'s launch — congrats.\n\n"
    "{{airframe_name}} travels in a tough portable box today — which surfaces later as a "
    "cracked arm or a gimbal out of true.\n\n{{sender_name}}"
)


def test_cmd_draft_flags_fabricated_pain_before_paying_for_qa(monkeypatch, tmp_path, capsys):
    # The guard is free and qa_check is not, so a fabricated-pain draft must never reach the
    # paid call. cold-0727/Arcsky shipped qa_flag="passed" because nothing checked this.
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Arcsky", website="https://arcsky.com", status="priority",
        buying_signals=["Launched the Xplorer"],
        case_evidence="packs nicely into one tough portable box",
        community_signals=[], competitor_weaknesses=[],
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Arcsky": {
            "c-suite": {
                "draft_initial": {
                    "v1": {"subject": "transport for the new Xplorer", "body": _FABRICATED_BODY},
                    "v2": {"subject": "s2", "body": "b2"},
                },
            }
        }
    }))

    called = []
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: called.append(1) or "")

    with pytest.raises(CheckpointPending):
        cmd_draft("arcsky-pain-1", str(drafts_path))

    saved = load_state(tmp_path)
    assert "asserts a consequence" in saved[0].drafts_by_tier["c-suite"].qa_flag
    assert called == []  # short-circuited before the paid qa_check

    assert "REDRAFT" in capsys.readouterr().out


def test_cmd_redraft_rechecks_pain_grounding(monkeypatch, tmp_path):
    # Same guard chain in the retry path — a redraft that reintroduces the claim is caught.
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Arcsky", website="https://arcsky.com", status="priority",
        buying_signals=["Launched the Xplorer"],
        case_evidence="packs nicely into one tough portable box",
        community_signals=[], competitor_weaknesses=[],
        drafts_by_tier={"c-suite": DraftSet(
            initial_subject="old subject", qa_flag="asserts a consequence (cracked)",
        )},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Arcsky": {
            "c-suite": {
                "draft_initial": {
                    "v1": {"subject": "transport for the new Xplorer", "body": _FABRICATED_BODY},
                    "v2": {"subject": "s2", "body": "b2"},
                },
            }
        }
    }))
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "")

    cmd_redraft("arcsky-pain-2", str(drafts_path))  # must NOT raise

    saved = load_state(tmp_path)
    assert "asserts a consequence" in saved[0].drafts_by_tier["c-suite"].qa_flag
```

Confirm `DraftSet` is in `tests/test_run.py`'s imports (it is used at line 764); add it if the
import block does not already carry it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run.py -k "fabricated_pain or pain_grounding" -v`
Expected: FAIL — `assert 'asserts a consequence' in flag`, actual flag is `"passed"`

- [ ] **Step 3: Add the import**

In `gtm/run.py`, add `check_pain_grounding,` to the `from gtm.draft import (...)` block so
lines 35-38 read:

```python
    check_pain_grounding,
    check_reference_customer,
    check_tier_distinctness,
    qa_check,
```

- [ ] **Step 4: Wire both guard chains**

In `cmd_draft`, replace lines 435-439 with:

```python
                    flag = (
                        check_reference_customer(p, draft, others)
                        or check_tier_distinctness(p, tier, draft)
                        or check_pain_grounding(p, draft)
                        or qa_check(p, draft, costlog=costlog)
                    )
```

Apply the identical replacement in `cmd_redraft` at lines 487-491.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_run.py -k "fabricated_pain or pain_grounding" -v`
Expected: 2 passed

- [ ] **Step 6: Full suite**

Run: `python -m pytest -q`
Expected: 411 passed

- [ ] **Step 7: Commit** — ask the user for go-ahead first

```bash
git add gtm/run.py tests/test_run.py
git commit -m "feat(run): run the pain-grounding guard before the paid qa_check"
```

---

### Task 5: Give `qa_check` the evidence it was never passed

**Files:**
- Modify: `gtm/draft.py` lines 317-319
- Test: `tests/test_draft.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new. `qa_check`'s signature and return type are unchanged.

This is a plain bug fix, independent of the gate: the fact-checker was told to verify claims
against evidence it never received. **Do not touch the system prompt** — see Global Constraints.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_draft.py` near the other `qa_check` tests. `_FakeClient` already records
`last_messages` (line 218), so no new fixture is needed.

```python
def test_qa_check_passes_the_grounding_fields_to_the_model():
    # The fact-checker was asked to verify claims against evidence it never received:
    # community_signals / competitor_weaknesses / case_evidence were absent from the
    # evidence block entirely, so no pain claim was ever checkable (2026-07-28).
    p = Prospect(
        company="Arcsky", website="https://arcsky.com",
        buying_signals=["Launched the Xplorer"],
        community_signals=["operators report arms cracking"],
        competitor_weaknesses=["too heavy for field carry"],
        case_evidence="packs nicely into one tough portable box",
    )
    client = _FakeClient(QAResult(flag=""))
    qa_check(p, _draft(), client=client)
    evidence = client.last_messages[1]["content"]
    assert "operators report arms cracking" in evidence
    assert "too heavy for field carry" in evidence
    assert "packs nicely into one tough portable box" in evidence


def test_qa_check_system_prompt_scope_is_not_widened():
    # Deliberate: "is this pain fabricated" is a judgment call kept off gpt-4.1-mini —
    # the same pattern leaked twice this month. check_pain_grounding owns it instead.
    client = _FakeClient(QAResult(flag=""))
    qa_check(_prospect(), _draft(), client=client)
    system = client.last_messages[0]["content"]
    assert "stat, contract, certification, or event" in system
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_draft.py -k "grounding_fields or scope_is_not_widened" -v`
Expected: `test_qa_check_passes_the_grounding_fields_to_the_model` FAILS
(`assert 'operators report arms cracking' in evidence`);
`test_qa_check_system_prompt_scope_is_not_widened` PASSES already — it is a regression lock,
not a red test.

- [ ] **Step 3: Write the implementation**

In `gtm/draft.py`, replace lines 317-319 with:

```python
    evidence = (
        f"buying_signals: {p.buying_signals}\nkey_news: {p.key_news}\n"
        f"fit_reason: {p.fit_reason}\ncommunity_signals: {p.community_signals}\n"
        f"competitor_weaknesses: {p.competitor_weaknesses}\ncase_evidence: {p.case_evidence}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_draft.py -k "grounding_fields or scope_is_not_widened" -v`
Expected: 2 passed

- [ ] **Step 5: Full suite**

Run: `python -m pytest -q`
Expected: 413 passed

- [ ] **Step 6: Commit** — ask the user for go-ahead first

```bash
git add gtm/draft.py tests/test_draft.py
git commit -m "fix(draft): pass the grounding fields to qa_check"
```

---

### Task 6: Voice-guide edits

**Files:**
- Modify: `company/voice-guide.md` — length table (lines 36-38), Block 3 paragraph (lines 52-56)
- Test: `tests/test_voice_guide.py`

**Interfaces:** none — but note the guide is interpolated **verbatim** into every draft prompt
at `gtm/draft.py:266`. A stale guide actively contradicts Task 2's instruction inside the same
prompt, which is why this is code, not documentation.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_voice_guide.py`, following the existing single-assertion style:

```python
def test_voice_guide_grounds_the_pain_block_in_pain_sources_only():
    text = VOICE_GUIDE.read_text()
    block3 = text.split("**Block 3")[1].split("**Block 4")[0]
    assert "community_signals" in block3
    assert "competitor_weaknesses" in block3
    # case_evidence is what they ship in today, not evidence anything hurts — listing it
    # here is what licensed the cold-0727/Arcsky fabrication.
    assert "case_evidence" not in block3
    assert "omit Block 3" in block3
```

`VOICE_GUIDE` is already defined at `tests/test_voice_guide.py:6` as
`Path("company/voice-guide.md")` — no new import is needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_voice_guide.py -k pain_sources_only -v`
Expected: FAIL — `assert 'case_evidence' not in block3`

- [ ] **Step 3: Edit the Block 3 paragraph**

In `company/voice-guide.md`, replace the sentence
*"Ground it in `community_signals` / `competitor_weaknesses` / `case_evidence` where real
evidence exists."* with:

```markdown
Ground it in `community_signals` or `competitor_weaknesses` — those are the only two fields
that record an actual complaint. `case_evidence` (what they ship in today) and
`buying_signals` (a trigger event) are not evidence that anything hurts, and never license a
pain claim. When neither pain source exists, omit Block 3 entirely: never assert a
consequence they experience, and never attribute a claim to operators, buyers, customers,
forums, or groups.
```

- [ ] **Step 4: Edit the length table**

Add a row to the length-by-tier table (after the Tier 1 row, line 37):

```markdown
| Tier 1, no pain source | `priority` | 3 (trigger · what we build · close) — Block 3 omitted, nothing researched to ground it | ~250–400 characters |
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_voice_guide.py -v`
Expected: all pass — the two pre-existing tests assert only social-proof and specificity
strings, which these edits leave untouched.

- [ ] **Step 6: Full suite**

Run: `python -m pytest -q`
Expected: 414 passed

- [ ] **Step 7: Commit** — ask the user for go-ahead first

```bash
git add company/voice-guide.md tests/test_voice_guide.py
git commit -m "docs(voice): ground Block 3 in pain sources, omit it when none exist"
```

---

### Task 7: Live verification

**Files:**
- Create: `scratchpad/verify_pain_gate.py` (throwaway, not committed)
- Touches: `data/runs/cold-0727/prospects.json` (gitignored, local only)

**Interfaces:** consumes everything from Tasks 1-6.

Project norm: never trust a fix until it is re-run against real stored state, not just unit
tests in isolation.

- [ ] **Step 1: Static sweep over all stored runs — no API calls**

Write to the scratchpad directory and run:

```python
import json, glob
from gtm.draft import check_pain_grounding
from gtm.schema import Prospect

for f in sorted(glob.glob("data/runs/*/prospects.json")):
    for raw in json.load(open(f)):
        p = Prospect(**raw)
        for tier, draft in p.drafts_by_tier.items():
            if not draft.initial_subject:
                continue
            flag = check_pain_grounding(p, draft)
            print(f"{'FLAG' if flag else 'ok  '} {f.split('/')[2]:12} {p.company[:22]:22} {tier:9} {flag[:70]}")
```

Expected — exactly two flags, seven clean:

| Run | Company | Tiers | Expected |
|---|---|---|---|
| cold-0727 | Arcsky | unknown, c-suite | **both FLAG** |
| us-drone-5 | Inspired Flight Technologies | c-suite, director, manager | ok |
| us-drone-5 | EagleNXT | c-suite | ok |
| us-drone-5 | Anzu Robotics | unknown | ok |
| us-drone-7 | Teal Drones | manager, director | ok |

Any other result means the word lists need tuning — adjust `_CONSEQUENCE_WORDS` /
`_ATTRIBUTION_PATTERNS` until this table holds exactly, and re-run Task 3's unit tests.

- [ ] **Step 2: End-to-end redraft of Arcsky**

Approved by the user on 2026-07-28. Mutates `data/runs/cold-0727/prospects.json` and costs one
`qa_check` call per tier. **No external push** — Sheet and HubSpot are the separate `output`
stage and must not be run.

```bash
python -m gtm.run draft cold-0727 data/runs/cold-0727/drafts.json
```

The stage prints redraft prompts for both flagged Arcsky tiers. Answer them per the new
three-block prompt, save to `data/runs/cold-0727/drafts.json`, then:

```bash
python -m gtm.run redraft cold-0727 data/runs/cold-0727/drafts.json
```

- [ ] **Step 3: Confirm the result**

Re-run Step 1's sweep. Expected: **zero flags across all runs**. Then confirm both Arcsky
tiers carry `qa_flag == "passed"` and that neither body contains an asserted consequence or a
third-party attribution — read them, do not just trust the flag.

This proves prevention, not just detection: the new drafts came from the three-block prompt
and should never have contained a pain claim to begin with.

- [ ] **Step 4: Final full suite**

Run: `python -m pytest -q`
Expected: 414 passed

- [ ] **Step 5: Report** — no commit; `data/` is gitignored and the scratchpad script is
throwaway. Report the before/after sweep output and both rewritten bodies to the user.

---

## Notes for the implementer

- `_rich_prospect` in `tests/test_draft.py` (line 86) carries `competitor_weaknesses` by
  default, so every pre-existing test stays on the four-block path. If a test you did not
  touch starts failing on `~450-700 characters`, you changed shape selection wrongly.
- Guard order in the chain is deliberate: reference-customer, then tier-distinctness, then
  pain-grounding, then the paid `qa_check`. All three free guards short-circuit the paid call.
- Out of scope, do not fold in: Arcsky's stale `unknown`-tier draft (it is a live fixture for
  Task 7), widening `qa_check`'s flag scope, and `is_thin_signal`'s threshold.
