# Driven-pipeline: two human checkpoints only

## Problem

`gtm/run.py` architecture always intended Claude to answer judgment prompts
(fit, signals, displacement, draft, QA) — CLAUDE.md states it plainly: "Claude
does judgment between commands (prompts print to stdout, answers go in a JSON
file)." In practice the human has been operating the CLI by hand — running
each stage, reading each prompt, hand-writing each JSON answer file. That's
the friction, not the architecture. Every judgment stage surfaced as a
checkpoint the human had to personally clear.

## Design

**No pipeline code changes.** This is an operating procedure for me (Claude)
driving the existing `gtm.run` CLI via my own Bash tool, end-to-end, within
one session. Two human checkpoints only:

1. **Company count** — asked once, up front, only if not stated. "hey zoki,
   find me drone companies" → I ask "how many?". "find me 3 companies" → I
   skip the question, run with 3.
2. **Draft approval** — before the Sheet push. I show a compact table
   (company, contact, tier, subject, angle) and full draft text on request.
   User approves all, or flags specific rows to redo. Nothing pushes to the
   Sheet without this.

### Flow

1. Wake word "hey zoki" → greeting (existing persona rule, unchanged).
2. User states the ask ("find me N drone companies" / "find me drone
   companies"). If N is absent, ask once. Then run:
   ```
   python -m gtm.run start data/runs/<run>/brief.md
   ```
3. Fit checkpoint: I score each company vs `company/ICP.md` myself, write
   `fit.json`, run `python -m gtm.run fit <run> fit.json`. No stop.
4. Enrich checkpoint: `python -m gtm.run enrich <run>` prints signal +
   displacement prompts per company. I research and judge (using
   `company-research` / `reddit-find` skills where real enrichment data is
   needed), write `signals.json`, run
   `python -m gtm.run signals <run> signals.json`. No stop.
5. `python -m gtm.run segment <run>` → per-(company,tier) draft prompts. I
   write copy per `company/voice-guide.md`, write `drafts.json`, run
   `python -m gtm.run draft <run> drafts.json`. QA-flagged tiers get redrafted
   by me in the same pass — no stop.
6. **Checkpoint 2**: present the draft table. Wait for approval / redo
   requests. On redo, I rewrite just those tiers and re-show the table.
7. On approval: `python -m gtm.run output <run>` → CSV + Sheet push.

### Error handling

Unchanged from CLAUDE.md: log-and-skip. A company that errors at any stage
goes to `data/errors.log` with `status="error"` and drops out of the run; it
does not stop the rest of the pipeline or surface as a checkpoint.

### Cost logging

Unchanged — `data/runs/<run>/costs.jsonl` keeps recording as today.

### Out of scope

- No new CLI command (`gtm.run auto`) — that's a possible future hardening
  step (option B, deferred) once this manual-driving procedure is proven on
  a live run.
- No autonomous self-judgment via a wired-in API call (option C, deferred
  indefinitely — overkill for a demo, needs cost guardrails).
- Sheet dedupe-by-company gap (known, carried over from prior handoff) is
  unchanged by this work — still append-only, still needs the tabs cleared
  by hand before `output` per Task 11's rollout note.

## Why this design over the alternatives

- **B (new `auto` command)** would harden this into one CLI call, but adds
  real implementation + test surface for a workflow that's unproven end-to-end
  today. Right move after A is validated on a real run, not before.
- **C (full autonomy via wired API)** removes me from the loop entirely,
  which contradicts CLAUDE.md's stated architecture ("Claude does judgment")
  and adds cost-control risk with no demo benefit.
