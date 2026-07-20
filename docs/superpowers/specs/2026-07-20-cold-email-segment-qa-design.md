# Design: cold-email drafting + segment/QA stages

Date: 2026-07-20
Status: proposed (pending user review)

## Context

`docs/PLAN.md` and the hardening plan's self-review both listed cold-email drafting as "later,
not demo scope." All 7 hardening slices are now code + live-smoke complete and pushed
(`.superpowers/sdd/progress.md`). This is genuinely new pipeline scope: three new stages —
`segment`, `draft`, `qa` — inserted between the existing `signals` and `output` stages.

## Pipeline order

```
start → fit → enrich → signals → segment → draft → output
```

Two new CLI commands. `qa` is not a separate command — it's an automated model call that runs
inline at the end of `draft` (same precedent as `extract`, which has no CLI command of its own
and runs inside `start`).

```
python -m gtm.run segment <run>              # deterministic bucketing → prints DRAFT PROMPTS → checkpoint
python -m gtm.run draft <run> <drafts.json>  # merge Claude's drafts → auto QA fact-check → done
```

`cmd_segment` mirrors `cmd_enrich`'s shape: does real work, then prints the next stage's prompts
and raises `CheckpointPending`. `cmd_draft` mirrors `cmd_fit`/`cmd_signals` (merges an answer
file) but keeps working after the merge to run QA — no checkpoint follows.

`STAGE_NAMES` (`gtm/run.py`) gains two entries: `"segment"`, `"draft"`. No `"qa"` entry — QA is
tracked under the `"draft"` stage label.

## Voice guide

`company/voice-guide.md` (written this session, committed separately) is the source of truth
for tone, format caps, banned phrases, signature, and style-anchor example emails. `draft`'s
prompt builder reads it directly rather than duplicating its content in code.

## Schema changes (`gtm/schema.py`)

New `Prospect` fields:

| Field | Sheet column? | Notes |
|---|---|---|
| `segment: str = ""` | No | Internal targeting signal for `draft`; state-only, same treatment as `case_evidence`. |
| `draft_initial_subject: str = ""` | Yes | v1 (primary) variant. |
| `draft_initial_body: str = ""` | Yes | v1 (primary) variant. |
| `draft_followup_subject: str = ""` | Yes | v1 (primary) variant. |
| `draft_followup_body: str = ""` | Yes | v1 (primary) variant. |
| `draft_initial_subject_alt: str = ""` | No | v2 variant, state-only — read from `drafts.json` if the user wants it. |
| `draft_initial_body_alt: str = ""` | No | v2 variant, state-only. |
| `draft_followup_subject_alt: str = ""` | No | v2 variant, state-only. |
| `draft_followup_body_alt: str = ""` | No | v2 variant, state-only. |
| `qa_flag: str = ""` | Yes | Empty when clean; else a short note of the unsupported claim. |

`SHEET_COLUMNS` gains 5 entries, inserted after `outreach_angle` and before `contact_name`:
`draft_initial_subject`, `draft_initial_body`, `draft_followup_subject`, `draft_followup_body`,
`qa_flag`.

## `segment` stage (`gtm/segment.py`)

Pure Python, deterministic, no LLM call. `assign_segment(p: Prospect) -> str`, applied to every
`priority`/`keep` prospect. Reuses `ICP.md`'s existing 4 outreach angles as the bucket taxonomy
(no new vocabulary). Checked in priority order, first match wins:

1. **`defense-ndaa-win`** — `p.us_made_ndaa is True`
2. **`generic-case-upgrade`** — `p.case_evidence` (lowercased) contains any of: `"soft bag"`,
   `"backpack"`, `"soft case"`, `"generic case"`, `"foam insert"`, and does not name a rugged-case
   brand/partner
3. **`new-model-launch`** — any string in `p.buying_signals` contains (case-insensitive)
   `"launch"`, `"new model"`, `"unveil"`, or `"announc"`
4. **`field-harsh-environment`** — fallback default; always matches if nothing above did

Rationale for this order: `defense-ndaa-win` correlates with the highest-weighted Fit signal
(NDAA/defense, 15 pts) so it's the strongest hook when present; `generic-case-upgrade` is the
next-most concrete, evidence-backed pain point.

`cmd_segment(run)`:
1. `load_state`, apply `assign_segment` to priority/keep prospects, `save_state`.
2. Build and print `=== DRAFT PROMPTS ===` — one call to `build_draft_prompt(p)` per
   priority/keep prospect.
3. `raise CheckpointPending(file="drafts.json", action="draft emails", resume=f"python -m gtm.run draft {run} drafts.json")`.

## `draft` stage (`gtm/draft.py`)

`build_draft_prompt(p: Prospect) -> str`:
- Reads `company/voice-guide.md` once, embeds its full content.
- Includes `p.outreach_angle` (the hook, not re-derived), `p.segment` (which angle category to
  lean into), `p.buying_signals`, `p.key_news`, `p.fit_reason` (supporting specifics).
- Format constraints are stated inline and self-enforced by the prompt (not checked in code):
  2-email sequence × 2 versions, subject <40 chars, body ~150 chars, voice-guide's banned
  phrases, signature block, `{FIRST_NAME}`/`{COMPANY}` vars.
- Asks Claude to save, per company, to `drafts.json`:
  ```json
  {
    "<company>": {
      "draft_initial": {"v1": {"subject": "...", "body": "..."}, "v2": {"subject": "...", "body": "..."}},
      "draft_followup": {"v1": {"subject": "...", "body": "..."}, "v2": {"subject": "...", "body": "..."}}
    }
  }
  ```

`merge_drafts(prospects, raw: dict) -> None` — writes the 8 draft fields per prospect from that
shape (v1 → the 4 surfaced fields, v2 → the 4 `_alt` fields).

`qa_check(p: Prospect) -> str` — one `gpt-4.1-mini` call via `OPENAI_API_KEY`. Checks whether
`p.draft_initial_body` references any stat/claim not actually present in `p.buying_signals`,
`p.key_news`, or `p.fit_reason`. Returns `""` if clean, else a short flag string. Fact-checking
only — mechanical rule compliance (length, banned phrases) is the `draft` prompt's job, not
QA's.

`cmd_draft(run, drafts_json)`:
1. `load_state`.
2. `merge_drafts(prospects, json.loads(Path(drafts_json).read_text()))`.
3. `save_state`.
4. For each prospect with a draft: `try: p.qa_flag = qa_check(p) except Exception as e: _log_error(ERROR_LOG, p.company, "qa", e)` — API failure logs-and-skips (`qa_flag` stays `""`), never blocks output. Matches the pipeline-wide "log & skip" philosophy (CLAUDE.md).
5. `save_state`.
6. Print summary: `f"{n} drafted, {m} flagged"`.

QA never excludes a prospect from `output` and never triggers a redraft loop — flagged
prospects still reach the Sheet/CSV/HubSpot, `qa_flag` just tells the user to check by hand
before sending.

## Error handling

- `segment`: pure Python, no external call, no failure mode beyond a code bug.
- `draft` merge: same shape as existing `merge_fit`/`merge_signals` — malformed JSON raises,
  same as those (no new handling needed, matches precedent).
- `qa_check`: wrapped in try/except, log-and-skip per prospect, never crashes the whole `draft`
  command.

## Testing

Per CLAUDE.md: TDD (RED→GREEN), recorded fixtures + 1 live smoke.

- `gtm/segment.py`: unit tests for each of the 4 bucket rules + the priority-order tie-break
  (a prospect matching both `defense-ndaa-win` and `generic-case-upgrade` conditions gets
  `defense-ndaa-win`), plus the fallback default.
- `gtm/draft.py`: unit tests for `build_draft_prompt`'s shape (includes voice-guide content,
  outreach_angle, segment), `merge_drafts`'s JSON→field mapping (v1 vs `_alt`), and `qa_check`
  with a mocked OpenAI response (both a clean case and a flagged case).
- `cmd_segment`/`cmd_draft`: tests asserting checkpoint-raise behavior (mirrors existing
  `cmd_start`/`cmd_enrich` checkpoint tests) and the log-and-skip path on a forced `qa_check`
  exception.
- One live smoke: run `segment` + `draft` against a real run directory (e.g. re-use
  `discover-3` or `github-smoke`'s existing state), confirm real `gpt-4.1-mini` QA call fires,
  confirm `qa_flag` populates correctly on at least one deliberately-mismatched draft.

## Out of scope for this design (deferred)

- Auto-redraft loop on QA failure — explicitly rejected.
- Hard-blocking flagged prospects from `output` — explicitly rejected.
- Haiku-drafts / Sonnet-polish two-tier drafting split — v1 is single-pass; only build if
  quality demands it later.
- A separate lightweight mechanical-rules gate (length/banned-phrase checker as code) — folded
  into the `draft` prompt instead, per the locked decision above.
