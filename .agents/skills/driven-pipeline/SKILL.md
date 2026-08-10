---
name: driven-pipeline
description: Drive the full gtm.run pipeline (start → fit → enrich → signals → segment → draft → redraft → emails → output) end-to-end via Bash, answering every judgment checkpoint directly instead of surfacing it to the user. Use when the user says "hey zoki, find me drone companies" (or similar) or otherwise asks to run/start a GTM pipeline. Reduces the human-facing checkpoints to exactly two: an up-front company-count question (only if unspecified) and a final draft-approval gate before the Sheet push.
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
   - **`community_signals` is a required answer, not an optional key.** The prompt shows gpt-4o-mini's candidates; re-judge each (a satisfied setup described in case-and-foam vocabulary is the common false positive) and write back the ones that name a real harm. If every candidate fails — or the funnel line printed by `enrich` shows `kept=0` — do not leave the key empty and move on: run `reddit-find` for that company's segment and source real operator pain by hand. 2026-08-05: eight runs' worth of live Sheet rows had an empty `community_signals` cell, which costs every draft its pain block (`gtm/draft.py::has_researched_pain`). `signals` and `output` both name the companies still empty; an empty cell that survives to the Sheet is a defect unless you can say what you searched.
4. `python -m gtm.run segment <run>` — assigns a segment bucket per company and prints one draft prompt per (company, tier) pair for every tier present. Every tier always gets `pain_points` + `talking_points` tailored to that tier's position (`company/voice-guide.md`'s "Persona tailoring" — a CFO and a director never get the same angle). A single email draft (no follow-up, 2 versions) is only requested when the prompt says the signal supports one (`gtm/draft.py::is_thin_signal` — needs a competitor weakness, case evidence, AND a buying signal); otherwise the prompt says SKIP and pain_points/talking_points are that tier's whole deliverable — do not invent a draft when told to skip. Write per `company/voice-guide.md` (category-only social proof, every value-prop claim backed by a concrete mechanism/spec — no bare comparatives) to `data/runs/<run>/drafts.json`, then `python -m gtm.run draft <run> drafts.json`.
5. Any tier QA-flags (an actual drafted email with an unsupported claim — tiers skipped for thin signal are auto-marked `n/a` and never flagged): re-answer just those tiers in a new JSON, `python -m gtm.run redraft <run> drafts.json`. Repeat until no real `qa_flag` remains. No stop.

## Fact-check pass (before Checkpoint 2)

For every tier that has a draft (skip tiers with no `draft_initial` — they
were intentionally not drafted), pull that prospect's `case_evidence` and
`competitor`/`competitor_weaknesses` fields (in `data/runs/<run>/prospects.json`)
and check the draft's `initial_body`/`initial_body_alt` for every named
competitor, spec rating, or dimension. Anything in the draft text that
doesn't appear in those source fields gets rewritten (via `redraft`) before
it reaches the table below. Deterministic string check — no LLM call.

## Checkpoint 2: draft approval

Present one compact table: company, contact, tier, subject line (or "—
talking points only" if `needs_research`), one-line angle, **fact-check
result** (the `qa_flag` value verbatim — `passed`, the flagged claim text, or
the `n/a — talking-points only...` marker — never omit this column, it's
the whole point of the QA step). Offer full draft text, pain_points, and
talking_points for any row on request. Wait for the user to approve all or
flag specific rows. On a flagged row, rewrite just that tier and redraft,
then re-show the table (loop until approved).

## Emails (before output — do not skip)

After approval, before `output`: `python -m gtm.run emails <run>` — runs the
pattern-tier → provider-chain → AI-hunt waterfall (`gtm/emails.py`) per
contact and writes verified/risky/unverified results into
`contact_emails`. Skipping this step is the single most common way a run
ends up with zero emails — `output` never calls it itself. Prints its own
`[<company>] <emails>` lines and a cost summary; relay both to the user, not
just the final one (see Cost visibility below).

## Output

Only after approval and the emails step above: `python -m gtm.run output <run>`
(add `--dry-run` first if the user wants to inspect the CSV before a live
Sheet push). Sheet push dedupes automatically — Companies by domain,
Contacts by email (falling back to LinkedIn, then name) — so re-running
against the same Sheet is safe and never needs a manual clear.

## Cost visibility

Every stage command (`start`, `enrich`, `signals`, `draft`/`redraft`,
`emails`, `output`) prints its own `cost this run — provider:$x.xx ·
provider:N credits` line (`gtm/costlog.py::CostLog.summary_line`) after it
finishes — this already covers OpenAI $, Serper credits, and any configured
email-provider (Prospeo/Hunter/GetProspect/Abstract) credits/$. Do not let
this scroll past silently in Bash output: after each stage, surface that
line to the user in your own reply (one line is enough), and give one final
consolidated total right before or alongside the Checkpoint 2 table and
again after `output` completes.

## Errors

Log-and-skip, unchanged: a company erroring at any stage lands in
`data/errors.log` with `status="error"` and drops out — never stops the rest
of the run.
