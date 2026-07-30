# GTM Helper

Free-tier **demo** of a LeadGrow-style GTM orchestrator, built in Codex (replaces Clay).
Goal: find drone manufacturers → check if their drones fit our cases → enrich → find the
right contact → push top prospects to a Google Sheet. Full plan: `docs/PLAN.md`.

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
2. **Scrape** — crawl4ai → markdown; named in prompt; auto-fallback (Firecrawl→ScrapeGraphAI→Apify;
   social hosts go straight to Apify). Scrapling dropped — see `docs/tools/scrapers.md`.
3. **Extract** — `gpt-4o-mini`: markdown → structured drone fields (one place, scraper-agnostic).
4. **Fit** — Codex scores 0–100 vs `company/ICP.md`; hard disqualifiers.
5. **Contacts + Enrich** (passers only) — all Serper + `gpt-4o-mini`, no skill in the loop:
   `gtm/contacts.py` (`site:linkedin.com/in` + team scrape → names/titles/LinkedIn, ranked,
   employment-verified, no email yet), `gtm/enrich.py` (company LinkedIn, community signals,
   headcount, news). The `company-research` skill is a standalone research tool, NOT called
   by this stage — don't assume the pipeline runs it.
6. **Output** — CSV → Google Sheet (service account) + HubSpot (company/contact upsert,
   `gtm/hubspot.py`, gated on `HUBSPOT_SERVICE_KEY`).
- **Learn** — read `data/feedback.jsonl` → Codex proposes ICP/denylist edits, but only from
  entries the user actually gave (`Feedback.origin == "user"`, `gtm/learn.py`); Codex's own
  session/smoke-test notes are context, never grounds for an edit on their own.

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
python -m gtm.run learn                            # show feedback for ICP/denylist proposals
```
Failures are logged to `data/errors.log` and that company is skipped (`status="error"`) — never
the whole run. Example brief: `data/runs/teal-demo/brief.md`.

### ALWAYS report the run cost — no exceptions
Every stage command prints `cost this run — <provider>:$x · <provider>:N credits`
(`gtm/costlog.py::CostLog.summary_line`). **The last line of any reply that ran one or more
pipeline stages MUST be that total.** Not "if it seems relevant", not "if the user asks" —
always, including partial runs, dry runs, aborted runs, and single-stage reruns.
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
deleted 2026-07-30 — both had drifted from the modules they mirrored and were superseded by
`gtm.run redraft` / `gtm.run enrich`. Run the CLI stage on a one-company run instead.

## Structure
- `gtm/` — pipeline code (module per stage, added per slice)
- `company/ICP.md` — company profile + fit criteria (drives Fit)
- `company/outreach.md` — sender identity + approved reference customers; fills the
  `{{sender_name}}` / `{{reference_customer}}` draft tokens at output. Unfilled (TODO) =
  that contact row is blocked from the sheet, never sent with raw tokens.
- `tests/` — pytest (fixtures) · `data/` — outputs, feedback, errors
- `docs/PLAN.md` — build plan + slice order · `docs/notes.md` — original brain dump
