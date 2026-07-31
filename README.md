# GTM Helper

A go-to-market pipeline that finds drone manufacturers, scores them against a case-maker's
ICP, enriches the ones that pass, drafts outreach, and pushes the result to a Google Sheet
and HubSpot. Free-tier demo of a LeadGrow-style orchestrator — the thing Clay does, built
out of Python modules and an LLM doing the judgment steps.

Selling company is **AeroVault Cases** (fictional, modeled on SKB): US maker of rugged
MIL-STD-810H / IP67 cases with custom foam for drones. Its profile and fit rules live in
[`company/ICP.md`](company/ICP.md).

## How it works

Python does the mechanical work. `gpt-4o-mini` does bulk extraction. An LLM orchestrator
(Claude Code) does the judgment — fit scoring, buying signals, draft copy — between CLI
commands, not inside them. Every stage reads and writes one JSON file per run, so a run
survives between commands and can be resumed after a crash.

| # | Stage | Engine | What it produces |
|---|---|---|---|
| 1 | Discover | Serper + `gpt-4o-mini` | Candidate makers from a natural-language query, or a fixed URL list. Resellers, listicles and news sites are filtered out |
| 2 | Scrape | crawl4ai, auto-fallback | Clean markdown. Fallback chain Firecrawl → ScrapeGraphAI → Apify; social hosts go straight to Apify |
| 3 | Extract | `gpt-4o-mini` | Structured drone fields — models, folded dims, weights, NDAA/US-made |
| 4 | Fit | LLM judgment | 0–100 score vs `company/ICP.md`, hard disqualifiers, per-signal reasons |
| 5 | Contacts + enrich | Serper + `gpt-4o-mini` | Names/titles/LinkedIn (employment-verified), company LinkedIn, headcount, deduped news, community pain signals |
| 6 | Segment + draft | LLM judgment | Persona tiers, then one email in two versions per tier, auto-QA'd against the evidence |
| 7 | Emails | Provider waterfall | Pattern guess → MyEmailVerifier/Abstract/Prospeo/Hunter/GetProspect chain → AI hunt |
| 8 | Output | gspread + HubSpot | CSV, Google Sheet upsert (matched on domain), HubSpot company/contact upsert |

Two feedback loops sit beside the pipeline:

- **Learn** — `data/feedback.jsonl` is read back and can drive an ICP or denylist edit, but
  only from entries you wrote yourself (`origin == "user"`). The orchestrator's own session
  notes are context, never grounds for a rule change on their own.
- **Postmortem** — after a run, `gtm/postmortem.py` mines that run's slice of
  `data/errors.log` and records one factual entry per distinct failure stage. Pure log
  parsing, no LLM call, no cost. Those fold into a capped `data/lessons.md` that prints at
  the start of the next run.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in the keys below
```

Minimum to run stages 1–5: `OPENAI_API_KEY` and `SERPER_API_KEY`. Everything else is
optional and degrades gracefully — a missing key skips that provider, it does not fail the
run.

Write a brief:

```markdown
---
run: my-run
query: US drone manufacturers for public safety
max_companies: 10
region: us
scraper: crawl4ai
---
Free-text notes for the orchestrator go here.
```

Use `urls:` instead of `query:` to run a fixed list of sites instead of searching. Save the
brief as `data/runs/my-run/brief.md`; the `run:` key must match that directory name. A brief
is frozen at `start` (`brief.lock.json`), so editing it mid-run does not change the run.

Note that `data/` is gitignored — runs, costs, feedback and outputs are local state and
never committed.

Then walk the stages:

```bash
python -m gtm.run start data/runs/my-run/brief.md   # discover → scrape → extract → print fit prompts
python -m gtm.run fit my-run fit.json               # apply the fit judgments
python -m gtm.run enrich my-run                     # passers only: contacts + enrichment → signal prompts
python -m gtm.run signals my-run signals.json       # apply buying signals + outreach angles
python -m gtm.run segment my-run                    # persona tiers → draft prompts
python -m gtm.run draft my-run drafts.json          # apply drafts → auto QA
python -m gtm.run redraft my-run drafts.json        # re-apply fixed drafts for anything QA flagged
python -m gtm.run emails my-run                     # email waterfall
python -m gtm.run output my-run                     # CSV, then Sheet + HubSpot push
python -m gtm.run output my-run --dry-run           # CSV only, guaranteed no external write
python -m gtm.run postmortem my-run                 # record this run's failure patterns
python -m gtm.run learn                             # review feedback, regenerate data/lessons.md
```

Or the whole thing on one company:

```bash
python -m gtm.run smoke https://tealdrones.com/          # dry
python -m gtm.run smoke https://tealdrones.com/ --live   # also pushes to the Sheet
```

### Checkpoints

Commands that need judgment stop rather than guess. They print the prompt, exit **5**, and
tell you the resume command. Write the answer to the named JSON file and run that command.
Exit **0** is success, **1** is a real error, **6** is a standards violation.

### Failures

A company that fails any stage is logged to `data/errors.log` with `status="error"` and
skipped. The run continues. Dead or guessed domains are dropped by a free DNS preflight
before any scrape credit is spent.

### Cost

Every stage appends to `data/runs/<run>/costs.jsonl` and prints a running total. Read it
back at any time:

```bash
python -c "from gtm.costlog import CostLog; print(CostLog('data/runs/my-run/costs.jsonl').summary_line())"
```

## Credentials

| Variable | Needed for | Required? |
|---|---|---|
| `OPENAI_API_KEY` | extraction, QA | yes |
| `SERPER_API_KEY` | discovery, contacts, enrichment | yes |
| `credentials/service_account.json` + `GTM_SHEET_KEY` | Google Sheet push | for stage 8 |
| `HUBSPOT_SERVICE_KEY` | HubSpot upsert | optional, skipped if absent |
| `FIRECRAWL_API_KEY`, `SCRAPEGRAPHAI_API_KEY` / `SGAI_API_KEY` | scraper fallbacks | optional |
| `HUNTER_API_KEY`, `MYEMAILVERIFIER_API_KEY`, `ABSTRACT_API_KEY`, `PROSPEO_API_KEY`, `GETPROSPECT_API_KEY` | email find/verify chain | optional |

The Sheet must be shared with the service account's email address before a push will land.
Never commit `.env` or `credentials/` — a pre-commit hook scans for keys.

## Layout

```
gtm/           one module per stage; gtm/run.py is the CLI, gtm/schema.py is the contract
company/       ICP.md (fit rules) · outreach.md (sender + approved references) · voice-guide.md
data/runs/     one directory per run: brief.md, prospects.json, costs.jsonl, CSVs
data/          feedback.jsonl · lessons.md · errors.log
docs/          PLAN.md (build plan) · tools/ (one reference per external API)
tests/         pytest against recorded fixtures — no network
```

## Tests

```bash
python -m pytest -q
```

701 tests, all offline against recorded fixtures. Each slice also got one live smoke run
against a real site, logged in `data/feedback.jsonl`.

## Conventions

Two rules that are easy to break and expensive to break:

- **Never code an external API from memory.** Fetch its official docs first and save a
  reference at `docs/tools/<name>.md` — install, auth, the exact call we make, free-tier
  caps, gotchas. Read that file before touching the integration.
- **No skill or script re-implements a pipeline stage.** Two Markdown skills that mirrored
  `gtm/draft.py` and `gtm/enrich.py` silently drifted from them and were deleted. If you
  need a manual one-off, run the CLI stage on a one-company run.

Full working agreement for the LLM orchestrator: [`CLAUDE.md`](CLAUDE.md). Build plan and
slice order: [`docs/PLAN.md`](docs/PLAN.md).
