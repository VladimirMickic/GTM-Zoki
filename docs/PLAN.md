# GTM Helper — Build Plan

Scoped, free-tier demo of a LeadGrow-style GTM orchestrator. Claude Code orchestrates;
Python does mechanical work; `gpt-4o-mini` does bulk extraction; Claude does judgment.

## Principles
- **Vertical slices**: one stage fully built + tested (recorded fixtures) before the next.
- **Credit-efficient**: CLI-first, `gpt-4o-mini` for grunt-work, bounded feedback reads, lean CLAUDE.md, no unused MCP servers.
- **Local files** as state; **one company end-to-end**; **log & skip** on failure.
- **Schema is the contract** between stages (`gtm/schema.py`, Pydantic).

## Pipeline (demo scope = stages 1–6 → Google Sheet)
| # | Stage | Engine | Notes |
|---|---|---|---|
| 1 | Input / discover | Python + Serper | URLs, or NL search → auto-filter to real makers |
| 2 | Scrape | crawl4ai (→ markdown) | named in prompt, auto-fallback: Firecrawl→Scrapling→Apify→ScrapeGraphAI |
| 3 | Extract | `gpt-4o-mini` | markdown → structured drone fields |
| 4 | Fit score | Claude | 0–100 vs `company/ICP.md`, hard disqualifiers |
| 5a | Contacts (passers) | Serper + crawl4ai | names/titles/LinkedIn (no email yet) |
| 5b | Enrich (passers) | company-research skill + Serper | 5 Serper credits/company: company LinkedIn · 2 community-signal pain queries · headcount · news |
| 6 | Output | Python (gspread) | CSV → Google Sheet (service account) |
| — | Learn | Claude | read `data/feedback.jsonl` → propose ICP/denylist edits |

Built since (past the original demo scope): segment (`gtm/segment.py`), displacement
(`gtm/displace.py`), persona tiers (`gtm/persona.py`), cold-email drafts (`gtm/draft.py`),
email waterfall (`gtm/emails.py`, `gtm/email_providers.py`), HubSpot push (`gtm/hubspot.py`).

## Build order (each = code + recorded-fixture test + 1 live smoke)
- **S0 – Scaffold**: Pydantic `Prospect` schema, per-run `brief.md`, cost/token log, secret-scan hook.
- **S1 – Scrape**: crawl4ai → clean markdown; auto-fallback; fixture = tealdrones.com.
- **S2 – Extract**: gpt-4o-mini markdown → `{models, folded_dims, weight, us_made, ...}`.
- **S3 – Fit**: Claude scores vs ICP; disqualifier checks; per-signal breakdown.
- **S4 – Contacts**: Serper `site:linkedin.com/in` + team-page scrape → contact rows.
- **S5 – Enrich**: passers only; company LinkedIn · community-signal pain (2 queries, LLM
  relevance filter) · headcount · news. See `gtm/enrich.py` for the per-query credit budget.
- **S6 – Output**: CSV writer + Google Sheet push (service account).
- **S7 – Orchestrate** (done): `gtm/run.py` CLI — `start`/`fit`/`enrich`/`signals`/`emails`/`output`/`learn`,
  Claude judges between steps via printed prompts + JSON answer files. State = `data/runs/<run>/prospects.json`,
  log&skip → `data/errors.log`, cost log. Live E2E on Teal Drones: fit 85/priority (re-run 2026-07-18 after feedback round 1: split dims/weights, top-3 contacts, news snippets, line-per-point reasons). Commands in CLAUDE.md.

## Sheet columns
Pushes are **upserts**, not appends: a company already on the sheet (matched on
normalized website domain) has its row rewritten in place; only new domains append.
Contacts match on email → LinkedIn → name+company (`_contact_dedupe_key`). So
re-running a company after a bugfix corrects its row — no manual clear ritual,
and no permanently stale row (2026-07-27, supersedes the 2026-07-24 skip rule).

Main tab = full funnel, one row per company, ends at community_signals. Shows all
three tiers (Tier 3/drops included, tagged in the `tier` column):
company · website · description · drone_models · drone_dimensions · drone_weights · best_case_line · us_made/NDAA ·
fit_score · **tier** · **why_fit** · fit_reason · buying_signals · key_news · linkedin · headcount · community_signals
`why_fit` is derived too (band + score · case line · top buying signal) — a one-glance summary
so a reader gets the gist without opening the long cells. `headcount` is an employee band from
`gtm/enrich.py::find_headcount`; blank when no source states one (never a guessed number).
`tier` (1/2/3) is derived from status by `Prospect.tier` (priority=1, keep=2, drop=3, error/unscored blank),
never a stored field. Only Tier 1/2 get enrichment/contacts/drafts (enrich/segment/draft
gate on `status in ("priority","keep")`); Tier 3 rows show fit only.

Contacts get their own tab/CSV (one row per person, not packed into the company row):
company · website · contact_name · contact_title · contact_linkedin · contact_email · email_status ·
outreach_angle · pain_points · talking_points · draft_initial_subject · draft_initial_body ·
draft_initial_subject_alt · draft_initial_body_alt · needs_research · qa_flag · date_processed
Format is locked at **one email, two versions** (no follow-up) by `company/voice-guide.md`.
Drafts are per **persona tier**, not per company: `Prospect.drafts_by_tier` holds one `DraftSet`
per tier present among that company's contacts (`gtm/persona.py::distinct_tiers_present`), and
`gtm/output.py::build_contact_rows` picks the matching-tier set for each contact row — a CFO and
a director never share talking points. Company-level cells repeat per row so each row stands alone.

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
