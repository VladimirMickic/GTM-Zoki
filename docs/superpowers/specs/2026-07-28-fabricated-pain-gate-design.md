# Fabricated-pain gate for the draft stage

Date: 2026-07-28
Stage: 6 (draft) — `gtm/draft.py`, `gtm/run.py`, `company/voice-guide.md`

## Problem

The voice guide's Block 3 ("the pain") is the paragraph that makes a cold email land. Nothing
enforces that it is grounded in evidence. A prospect can pass every existing gate, be asked
for a four-block email, and have no pain evidence to write the pain block from — at which
point inventing one is the only way to satisfy the prompt.

Three defects combine to produce this:

1. **`qa_check` cannot see the grounding fields.** `gtm/draft.py` builds its evidence block
   from `buying_signals`, `key_news`, and `fit_reason` only. The three fields the draft
   prompt names as Block 3's grounding — `community_signals`, `competitor_weaknesses`,
   `case_evidence` — are never passed to the fact-checker. It cannot verify a pain claim
   because it never receives the evidence a pain claim would be checked against.
2. **`is_thin_signal` does not gate on pain.** It counts `competitor_weaknesses`,
   `case_evidence`, and `buying_signals`, 2-of-3. `community_signals` is not counted at all,
   and neither `case_evidence` (what they ship in today) nor `buying_signals` (a trigger
   event) is evidence that anything hurts. A prospect with both and no pain evidence
   whatsoever passes the gate and is asked for a pain block.
3. **`qa_check`'s flag scope excludes pain.** Its system prompt flags only an unsupported
   "specific stat, contract, certification, or event". A fabricated consequence is none of
   those, so it passes.

### Live failure — cold-0727 / Arcsky

State: `community_signals=[]`, `competitor_weaknesses=[]`,
`case_evidence="packs nicely into one tough portable box"` (a *positive* statement about
their current box), `buying_signals` × 4. Passes `is_thin_signal` 2-of-3. Both drafted tiers
are marked `qa_flag="passed"` and both assert pain with nothing behind it:

- `unknown` tier: *"…which surfaces later as a cracked arm or a gimbal out of true."*
  An asserted physical consequence with zero supporting evidence.
- `c-suite` tier: *"…the surveying buyers comparing NDAA packages in the mapping groups are
  asking what comes in the box before they commit."* An asserted third-party claim, while
  `community_signals` is empty.

A previous session rewrote this content by hand; the rewrite reworded the fabrication rather
than removing it. That is the argument for a mechanical gate over careful drafting.

This is the same class as two bugs already fixed this month (the gpt-4o-mini community-signal
verdict, and cross-tier email duplication): a judgment a cheap or absent gate could not hold.

## Decisions

| Decision | Choice |
|---|---|
| What counts as a pain source | `community_signals` and `competitor_weaknesses` only |
| When no pain source exists | Drop the email to a three-block shape; Block 3 is never requested |
| Detection backstop | Deterministic guard, free, no model — plus the `qa_check` evidence bug fix |
| `qa_check` flag scope | Unchanged — deliberately NOT widened to cover pain |

`case_evidence` and `buying_signals` license the opener and the value line. They never license
the pain block. Under this rule Arcsky has zero pain sources, which is the correct verdict.

Widening `qa_check`'s scope was considered and rejected. It would hand a judgment call to
gpt-4.1-mini — precisely the pattern that leaked twice this month. Prevention by construction
plus a deterministic guard carries the guarantee instead.

## Design

### A. The rule

New predicate in `gtm/draft.py`, beside `is_thin_signal`:

```python
def has_pain_source(p: Prospect) -> bool:
    return bool(p.community_signals or p.competitor_weaknesses)
```

Block 3 may exist only when this returns True.

### B. Prevention — `build_draft_prompt`

A third shape alongside `_TIER_SHAPE`:

```python
_NO_PAIN_SHAPE = (
    "Tier 1 (priority), no researched pain",
    "three blocks — opener · what we build · close",
    "~250-400 characters",
)
```

Shape selection and the prohibition are two separate things, and they key off different
conditions:

- **Shape** — `_NO_PAIN_SHAPE` replaces the four-block shape only when the prospect would
  otherwise have resolved to it (`p.status` of `priority`, or an unscored prospect falling
  through to `_DEFAULT_SHAPE`). Block 3 is removed and the remaining blocks renumbered.
  A `keep`-tier prospect keeps `_TIER_SHAPE["keep"]` — it is already three-block, so there is
  nothing to drop.
- **Prohibition** — emitted whenever `not thin and not has_pain_source(p)`, at every tier
  including `keep`: no researched pain exists for this prospect; do not assert any consequence
  they experience, and do not attribute a claim to operators, buyers, or forums.

The split matters because `_TIER_SHAPE["keep"]` describes itself as folding the pain into the
value line. Without the prohibition applying at that tier, a no-pain `keep` prospect would
invite the identical fabrication one block earlier, in Block 2. `check_pain_grounding` arms on
the same condition, so it covers `keep` prospects too.

Fabrication becomes structurally impossible at Tier 1 because the block is never asked for.
The email still ships — Arcsky keeps its trigger and its airframe, and loses only the invented
consequence.

The thin-signal SKIP path is unaffected.

### C. Detection — `check_pain_grounding`

New guard in `gtm/draft.py` with the same signature contract and the same position as
`check_tier_distinctness`: returns `""` when clean, else the flag text. Runs free, before the
paid `qa_check`, and short-circuits it.

```python
flag = (check_reference_customer(p, draft, others)
     or check_tier_distinctness(p, tier, draft)
     or check_pain_grounding(p, draft)          # NEW
     or qa_check(p, draft, costlog=costlog))
```

Wired identically in `cmd_draft` and `cmd_redraft` in `gtm/run.py`.

The guard arms **only** when `not has_pain_source(p)` — it is disarmed whenever real pain
evidence exists, which keeps the blast radius small. Once armed it scans the body for the two
fabrication shapes observed live:

- `_CONSEQUENCE_WORDS` — cracked, snapped, damaged, dented, warranty claim, RMA, downtime,
  grounded, out of true, shipping damage, replacement cost, and similar.
- `_ATTRIBUTION_PATTERNS` — "operators say/report", "buyers are asking", "customers report",
  "we hear", "in the … groups/forums/threads", "on reddit", and similar.

False positives are possible and deliberately accepted. A Block 2 value line reading "prevents
transit damage" would trip the guard; the cost is one pass through the redraft loop that
already exists.

The word lists above are a starting point, not the specification. The binding acceptance
criterion is the static-verification table below: whatever lists produce exactly two flags on
Arcsky and leave all seven other stored tier-drafts unarmed are the correct lists. Tune
against real stored state; do not invent entries to be thorough.

### D. `qa_check` evidence fix

The evidence block gains the three missing fields:

```python
evidence = (
    f"buying_signals: {p.buying_signals}\nkey_news: {p.key_news}\n"
    f"fit_reason: {p.fit_reason}\ncommunity_signals: {p.community_signals}\n"
    f"competitor_weaknesses: {p.competitor_weaknesses}\ncase_evidence: {p.case_evidence}"
)
```

The system prompt's flag scope stays stat / contract / certification / event. The gain is
narrow and real: a fabricated stat that contradicts `community_signals` becomes catchable at
all. Fabricated pain remains `check_pain_grounding`'s responsibility.

### E. Voice-guide edits

`company/voice-guide.md` is interpolated verbatim into every draft prompt, so a stale guide
fights the new instruction inside the same prompt. Two minimal edits:

- **Block 3 paragraph** — pain sources become `community_signals` / `competitor_weaknesses`
  only; `case_evidence` drops out of that list; the soft "where real evidence exists" hardens
  into: when neither exists, omit Block 3 entirely — never assert a consequence, never
  attribute a claim to operators, buyers, or forums.
- **Length-by-tier table** — Tier 1 gains a second row for the no-pain case: 3 blocks,
  ~250–400 characters.

`tests/test_voice_guide.py` asserts only social-proof and specificity strings; these edits do
not break it.

## Verification

### Unit — `tests/test_draft.py`

- `has_pain_source` across field combinations, including the Arcsky shape
  (`case_evidence` + `buying_signals`, no pain fields → False).
- `build_draft_prompt`: priority + no pain → three blocks, no pain-block header, prohibition
  line present. Priority + pain → four blocks, unchanged. `keep` + no pain → shape unchanged
  but prohibition line present. `keep` + pain and the thin-signal SKIP path → unchanged.
- `check_pain_grounding`: flags both real Arcsky bodies (consequence shape and attribution
  shape); returns `""` for a clean no-pain body; stays disarmed for a prospect that has
  `community_signals` even when the body contains a cracked-arm sentence.
- `qa_check`: the three new fields appear in the user message (mocked client).

### Wiring — `tests/test_run.py`

`cmd_draft` and `cmd_redraft` call `check_pain_grounding` before `qa_check`; a flagged draft
routes into the redraft checkpoint.

### Live, static (no API calls)

Run the guard over every stored `data/runs/*/prospects.json`. Expected, exactly:

| Run | Company | Tiers drafted | Pain sources | Expected |
|---|---|---|---|---|
| cold-0727 | Arcsky | unknown, c-suite | none | **both flag** |
| us-drone-5 | Inspired Flight Technologies | c-suite, director, manager | 5 community_signals | disarmed |
| us-drone-5 | EagleNXT | c-suite | 5 community_signals | disarmed |
| us-drone-5 | Anzu Robotics | unknown | 5 community_signals | disarmed |
| us-drone-7 | Teal Drones | manager, director | 5 community_signals | disarmed |

Two flags, seven unarmed. Any other result means the word lists need tuning.

### Live, end-to-end

Regenerate Arcsky's drafts through the new no-pain prompt on the real `cold-0727` run and
confirm the result passes all four guards. This proves prevention, not just detection.
Mutates `data/runs/cold-0727/prospects.json` (gitignored, local only) and costs one
`qa_check` call per tier. No external push — Sheet and HubSpot are the separate output stage
and are not run.

## Out of scope

- **Arcsky's stale `unknown` tier draft.** `distinct_tiers_present` now returns `['c-suite']`
  only, so that draft is dead weight in `prospects.json`. Confirmed not to reach CSV or Sheet
  output. It is also one of the two live fixtures for this work, so pruning it here would
  remove a test case. Separate change afterwards.
- **Widening `qa_check`'s flag scope** — see Decisions.
- **Changing `is_thin_signal`'s 2-of-3 threshold.** The 2026-07-27 decision stands; requiring
  a pain source to draft at all would skip nearly every contact, since
  `competitor_weaknesses` is almost always empty.
