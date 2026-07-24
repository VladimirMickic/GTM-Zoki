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
