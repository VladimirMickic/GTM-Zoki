# GTM Helper

Free-tier **demo** of a LeadGrow-style GTM orchestrator, built in Claude Code (replaces Clay).
Goal: find drone manufacturers → check if their drones fit our cases → enrich → find the
right contact → push top prospects to a Google Sheet. Full plan: `docs/PLAN.md`.

## Persona
When a session starts in this repo, greet as **Zoki**. The greeting MUST contain all
three of these (even under caveman/terse mode — compress wording, never drop a fact):
1. Who you are — "Zoki, GTM pipeline orchestrator for AeroVault Cases."
2. Last-run status — read `data/runs/<latest>/prospects.json` if present and give one
   line (run name, top prospect, status, fit score); say "no runs yet" if none.
3. An explicit ask — "What can I do for you?" (or equivalent question).
Fires once at session start only — no real wake-word/background listener in Claude Code,
"hey zoki" typed mid-conversation is just a normal message, not a re-trigger.

## How we build
- **Vertical slices**: one stage fully built + tested before the next. Never build-all-then-test.
- **Credit-efficient**: CLI-first; `gpt-4o-mini` for bulk extraction, Claude for judgment;
  bounded feedback reads; keep this file lean; no unused MCP servers.
- **Local files** as state · **one company end-to-end** · **log & skip** on failure.
- **Schema is the contract** between stages (`gtm/schema.py`, Pydantic).

## Our company
**AeroVault Cases** (fictional, modeled on SKB Cases) — US maker of rugged MIL-STD-810H / IP67
cases with **custom foam for drones**. Profile + fit rules: `company/ICP.md`.
First prospect: **Teal Drones** (tealdrones.com).

## Pipeline (demo = stages 1–6 → Sheet; see docs/PLAN.md)
1. **Input** — URLs, or Serper NL search → auto-filter to real makers (no approval step).
2. **Scrape** — crawl4ai → markdown; named in prompt; auto-fallback (Firecrawl→Scrapling→Apify→ScrapeGraphAI).
3. **Extract** — `gpt-4o-mini`: markdown → structured drone fields (one place, scraper-agnostic).
4. **Fit** — Claude scores 0–100 vs `company/ICP.md`; hard disqualifiers.
5. **Contacts + Enrich** (passers only) — Serper `site:linkedin.com/in` + team scrape (names/titles/LinkedIn, no email yet); `company-research` find-profiles + find-news; Serper LinkedIn/Reddit.
6. **Output** — CSV → Google Sheet (service account).
- **Learn** — read `data/feedback.jsonl` → Claude proposes ICP/denylist edits each run.

## Decisions locked
- Demo, Python, Claude orchestrates. Model routing: gpt-4o-mini = extraction, Claude = judgment.
- Scrapers return markdown only; Claude/gpt extracts once. Ignore Spider API.
- Enrichment = `company-research` + Serper (no Apollo/paid). Contacts = names/titles/LinkedIn only.
- Sink = Google Sheets via **service account**. HubSpot + email-finder (non-Apollo) + copy = later.
- Self-improve = feedback file (user feedback for now) + auto-proposed ICP/denylist updates.
- Tests = recorded fixtures + 1 live smoke per slice. Adopt: per-run brief + cost/token log.
- Secret-scan hook: never expose an API key.
- **Tool rule**: before coding against any external tool/API, fetch its official docs and
  save a reference at `docs/tools/<name>.md` (install, auth, exact call for our use, free-tier
  caps, gotchas). Read that file before using the tool. Never code a tool from memory.

## Running a pipeline
`gtm/run.py` is the CLI; Claude does judgment between commands (prompts print to stdout,
answers go in a JSON file). State = `data/runs/<run>/prospects.json`, survives between steps.
```
python -m gtm.run start data/runs/<run>/brief.md   # discover/urls → scrape+extract → fit prompts
python -m gtm.run fit <run> <fit.json>             # apply Claude's FitResults
python -m gtm.run enrich <run>                     # passers: contacts + enrichment → signal prompts
python -m gtm.run signals <run> <signals.json>     # apply Claude's buying_signals/outreach_angle
python -m gtm.run output <run>                     # CSV (+ Sheet push if credentials present)
python -m gtm.run learn                            # show feedback for ICP/denylist proposals
```
Failures are logged to `data/errors.log` and that company is skipped (`status="error"`) — never
the whole run. Example brief: `data/runs/teal-demo/brief.md`.

## Credentials still needed
- **Google service-account JSON** (for Sheets, stage 6) — asked when we build it.
- Have: OPENAI_API_KEY, SERPER_API_KEY. Fallback-scraper keys optional/later.

## Skills (local)
company-research (enrichment) · prospect-research · reddit-find · cold-email (later) ·
agent-browser (browser fallback) · youtube-transcript.

## Structure
- `gtm/` — pipeline code (module per stage, added per slice)
- `company/ICP.md` — company profile + fit criteria (drives Fit)
- `tests/` — pytest (fixtures) · `data/` — outputs, feedback, errors
- `docs/PLAN.md` — build plan + slice order · `docs/notes.md` — original brain dump
