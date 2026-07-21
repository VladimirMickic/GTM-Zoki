# Competitor displacement + per-persona drafts — design

Status: approved by user (verbal design in prior session, confirmed via AskUserQuestion
this session for the 3 remaining open decisions). Not yet implemented.

## Why

User feedback on the live `us-drone-3` Google Sheet (verbatim, prior session):

> "All of these emails are the same... craft a better more professional email from
> examples... This is sooo vague and unprofessional: 'Custom-foam cases protect each unit
> better than the stock Pelican 1520.'"

> "we do not score if there is a competitor detected! WHY? ... If there is a competitor
> detected there should be an agent that tries to displace! Look at bad reviews for
> competitor on that product."

> "The email to a cfo or a director/manager cannot be the same!"

Three problems, three parts to this design:

1. **Fit scoring penalizes a detected competitor case instead of treating it as an
   opportunity.**
2. **No research step turns a detected competitor into usable email ammo** (concrete
   weaknesses/complaints about that specific product).
3. **One draft per company, tailored to only the single top-ranked contact** — a CFO and a
   director at the same company get an identical email.

Plus two smaller, related fixes surfaced during the same feedback: emails read as vague
("protects better than X" with no concrete mechanism), and the voice guide's social-proof
step implies real customers AeroVault doesn't have (it's a fictional demo company).

## Part 1 — Fit scoring: competitor detected = opportunity, not penalty

`company/ICP.md`'s current "Upgrade gap" signal (15 pts) scores a **named** incumbent
competitor case LOW (0–3/15 — "we'd be displacing an established brand") and a generic/soft
case HIGH (10–15/15 — "easy upgrade"). This is backwards for a company that explicitly wants
to go compete for switchers.

**Change**: rename the signal **"Displacement opportunity"** and flip the scoring:

| case_evidence | Score | Why |
|---|---|---|
| Named rugged-case competitor identified (Pelican, Nanuk, SKB, Hardigg, Seahorse, Explorer, etc.) | 12–15/15 | Concrete displacement target — Part 2's research turns this into cited email ammo. |
| Generic/soft case, no branded competitor, or no case at all | 8–11/15 | Still an upgrade opportunity, but no named incumbent to research weaknesses on. |
| Unknown after the web hunt | 3/15 exactly | Unchanged — never award midpoint points for missing evidence. |

Update in both places that currently encode the old scoring:
- `company/ICP.md` — the "Fit scoring" table row + the "Upgrade-gap scoring must cite
  case_evidence" paragraph directly below it.
- `gtm/fit.py::build_fit_prompt` — no code change needed here; it interpolates the ICP text
  verbatim, so the ICP.md edit is sufficient. (Verified: the prompt has no independently
  hardcoded scoring language.)

This changes `fit_score` for prospects with a named competitor (e.g. AeroVironment/Pelican
1520 goes from 78 upward). A fit re-run after this ships is expected to move numbers — not a
regression.

## Part 2 — Displacement research (competitor → cited weaknesses)

### Detecting the competitor (no new LLM call)

`gtm/segment.py` already has a `_RUGGED_BRANDS` keyword list and does a substring check
against `case_evidence` for `assign_segment`'s upgrade-vs-generic branch. Rather than adding
a new gpt-4o-mini extraction field (credit-efficiency is a locked project decision —
`CLAUDE.md` "Credit-efficient" bullet), reuse this deterministic detection:

- Move `_RUGGED_BRANDS` to a new `gtm/displace.py` (canonical home) and have `gtm/segment.py`
  import it, so there's one source of truth.
- Add `detect_competitor(case_evidence: str) -> str` in `gtm/displace.py`: regex-match a
  brand keyword in `case_evidence`, and if a model-number-shaped token (e.g. `1520`, `X200`)
  appears within the same short string, append it (`"Pelican 1520"`); otherwise return just
  the brand (`"Pelican"`). Empty string if no brand keyword matches. Pure Python, zero API
  cost.

### The research prompt

`gtm/displace.py::build_displacement_prompt(company: str, competitor: str) -> str` — a
Claude-checkpoint prompt (same pattern as `build_signal_prompt`), instructing use of the
**`reddit-find`** and **`company-research`** skills (per user's explicit instruction — not a
single Serper call) to find 2–3 concrete, cited weaknesses/complaints about the *named
competitor product specifically* (e.g. "Pelican 1520 too heavy" / reddit complaints). Reply
shape: `{"competitor_weaknesses": ["<complaint> — <source/context>", ...]}`, plain English,
2–3 entries max.

### Where it plugs into the pipeline (resolved: fold into enrich/signals checkpoint)

No new CLI stage. In `cmd_enrich` (`gtm/run.py`):
- After `enrich(p)` runs (so `p.case_evidence` is already set from stage 3), compute
  `competitor = detect_competitor(p.case_evidence)` for each `priority`/`keep` prospect.
- Store `p.competitor = competitor` (new state field, empty string if none).
- When printing the signal-prompt block, if `competitor` is truthy, also print
  `build_displacement_prompt(p.company, competitor)` right after that company's signal
  prompt, under the same `signals.json` checkpoint file — one round-trip, not two.
- `signals.json`'s per-company answer shape grows one optional key:
  `{"buying_signals": [...], "outreach_angle": "...", "competitor_weaknesses": [...]}` —
  `competitor_weaknesses` omitted or `[]` when no competitor was detected.
- `merge_signals` (`gtm/run.py`) also sets `p.competitor_weaknesses = s.get("competitor_weaknesses", [])`.

New `Prospect` fields (state-only, not new `SHEET_COLUMNS` entries for v1 — keeps the sheet
lean per the trimming work from the prior session; `draft.py` reads them directly):
```python
competitor: str = ""
competitor_weaknesses: list[str] = []
```

### Segment + outreach angle

`gtm/segment.py::assign_segment` currently has a `"generic-case-upgrade"` bucket keyed off
the same brand-substring check this design is replacing. Refactor it to call
`gtm.displace.detect_competitor(p.case_evidence)`:
- Truthy → new segment `"competitor-displacement"` (checked before the old generic-upgrade
  branch — a named competitor is a stronger, more specific hook than "you have no case").
- Falsy but an upgrade keyword matches (soft bag / backpack / generic case / foam insert,
  no brand) → keep the existing `"generic-case-upgrade"` bucket, unchanged semantics.

`company/ICP.md`'s "Outreach angles" section gets one new line:
- **Competitor detected** → "named-competitor weakness, cited — displace with proof."

### Draft prompt: use the ammo

`gtm/draft.py::build_draft_prompt` (see Part 3 for its full signature change) adds, when
`p.competitor_weaknesses` is non-empty, a block instructing the value-prop step to name the
specific competitor product and cite one weakness verbatim from `competitor_weaknesses`
instead of the generic "better than X" framing that prompted this whole design.

## Part 3 — Per-persona-tier drafts

### Current state (confirmed this session, not re-litigated from handoff)

`gtm/persona.py::classify_persona` on the three real AeroVironment contacts:
- `"Vice President and Chief Technologist"` → `c-suite`
- `"VP Logistics Operations"` → `c-suite` (bare `"vp"` keyword catches it — a known
  quirk, not in scope to fix here; flagged separately below)
- `"Senior Director International Sales"` → `director`

So AeroVironment today would get exactly **2** distinct draft sets (c-suite, director), not
3, even after this ships — Dan Stone (VP Logistics Operations) and Scott Newbern (VP & Chief
Technologist) both classify c-suite. This is fine: the design drafts by distinct tier
*present*, and 2 tiers being present is a correct outcome of the current classifier, not a
bug in this design.

### Schema change (resolved: dict tier → DraftSet)

New nested model in `gtm/schema.py`:
```python
class DraftSet(BaseModel):
    initial_subject: str = ""
    initial_body: str = ""
    initial_subject_alt: str = ""
    initial_body_alt: str = ""
    followup_subject: str = ""
    followup_body: str = ""
    followup_subject_alt: str = ""
    followup_body_alt: str = ""
    qa_flag: str = ""  # per-tier — each tier's draft can reference different facts
```

`Prospect.drafts_by_tier: dict[str, DraftSet] = {}` **replaces** the 8 flat
`draft_initial_subject`/`draft_initial_body`/`_alt` ×2 fields and the prospect-level
`qa_flag` field entirely (no backwards-compat shim — nothing outside this codebase reads
`prospects.json` directly).

### Tier enumeration

New helper in `gtm/persona.py`:
```python
def distinct_tiers_present(contact_titles: str) -> list[str]:
    """contact_titles: the CONTACT_FIELD_SEP-joined Prospect.contact_title field.
    Returns distinct classify_persona() tiers, in first-seen order. Empty/all-blank
    titles produce ["unknown"] (a single default draft, never zero)."""
```

### Draft prompt (one call per distinct tier present)

`build_draft_prompt(voice_guide: str, p: Prospect, tier: str) -> str` — signature grows a
required `tier` argument (was: infer persona from `p.contact_title`'s first entry only).
Same brief as today, but the "This contact" block now describes the *tier* generically
("this email is for the {tier} persona at {company} — apply the matching rule from the
voice guide's Persona tailoring section") rather than quoting one specific contact's title,
since a tier can represent multiple contacts.

Reply JSON nests one level deeper, keyed by tier:
```json
{"CompanyName": {
  "c-suite": {"draft_initial": {...}, "draft_followup": {...}},
  "director": {"draft_initial": {...}, "draft_followup": {...}}
}}
```

`cmd_segment` (`gtm/run.py`) prints one prompt block per `(prospect, tier)` pair — header
`----- {company} [{tier}] -----` — looping `distinct_tiers_present(p.contact_title)` for
every `priority`/`keep` prospect.

`merge_drafts` builds one `DraftSet` per tier key present in the answer and assigns into
`p.drafts_by_tier[tier]`.

### QA (per tier)

`cmd_draft`/`cmd_redraft` loop `p.drafts_by_tier.items()` and call `qa_check` once per
`(prospect, tier)` — same gpt-4.1-mini call, just multiplied by tiers-present instead of
1-per-prospect (still cheap: 2 tiers × a handful of qualified companies). `qa_check` and
`build_redraft_prompt` take the specific `DraftSet` instead of reading flat `Prospect`
fields.

### Output: pick the right draft per contact row

`gtm/output.py::build_contact_rows` currently repeats the single company-level draft on
every contact row. Change: for each contact index, classify that contact's own
`contact_title` (`classify_persona`), look up `prospect.drafts_by_tier.get(tier)` falling
back to `.get("unknown")`, and merge `{FIRST_NAME}`/`{COMPANY}` into *that* draft set's
text instead of the old flat fields. The row's `qa_flag` cell also switches source, from
`prospect.qa_flag` (removed) to that same matched `DraftSet.qa_flag`.

## Also in scope — flagged fixes riding along

### Voice guide: ban vague value-prop assertions

`company/voice-guide.md` has no rule today against generic "X protects better than Y"
claims with no mechanism named — the user's own quoted complaint was drafted under the
current guide. Add to the "Banned phrases / openers" section (or a new "Specificity"
subsection): value-prop claims must name a concrete mechanism or spec difference (a
MIL-STD-810H drop-test spec, a cited competitor weakness from `competitor_weaknesses`, a
specific dimension/feature) — never a bare comparative ("better protection", "keeps your
gear safe") with nothing concrete backing it.

### Voice guide: social proof → category proof only

AeroVault Cases is fictional; no real customers exist. Resolved this session: **category
proof only** — "other defense sUAS makers ship in our cases" style claims, never a named
client/logo. Update the "Email structure" section's step 2 ("a use case + social proof (a
comparable, well-known customer)...") and the "Value prop" framing example ("We saw
companies similar to you have {xyz}") to explicitly say category-level only, never a named
company, since AeroVault has no real customers to cite.

### Known quirk, explicitly out of scope

`classify_persona`'s bare `"vp"` keyword check classifies "VP Logistics Operations" as
c-suite when it arguably reads more manager-ish. Not fixed by this design — flagged so it
isn't rediscovered as a surprise. A future design can tighten the c-suite keyword list.

## Testing (TDD, per this repo's established convention)

- `tests/test_displace.py` (new): `detect_competitor` against known brand strings, model-
  number extraction, no-match case; `build_displacement_prompt` shape.
- `tests/test_segment.py`: update for `"competitor-displacement"` bucket + brand detection
  now routed through `gtm.displace.detect_competitor`.
- `tests/test_fit.py`: no code changes expected (ICP.md is data, not code) — but add a
  regression test asserting `build_fit_prompt` output contains "Displacement opportunity"
  wording sourced from the ICP text, so a future ICP.md edit that breaks the rename is
  caught.
- `tests/test_persona.py`: `distinct_tiers_present` — multiple distinct titles, all-same
  tier collapses to one entry, blank/empty → `["unknown"]`.
- `tests/test_schema.py`: `DraftSet` model, `Prospect.drafts_by_tier` default `{}`,
  `to_sheet_row`/`SHEET_COLUMNS` unaffected (drafts were never a sheet column).
- `tests/test_draft.py`: `build_draft_prompt` requires `tier` arg now; competitor-weakness
  block appears only when `competitor_weaknesses` is non-empty; `qa_check`/
  `build_redraft_prompt` operate on a `DraftSet`.
- `tests/test_output.py`: `build_contact_rows` picks the tier-matching `DraftSet` per
  contact index, falls back to `"unknown"`.
- `tests/test_run.py` (or wherever `cmd_enrich`/`cmd_segment`/`cmd_draft` are covered):
  displacement prompts print only for competitor-bearing prospects; segment/draft loops
  emit one block per distinct tier.

## Rollout

After merge: re-run `enrich → signals → segment → draft → output` for `us-drone-3` (fit
scores will shift per Part 1 — expected, not a bug) and re-push the Sheet tabs. Reminder
carried over from the prior handoff: `push_to_sheet`/`push_contacts_to_sheet` are still
append-only with no dedupe-by-company — clear the tabs by hand before re-pushing, same as
last time.
