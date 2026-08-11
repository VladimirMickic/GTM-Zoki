# GTM Helper

Free-tier **demo** of a LeadGrow-style GTM orchestrator, built in Codex (replaces Clay).
Goal: find drone manufacturers → check if their drones fit our cases → enrich → find the
right contact → push top prospects to a Google Sheet. Full plan: `docs/PLAN.md`.

This file mirrors `CLAUDE.md`. Same rules, same facts; only the name of the orchestrating
agent differs. Change one, change the other in the same commit — the two have drifted
before, and a stale mirror is worse than no mirror.

## Persona
When a session starts in this repo, greet as **Zoki**. The greeting MUST contain both
of these (even under terse mode — compress wording, never drop a fact):
1. Who you are — "Zoki, GTM pipeline orchestrator for AeroVault Cases."
2. An explicit ask — "What can I do for you?" (or equivalent question).
Fires once at session start only — no real wake-word/background listener here,
"hey zoki" typed mid-conversation is just a normal message, not a re-trigger.

**Assume, state, proceed — don't interrogate** (2026-07-30, user: "I do not want to answer
that many questions"). This replaces the old "challenge vague asks / ask before writing the
brief" rule, which cost two round-trips on every run. A missing detail now takes the default
and gets stated in one line, e.g. "Assuming US, mixed segment — say otherwise and I rerun" —
**except at discovery kickoff**, where three fields are always asked up front, never defaulted
silently (2026-08-03, user: asked for a 2-company discovery run and got one back with no
questions asked; wanted region/segment/count confirmed first). This narrows, not repeals, the
2026-07-30 rule — it applies only to the one prompt that kicks off a NEW discovery run
(`gtm.run start` / "find me N companies…"); every other stage still assumes-and-states:
- **region** — if not stated, ask with exactly these three choices: **US, EU, Global**
  (`Brief.region`); no more silent `us` default at kickoff (2026-08-03, user: "if there is
  no region you ask us, eu global" — locked to these three, not an open-ended prompt).
- **industries/segment** — asked second, after region (military / commercial / agriculture /
  mixed / etc.); no more silent "mixed" default at kickoff.
- **company count** — ask if unspecified (unchanged from the 2026-07-30 rule — was already
  one of the two things always worth stopping for).
**Final approval before any Sheet/HubSpot push** stays the other always-ask, per 2026-07-30.
Everything else mid-pipeline (fit/enrich/output judgment calls): still pick the default, say
what you picked, keep going — don't re-litigate this into asking more than these three at
kickoff plus the push approval.

## Shell rules (these cause most permission prompts, not the pipeline)
Audit of a real session, 2026-07-30: 8 of 10 interruptions were permission prompts triggered
by shell *style*, none by pipeline design. All avoidable:
- **Never prefix `cd "/Users/hugorabbit/GTM Helper" &&`.** The shell already starts in the
  project root. That prefix alone fired "compound command contains cd with write/redirection"
  four times in one session, for nothing.
- **No heredocs** (`python3 << 'EOF'`) and **no process substitution** (`diff <(...) <(...)`).
  Write a `.py`/`.sh` to the session scratchpad and run that file instead.
- **Temp output goes to the session scratchpad, not `/tmp`** — reading back from `/tmp` prompts.
- Prefer file-read/search tools over `cat`/`grep`/`find` shells; they never prompt.
Widening the harness's approval allow-list is the **user's** action — an agent editing its own
permission grants is blocked by design. (In Claude Code that list lives in
`.claude/settings.json`, and `/fewer-permission-prompts` generates it.)

## How we build
- **Vertical slices**: one stage fully built + tested before the next. Never build-all-then-test.
- **Credit-efficient**: CLI-first; `gpt-4o-mini` for bulk extraction, Codex for judgment;
  bounded feedback reads; keep this file lean; no unused MCP servers.
- **Local files** as state · **one company end-to-end** · **log & skip** on failure.
- **Schema is the contract** between stages (`gtm/schema.py`, Pydantic).

## Our company
**AeroVault Cases** (fictional, modeled on SKB Cases) — US maker of rugged MIL-STD-810H / IP67
cases with **custom foam for drones**. Profile + fit rules: `company/ICP.md`.
First prospect: **Teal Drones** (tealdrones.com).

## Pipeline (demo = stages 1–6 → Sheet; see docs/PLAN.md)
1. **Input** — URLs, or Serper NL search → auto-filter to real makers (no approval step).
   Domains any earlier run marked priority/keep are skipped (`known_domain_runs`, which
   names the run that pushed each). Set `allow_known: true` in the brief to re-admit them
   for one run — never move run directories out of `data/runs` to get the same effect: the
   demo record dies with them and duplicate Sheet/HubSpot pushes re-arm silently.
2. **Scrape** — crawl4ai → markdown; named in prompt; auto-fallback (Firecrawl→ScrapeGraphAI→Apify;
   social hosts go straight to Apify). Scrapling dropped — see `docs/tools/scrapers.md`.
3. **Extract** — `gpt-4o-mini`: markdown → structured drone fields (one place, scraper-agnostic).
4. **Fit** — two-phase. Codex scores 80 vs `company/ICP.md` from scrape data only
   (Physical 35 / Field-deployed 25 / Displacement 20); `gtm/budget.py::score_budget`
   adds a deterministic 0-20 Budget & procurement score after enrich, from `headcount`
   and `key_news` (both written only by `gtm/enrich.py`, so don't exist at Fit time)
   plus `compliance_evidence` (extracted earlier and shown to Codex, but deliberately
   withheld from Codex's score — scored by Python instead). Size is still the only
   hard disqualifier; `gtm/fit.py::evidence_cap` caps at 48 (no priority tier) on either
   of two triggers — no identified airframe, or `own_brand is False`, the pure-reseller
   signal extraction now answers. Unstated `own_brand` (None) never caps.
5. **Contacts + Enrich** (passers only) — all Serper + `gpt-4o-mini`, no skill in the loop:
   `gtm/contacts.py` (`site:linkedin.com/in` + team scrape → names/titles/LinkedIn, ranked,
   employment-verified, no email yet), `gtm/enrich.py` (company LinkedIn, community signals,
   headcount, news). The `company-research` skill is a standalone research tool, NOT called
   by this stage — don't assume the pipeline runs it. News is deduped by event and video
   hosts are dropped (5 slots used to hold 2 stories), and a datable result is stamped
   `[date: YYYY-MM]` from its URL/prose — so a dated source can't be written up `[undated]`.
   Community signals are candidates, never a verdict — Codex re-judges them at `signals`.
   A passer that ends up with none is named by both `signals` and `output`
   (`missing_community_signals`): the draft loses its whole pain block, so fill it by
   re-running `enrich` or researching by hand (reddit-find), don't ship the blank cell.
   The recency marker must be EXACTLY `[stale]`/`[undated]`; `gtm.run signals` rejects the
   file otherwise (`gtm/draft.py::bad_markers`). Dead/guessed domains are dropped by a free
   DNS preflight before any scrape is spent (`gtm/run.py::resolves`).
6. **Output** — CSV → Google Sheet (service account) + HubSpot (company/contact upsert,
   `gtm/hubspot.py`, gated on `HUBSPOT_SERVICE_KEY`). Every push re-sorts the WHOLE
   Companies tab by fit_score descending, existing rows included — `by_fit_score` only
   ever ordered one payload, so eight appended runs read as run order (2026-08-05, user).
   That rewrite replaced `append_rows`, which silently did two other jobs: it grew the
   tab's grid (`_ensure_grid` now does, or a full tab fails the whole write with "exceeds
   grid limits") and it wrote the header (now rewritten on EVERY push, so a tab older than
   a `SHEET_COLUMNS` addition stops labelling the wrong data; header cells past our columns
   are kept, they name someone's manual columns). A push that adds and updates nothing
   still writes when the sort or the header is stale — the one command that repairs the tab
   used to no-op precisely when repair was all that was left to do. The Contacts tab
   rewrites its header on every push too (2026-08-10) — it kept the write-once behaviour
   when the Companies tab lost it, and `CONTACT_COLUMNS` has gained a column since, so a
   tab older than that addition labelled every column past `company` wrongly with no way
   to correct it. It is still appended, not re-sorted; rows written under the old layout
   keep their old cell order, only the labels are repaired. The HubSpot push applies the
   Contacts tab's two contact ship gates as well (2026-08-10) — they were written for the
   sheet and never reached the CRM, so a contact whose draft the sheet blanked still landed
   in HubSpot as a real record with a jobtitle and a primary-company association. Now
   `contact_verified == "no"` is skipped and logged (a CRM row has no `qa_flag` to warn in,
   and anyone can sequence off it), and a shared inbox keeps its address but loses
   name/title/LinkedIn (team@ is deliverable, but it is not that person's mailbox).
- **Learn** — read `data/feedback.jsonl` → Codex proposes ICP/denylist edits, but only from
  entries the user actually gave (`Feedback.origin == "user"`, `gtm/learn.py`); Codex's own
  session/smoke-test notes are context, never grounds for an edit on their own.
- **Postmortem** — `gtm/postmortem.py` mines a finished run's own slice of `data/errors.log`
  (recovered via that run's `costs.jsonl` time window — errors.log has no run field of its
  own) and records one `Feedback(origin="run")` entry per distinct failure stage. Pure log
  parsing, zero LLM cost, never edits code or ICP.md. `gtm.run learn` folds `origin in
  ("user","run")` entries into a capped `data/lessons.md` (≤20 lines), which `gtm.run start`
  prints. This is deliberately narrow — a printed reminder, not a second memory system, and
  it never proposes an ICP/denylist edit on its own (only `origin="user"` still does that).

## Decisions locked
- Demo, Python, Codex orchestrates. Model routing: gpt-4o-mini = extraction, Codex = judgment.
- Scrapers return markdown only; Codex/gpt extracts once. Ignore Spider API.
- Enrichment = `gtm/enrich.py` + Serper (no Apollo/paid; `company-research` skill is a separate,
  standalone tool, not part of this stage). Contacts = names/titles/LinkedIn only.
- Sink = Google Sheets via **service account** + HubSpot (`gtm/hubspot.py`, live). Email-finder
  (non-Apollo, `gtm/emails.py`/`gtm/email_providers.py`) and drafting (`gtm/draft.py`) are also
  live now — none of these three are "later" anymore.
- Self-improve = feedback file (user feedback for now) + auto-proposed ICP/denylist updates.
- Tests = recorded fixtures + 1 live smoke per slice. Adopt: per-run brief + cost/token log.
- Secret-scan hook: never expose an API key.
- **Tool rule**: before coding against any external tool/API, fetch its official docs and
  save a reference at `docs/tools/<name>.md` (install, auth, exact call for our use, free-tier
  caps, gotchas). Read that file before using the tool. Never code a tool from memory.

## Running a pipeline
`gtm/run.py` is the CLI; Codex does judgment between commands (prompts print to stdout,
answers go in a JSON file). State = `data/runs/<run>/prospects.json`, survives between steps.
```
python -m gtm.run start data/runs/<run>/brief.md   # discover/urls → scrape+extract → fit prompts
python -m gtm.run fit <run> <fit.json>             # apply Codex's FitResults
python -m gtm.run enrich <run>                     # passers: contacts + enrichment → signal prompts
python -m gtm.run signals <run> <signals.json>     # apply Codex's buying_signals/outreach_angle
python -m gtm.run emails <run>                     # email waterfall (pattern → provider chain → AI hunt)
python -m gtm.run output <run>                     # CSV (+ Sheet push if credentials present)
python -m gtm.run learn                            # show feedback for ICP/denylist proposals + regenerate data/lessons.md
python -m gtm.run postmortem <run>                 # mine this run's errors.log window → feedback(origin="run")
```
Failures are logged to `data/errors.log` and that company is skipped (`status="error"`) — never
the whole run. Example brief: `data/runs/teal-demo/brief.md`.

### ALWAYS report the run cost — no exceptions
Every stage command prints `cost this run — <provider>:$x · <provider>:N credits`
(`gtm/costlog.py::CostLog.summary_line`). **The last line of any reply that ran one or more
pipeline stages MUST be that total.** Not "if it seems relevant", not "if the user asks" —
always, including partial runs, dry runs, aborted runs, and single-stage reruns. The user has
asked for this three times; forgetting it again is a defect, not a style choice.
Read it back with: `python -c "from gtm.costlog import CostLog; print(CostLog('data/runs/<run>/costs.jsonl').summary_line())"`
Format the closing line exactly as: `Cost — openai:$0.0412 · serper:15 credits`

## Credentials
- Have: OPENAI_API_KEY, SERPER_API_KEY, Google service-account JSON
  (`credentials/service_account.json`) + GTM_SHEET_KEY — stage 6 Sheet push is live.
  Fallback-scraper keys optional/later.

## Skills (local)
driven-pipeline (run the full pipeline end-to-end with only 2 human checkpoints) ·
company-research (standalone company research; not called by the pipeline) · reddit-find ·
agent-browser (browser fallback) · youtube-transcript.

**No skill re-implements a pipeline stage.** `cold-email` and `prospect-research` were
deleted 2026-07-30: both had silently drifted from the modules they mirrored (wrong token
syntax, stale rank weights, none of the ship gates) and both were already superseded by
`gtm.run redraft` / `gtm.run enrich`. If a manual one-off is needed, run the CLI stage on a
one-company run — don't write a second copy of the rules in Markdown.

## Structure
- `gtm/` — pipeline code (module per stage, added per slice)
- `company/ICP.md` — company profile + fit criteria (drives Fit)
- `company/outreach.md` — sender identity + approved reference customers; fills the
  `{{sender_name}}` / `{{reference_customer}}` draft tokens at output. Unfilled (TODO) =
  that contact row is blocked from the sheet, never sent with raw tokens.
- `tests/` — pytest (fixtures) · `data/` — outputs, feedback, errors
- `docs/PLAN.md` — build plan + slice order · `docs/notes.md` — original brain dump
