# GTM Helper — Build Plan

Scoped, free-tier demo of a LeadGrow-style GTM orchestrator. Claude Code orchestrates;
Python does mechanical work; `gpt-4o-mini` does bulk extraction; Claude does judgment.

## Principles
- **Vertical slices**: one stage fully built + tested (recorded fixtures) before the next.
- **Credit-efficient**: CLI-first, `gpt-4o-mini` for grunt-work, bounded feedback reads, lean CLAUDE.md, no unused MCP servers.
- **Local files** as state; **one company end-to-end**; **log & skip** on failure.
- **Schema is the contract** between stages (`gtm/schema.py`, Pydantic).

## Pipeline (demo scope = stages 1–5 → Google Sheet)
| # | Stage | Engine | Notes |
|---|---|---|---|
| 1 | Input / discover | Python + Serper | URLs, or NL search → auto-filter to real makers |
| 2 | Scrape | crawl4ai (→ markdown) | named in prompt, auto-fallback: Firecrawl→Scrapling→Apify→ScrapeGraphAI |
| 3 | Extract | `gpt-4o-mini` | markdown → structured drone fields |
| 4 | Fit score | Claude | 0–100 vs `company/ICP.md`, hard disqualifiers |
| 5a | Contacts (passers) | Serper + crawl4ai | names/titles/LinkedIn (no email yet) |
| 5b | Enrich (passers) | company-research skill + Serper | find-profiles + find-news + LinkedIn/Reddit |
| 6 | Output | Python (gspread) | CSV → Google Sheet (service account) |
| — | Learn | Claude | read `data/feedback.jsonl` → propose ICP/denylist edits |

Later (out of demo scope): segment, copy (cold-email), QA, HubSpot/Bison, verified emails (non-Apollo).

## Build order (each = code + recorded-fixture test + 1 live smoke)
- **S0 – Scaffold**: Pydantic `Prospect` schema, per-run `brief.md`, cost/token log, secret-scan hook.
- **S1 – Scrape**: crawl4ai → clean markdown; auto-fallback; fixture = tealdrones.com.
- **S2 – Extract**: gpt-4o-mini markdown → `{models, folded_dims, weight, us_made, ...}`.
- **S3 – Fit**: Claude scores vs ICP; disqualifier checks; per-signal breakdown.
- **S4 – Contacts**: Serper `site:linkedin.com/in` + team-page scrape → contact rows.
- **S5 – Enrich**: passers only; find-profiles + find-news + 1 Serper each (LinkedIn/Reddit).
- **S6 – Output**: CSV writer + Google Sheet push (service account).
- **S7 – Orchestrate** (done): `gtm/run.py` CLI — `start`/`fit`/`enrich`/`signals`/`output`/`learn`,
  Claude judges between steps via printed prompts + JSON answer files. State = `data/runs/<run>/prospects.json`,
  log&skip → `data/errors.log`, cost log. Live E2E on Teal Drones: fit 85/priority (re-run 2026-07-18 after feedback round 1: split dims/weights, top-3 contacts, news snippets, line-per-point reasons). Commands in CLAUDE.md.

## Sheet columns
Main tab ends at community_signals (company-level enrichment only):
company · website · description · drone_models · drone_dimensions · drone_weights · best_case_line · us_made/NDAA ·
fit_score · fit_reason · buying_signals · key_news · linkedin · community_signals

Contacts get their own tab/CSV (one row per person, not packed into the company row):
company · outreach_angle · contact_name · contact_title · contact_linkedin · contact_email · email_status ·
source · date_processed · status(feedback)
Company-level fields (company · outreach_angle · source · date_processed · status) repeat on
every contact row so each row is self-contained — see `gtm/output.py::build_contact_rows`.
Drafts (draft_initial/followup subject+body) + qa_flag are state-only — they live in
`drafts.json` / on the `Prospect` model (read by `gtm/draft.py`, `gtm/hubspot.py`), not on either Sheet tab.

## Credentials needed from user (asked per slice)
- **S6**: Google Cloud **service-account JSON** + share target Sheet with its email.
- **Fallback scrapers (optional, later)**: Firecrawl / ScrapeGraphAI free-tier keys.
- Already have: OPENAI_API_KEY, SERPER_API_KEY.

## Model routing (right model per job)
**Demo (now):**
| Task | Model | Why |
|---|---|---|
| Extraction (drone fields, contacts, SERP filter) | `gpt-4o-mini` | cheap, structured, proven in Keller |
| Fit score · enrichment synthesis · feedback learning | Claude (orchestrator) | judgment, in-loop, no extra key |

**Later (email/QA — not demo):**
| Task | Model | Why |
|---|---|---|
| Cold-email drafts (volume) | `claude-haiku-4-5` | Anthropic voice at Haiku cost |
| Email polish (high-value only) | `claude-sonnet` | best quality when prospect is worth it |
| Semantic QA | `gpt-4.1-mini` | cheap judgment |
| Ultra-cheap bulk fallback | `deepseek-*` (optional) | only if OpenAI cost bites at scale; needs `DEEPSEEK_API_KEY` |

- **No Opus** anywhere — nothing here needs it; too expensive. **No DeepSeek** for the demo.
- Demo needs **no new models/keys** — `gpt-4o-mini` + Claude covers it.

## Deps (add per slice)
`pydantic`, `python-dotenv`, `pytest`, `requests`, `crawl4ai`, `openai`, `gspread`, `google-auth`
