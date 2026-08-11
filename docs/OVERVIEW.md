# GTM Helper — Project Overview

Written 2026-08-11. Plain-language tour of what this project is, how it is put together,
and why each big decision went the way it did. If you are new here, read this before
`CLAUDE.md` or `docs/PLAN.md` — those two assume you already know the shape of the thing.

---

## 1. What this project is

It finds companies worth selling to, decides which ones are actually worth the effort,
learns enough about each one to write a credible email, finds the right person to send it
to, writes the email, and puts the whole result in a Google Sheet and a CRM.

That is what Clay does. Clay charges per credit and gives you a visual builder. This does
the same job with about 7,300 lines of Python, an LLM doing the parts that need judgment,
and free API tiers. Total real money spent building and running it so far: **under nine
cents**, plus 352 Serper search credits.

The demo scenario, which everything is currently tuned for:

- **We are** AeroVault Cases — a fictional US maker of rugged waterproof cases with custom
  cut foam for drones. Modeled on the real company SKB.
- **We sell to** companies that *manufacture* drones. Their customers carry those drones
  into fields, deserts and disaster zones, so the drones need a case built around them.
- **The pipeline's job** is to find those manufacturers, work out whose drone actually fits
  one of our four case sizes, and hand a salesperson a ready-to-send email.

Everything about our company and who we want lives in one file, `company/ICP.md`. That file
is deliberately the only place the sales strategy is written down.

### What you can do with it right now

| Job | How |
|---|---|
| Find new companies from scratch | Write a brief with a `query:`, run the pipeline. "20 US public-safety drone makers" → Sheet rows |
| Enrich a list you already have | Same, but with `urls:` instead of `query:`. Skips the discovery step |
| Investigate one company deeply | `python -m gtm.run smoke https://example.com` — whole pipeline, one company |
| Fix and re-run | Re-run any company after a bugfix. The Sheet matches on website domain and rewrites the row in place, so nothing goes stale and nothing duplicates |
| Learn from what went wrong | `postmortem` reads the run's errors and writes them down; `learn` turns your own feedback into proposed changes to the sales rules |

### What it is *not* yet

It is not industry-agnostic. You can change *who we sell to* by editing `company/ICP.md`,
and that genuinely re-aims the judgment. But the data structure itself is drone-shaped —
there are columns called `drone_models`, `drone_dimensions`, `best_case_line` — and the
budget scorer looks for defense words like NDAA and Blue UAS. Pointing this at, say, SaaS
companies is a real code change across three files, not a settings tweak. Worth knowing
before anyone promises otherwise.

---

## 2. The core idea: Python does the work, the LLM does the thinking

This is the single most important design decision, and everything else follows from it.

A pipeline stage is either **mechanical** or **judgment**:

- **Mechanical** — "extract the dimensions from this page", "check if this email address
  bounces", "sort the sheet by score", "does this headline mention a funding round". Same
  input must always give the same output. These are Python functions, and where a small
  cheap model is needed for bulk text work, they call `gpt-4o-mini`.
- **Judgment** — "how well does this company fit us", "is this Reddit thread real customer
  pain or just chatter", "write an email that sounds like a person". These need reading
  between lines. These go to Claude.

The two never mix inside one function. Where they meet, they meet at a file.

### How a stage stops to ask a question

When a Python stage reaches something needing judgment, it does not guess and it does not
call an LLM inline. It **prints a prompt, exits with code 5, and stops.** You write the
answer into a JSON file and run the next command, which reads it.

```
python -m gtm.run start data/runs/my-run/brief.md   # …prints fit prompts, exits 5
python -m gtm.run fit my-run fit.json               # you supply the judgments here
```

That sounds clunky. It buys three things that matter a lot:

1. **The run survives everything.** Crash, rate limit, closed laptop, a week off — state
   lives in `data/runs/<run>/prospects.json` and the next command picks up where you left off.
2. **Every judgment is inspectable and re-doable.** The prompt is on screen; the answer is a
   file you can read, edit and re-apply. Nothing important happens invisibly inside a black box.
3. **Cost is bounded and visible.** No stage can quietly decide to make forty LLM calls.

Exit codes are the protocol: `0` success, `1` real error, `5` waiting for judgment, `6`
standards violation.

### Why the whole thing does not just kill itself on one bad company

Every company is processed inside its own try/except. A company that fails any stage gets
logged to `data/errors.log`, marked `status="error"`, and skipped. The run continues. This
is called log-and-skip and it is the reason a 20-company run with three dead websites still
produces 17 good rows instead of a stack trace.

---

## 3. Why Python modules instead of Claude skills

This question has an evidence-based answer, because we tried it the other way and it failed.

Two skills, `cold-email` and `prospect-research`, were Markdown files that duplicated the
logic of `gtm/draft.py` and `gtm/enrich.py`. Both were deleted on 2026-07-30 because both
had **silently drifted** from the modules they mirrored — wrong token syntax, out-of-date
ranking weights, and none of the safety checks that stop a bad email from shipping. Nobody
noticed until someone compared them line by line.

The structural reasons this was always going to happen:

- **You cannot test prose.** 862 automated tests hold this pipeline's behavior in place.
  A Markdown file has nothing to assert. When the contact ranking rules changed, the module's
  tests changed with them and failed loudly; the skill's copy just quietly stopped matching.
- **Two copies of a rule is one rule and one lie.** The moment only one gets edited, they
  disagree, and no diff will ever tell you.
- **Prose costs tokens every single run** and gets re-interpreted slightly differently each
  time. `score_budget` is a regex — same input, same 20 points, free, forever.
- **Some rules must not be negotiable.** The size disqualifier, the 48-point cap on
  resellers, the rule that blocks an email with unfilled placeholder text. These are applied
  by Python *before and after* the LLM specifically so the LLM cannot reason its way past them.
- **Failures need a type, not a paragraph.** `ScrapeError` and exit code 5 can be handled.
  A skill that goes wrong just produces confident-sounding text.

**The line we hold:** skills orchestrate and judge; modules execute. The `driven-pipeline`
skill is legitimate — it drives CLI commands and answers checkpoints. It re-implements no
stage. If you need a one-off manual run, run the real CLI stage on a one-company run rather
than writing a second copy of the rules in Markdown.

---

## 4. The stages, in order

| # | Stage | What happens | Engine |
|---|---|---|---|
| 1 | Discover | A plain-English query goes to Serper (Google search API); `gpt-4o-mini` filters out listicles, news articles and resellers, keeping real manufacturers | Serper + gpt-4o-mini |
| 2 | Scrape | Each site is crawled to clean markdown. If the main scraper fails, three backups try in turn | crawl4ai → Firecrawl → ScrapeGraphAI → Apify |
| 3 | Extract | The markdown becomes structured fields: model names, folded dimensions, weights, US-made status, whether they make their own brand | gpt-4o-mini |
| 4 | Fit | Score 0-100 against `company/ICP.md`. Claude scores 80 from the website; Python adds 20 later | Claude + Python |
| 5a | Contacts | For passers only: find real people with titles and LinkedIn profiles, ranked by who actually buys | Serper |
| 5b | Enrich | For passers only: company LinkedIn, headcount, recent news, and complaints from public forums | Serper + gpt-4o-mini |
| 6 | Segment | Bucket each company into one of four outreach angles, deterministically | Python |
| 7 | Draft | One email in two versions per persona tier, then an automatic fact-check against the evidence | Claude + gpt-4.1-mini |
| 8 | Emails | Find and verify an address: guess the pattern, then a chain of five providers, then an AI hunt | Provider chain |
| 9 | Output | CSV, then Google Sheet, then HubSpot | gspread + HubSpot API |

Two loops run beside the pipeline rather than in it:

- **Learn** reads `data/feedback.jsonl` and can propose changes to the sales rules — but
  **only from entries you wrote yourself**. Claude's own notes about a run are context, never
  grounds for changing the strategy. That guardrail exists so the system cannot slowly talk
  itself into a different ICP.
- **Postmortem** reads a finished run's slice of the error log and records one factual entry
  per kind of failure. Pure text parsing, no LLM, no cost. These feed a capped 20-line
  `data/lessons.md` that prints when the next run starts.

---

## 5. The Python files, explained

### The contract — what every stage agrees on

**`gtm/schema.py`** (395 lines) — The most important file in the repo. Defines `Prospect`,
the single data structure every stage reads and writes, using Pydantic so bad data fails
immediately instead of three stages later. Also owns the locked Sheet column order and the
rules for trimming long cells.

One nice detail: `tier` (1/2/3) is *computed* from status, never stored. There is no way for
a company's tier to disagree with its score, because the tier is not a separate fact.

**`gtm/brief.py`** (79) — Each run starts with a `brief.md`: a few lines of YAML plus notes.
It is **frozen** to `brief.lock.json` when the run starts, so editing the brief halfway
through cannot silently change what the run was. Also validates the run name (see §7).

**`gtm/control.py`** (29) — Tiny file, big job. The exit codes and the `CheckpointPending`
exception. This is what turns "stop rather than guess" from a good intention into something
the code enforces.

### The orchestrator

**`gtm/run.py`** (983) — The command-line interface. Eleven `cmd_*` functions, one per stage.
Holds the per-company error handling that makes log-and-skip work, and the DNS preflight that
throws away dead or guessed domains before spending a single scrape on them.

### Finding and reading companies

**`gtm/discover.py`** (168) — Turns "US drone makers for public safety" into a list of
candidate websites and filters the junk out of the search results.

**`gtm/scrape.py`** (442) — Fetches sites as markdown. Four scrapers in a fallback chain;
social media hosts skip straight to Apify because the others cannot read them. It returns
markdown *only*, on purpose — that way there is exactly one extraction path no matter which
scraper won.

**`gtm/spechunt.py`** (97) — A quietly clever one. If a company's own site never publishes
its drone's folded dimensions, this searches the wider web — spec pages, reviews, Reddit
threads, unboxing videos — *before* fit gets judged. Without it, a great prospect with a
thin website would be permanently stuck in a low scoring band for a reason that has nothing
to do with how good a customer they'd be.

**`gtm/extract.py`** (105) — Markdown in, structured fields out, via `gpt-4o-mini`. Also
answers `own_brand`: does this company make its own drones, or just resell other people's?

### Deciding who is worth it

**`gtm/fit.py`** (240) — Builds the scoring prompt, merges Claude's answer back in, and
applies `evidence_cap`: a hard 48-point ceiling when no airframe was identified, or when the
company is a pure reseller. Python caps what Claude scores — the model can be persuasive,
but it cannot lift a reseller into the priority tier.

**`gtm/budget.py`** (159) — The final 20 points, with **zero LLM involvement**. Regexes over
headcount and news. Includes two "veto" rules learned the hard way: a market-size forecast
("drone market to hit $12 billion") is not this company's money, and winning a trophy is not
winning a contract.

**`gtm/displace.py`** (160) — Detects whether a company uses a competitor's case or builds
its own, and turns that into cited ammunition for the email.

**`gtm/segment.py`** (56) — Sorts each company into one of four outreach angles. Pure Python,
no ambiguity.

**`gtm/persona.py`** (47) — Turns a job title into a seniority tier: finance, C-suite,
director, manager, individual contributor. Only labels the tier — *what to actually say* to
each tier lives in `company/voice-guide.md`. Labelling and doctrine deliberately separated.

### Learning about the ones who passed

**`gtm/contacts.py`** (253) — Finds real people via LinkedIn search plus the company's own
team page. Ranks by who actually signs off on transport cases: founders and chiefs first,
sales last. Verifies the person still works there. Excludes CEOs — unless they founded the
company, because at a founder-led company those are the same person, and blanket-excluding
CEOs once left a drafted email with no recipient at all.

**`gtm/enrich.py`** (863) — The second-largest module, and it earns it. Five Serper credits
per company buys: company LinkedIn, two searches for public complaints, headcount, and news.
The subtlety is all in the cleanup — news is deduplicated by *shared entities* rather than
similar headlines (and needs two matches, not one, or generic acronyms cause false merges),
missing dates are recovered from URLs, and video hosts are dropped because five news slots
were once holding two actual stories.

### Writing the email

**`gtm/draft.py`** (695) — Builds the draft prompt, then runs an automatic quality check on
what comes back. The checks are the interesting part: is the claimed customer pain actually
traceable to a source, are two personas' emails suspiciously similar, is the email padded
with spec jargon, is it the right length for the tier, does it reuse sentences from another
company's email in the same batch. A draft that fails gets flagged and re-drafted, not shipped.

**`gtm/render.py`** (169) — Fills placeholders like `{{sender_name}}` at the last moment —
or **refuses to ship the row**. If a placeholder cannot be filled, that contact is blocked
from the Sheet entirely. Nothing goes out with raw `{{tokens}}` in it, ever.

**`gtm/emails.py`** (312) + **`gtm/email_providers.py`** (307) — The address waterfall. Guess
the pattern from the name and domain, then try five free-tier providers in turn, then an AI
hunt as a last resort. Detects catch-all domains, so a domain that accepts *everything* never
gets reported as a verified address.

### Getting it out

**`gtm/output.py`** (608) — CSV first, then the Sheet. Rows are **upserted** on normalized
website domain, so re-running a company corrects its existing row rather than adding a second
one. Every push re-sorts the whole Companies tab by score, rewrites both tab headers, and
grows the grid if needed. A push that adds nothing new still runs, because sometimes the
repair *is* the job.

**`gtm/hubspot.py`** (338) — Company and contact upsert into the CRM. Applies the same two
safety gates as the Sheet: an unverified contact is skipped entirely, and a shared inbox like
`team@` keeps its address but loses the person's name and title — because `team@` is real
mail, but it is not that person's mailbox.

### Watching itself

**`gtm/costlog.py`** (125) + **`gtm/claudeusage.py`** (113) — Every stage appends what it
spent to a per-run JSONL file. The second file reads Claude's own token usage out of the
Claude Code session transcript, so the judgment cost gets charged to the run instead of being
invisible.

**`gtm/github_state.py`** (176) — One GitHub Issue per run, lifecycle tracked in labels,
checkpoints posted as comments.

**`gtm/postmortem.py`** (137) + **`gtm/learn.py`** (90) — The two feedback loops from §4.

**`gtm/smoke.py`** (117) — One company, end-to-end, dry or live. The fastest way to check the
whole pipeline still works.

**`gtm/net.py`** (80) — Security. Covered in §7.

---

## 6. How scoring works

A company gets 0-100. It is scored in **two phases**, for a specific reason: some of the
evidence does not exist yet when scoring starts.

| Criterion | Points | Who scores it | Where the evidence comes from |
|---|---|---|---|
| Airframe physically fits one of our cases | 35 | Claude | The scraped website |
| Field-deployed / rugged use | 25 | Claude | The scraped website |
| Displacement opportunity | 20 | Claude | The scraped website |
| Budget & procurement | 20 | Python, deterministic | Enrichment data (headcount, news) |

Claude scores the first 80 from **website data only**, and is explicitly forbidden from using
what it already knows about a famous company. Python adds the last 20 after enrichment, from
data that literally does not exist at fit time.

**Result bands:** 70-100 = `priority` (Tier 1, full personalized outreach) · 40-69 = `keep`
(Tier 2, still drafted) · under 40 = `drop` (Tier 3, logged and excluded, never drafted).

### The rule that matters most

**Every criterion's bottom band is "no evidence."** Missing evidence scores the bottom band,
never the middle.

This sounds pedantic and is not. On run `us-drone-20`, a criterion produced the line "no
unit-price/volume evidence was captured this run" attached to a score of 10/15. The model had
no evidence, so it quietly filled the gap with what it happened to know about a famous
company. A score the underlying data cannot support looks exactly like a real finding, and
for a company nobody has heard of it silently collapses to zero. Hence: no evidence, bottom
band, always.

### The hard limits Python enforces regardless of what Claude says

- **Size is the only automatic rejection.** Too big for our largest case (40×24×16 inches
  folded) or a toy under 250g. Everything else that used to auto-reject — foreign company,
  racing drones, software-only — is now a score penalty instead, because each of those was
  sometimes wrong.
- **48-point cap** when no airframe was identified at all, or when the company is a pure
  reseller. The reseller case is subtle: a reseller's site lists *every* airframe it stocks,
  so the no-airframe cap never fired. The drone genuinely does fit our foam — the reseller
  just is not the buyer, because the manufacturer commissions the case, not the shop. So
  extraction answers a separate `own_brand` question, and a `false` there caps the score no
  matter how many drones are listed. Silence is `null`, never `false` — a site that simply
  does not say is not evidence of reselling.

### Displacement /20 — the argument, since it comes up

The instinct is that a company which builds its own cases is *harder* to displace, so
weighting in-house enclosures highest looks wrong.

That instinct is measuring win *probability*. A fit score should approximate expected value,
which is deal size × probability. In-house loses on probability and wins on both other terms:

- **Nobody is defending the account.** A Pelican-equipped prospect has a vendor with a
  relationship, a contract, volume pricing and a rep who will discount to keep it. In-house
  has none of that. The opposition is internal inertia, which has no sales team.
- **It is a recurring line, not one order.** Displacing Pelican wins a case order.
  Displacing in-house tooling wins the enclosure line, and every airframe revision after it.
- **They already agree with our pitch.** A company that tooled its own housing has decided
  rugged transport is part of the product and has a budget line for it. The soft-bag band is
  where you still have to sell the category itself.
- **The cost is visible to the person we email.** Tooling, molds, spares and a revision every
  time the airframe changes — ops and product people feel that monthly, and those are exactly
  the titles we target.

The honest counterpoint: it is the **slowest** sale. Sunk tooling, engineering pride, a fixed
bill of materials. If `fit_score` meant "likely to reply within 90 days," this weighting would
be wrong. It currently means "worth pursuing," and it is used for both. **Deciding which of
those two things the score is** is worth more than moving any individual number, and it is
still open.

What the live data actually showed (2026-08-11, nine companies scored under this rubric): the
problem was not the weight, it was the application. Three companies scored 0/20 while their
own evidence field said things like *"ships in an SKB Travel Case"* — a named competitor,
worth 13-16 — or described backpack carry, worth 8-12. The judge was reading "no *rugged* case
mentioned" as "no evidence," which is precisely what the bottom band is not for.

Two real rubric bugs were found and fixed the same day:

- **Overlapping bands.** In-house was 17-20 and named competitor 14-17, so a 17 satisfied
  both. The two highest-value verdicts were indistinguishable at their shared edge.
- **A dead zone.** Bands ran 0-4 then jumped straight to 10-13. Nothing covered 5-9, so a
  mid-strength verdict had no legal band and either rounded up to 10 or fell to 4 — and 4 is
  the "no evidence" band, which is exactly what it was not.

Now: **17-20 / 13-16 / 8-12 / 0-7**, partitioning 0-20 with no overlap and no gap, and the
0-7 bottom matches what the other criteria already use.

---

## 7. Security

An autonomous AI pentest (Strix 1.5.2) ran against this repo on 2026-08-10 and found two
MEDIUM issues, both confirmed with working proof-of-concept exploits rather than static
guesses. Both are now fixed and merged to `main`, covered by 18 regression tests that were
written first and watched fail.

**Path traversal in the run name (CWE-23).** The run name is operator input, and it was
pasted straight into a filesystem path. A brief with `run: ../../../tmp/pwn` redirected every
stage that saves state — the frozen brief, the prospect state, the output CSVs — to a
directory of its choosing, silently and with no error. Fixed by allowlisting the name
(`gtm/brief.py::safe_run_name`) and then separately verifying the resolved path still sits
under `data/runs`. Both checks are needed: several commands take the run name from the
command line and never build a `Brief` at all.

**SSRF in scrape targets (CWE-918).** Scrape targets are untrusted — the URL list is whatever
was pasted in, and discovered websites are whatever a search API returned. The only gate in
front of them asked whether the hostname existed in DNS. So `http://127.0.0.1:8080/`, an
internal hostname, and a public domain pointing at a cloud metadata address all passed, and
the fetched content ended up in the run's markdown and in the extraction prompt. Fixed by the
new `gtm/net.py`, which checks the resolved **address** rather than the name — blocking the
string "localhost" is theatre, since any name is free to answer 127.0.0.1.

**Known limit, accepted:** the check resolves the name once and the scraper connects
separately, so a DNS rebind between those two moments is theoretically possible. Closing that
means pinning the connection inside all four scrapers. Not worth it for a local pipeline;
revisit if this ever accepts URLs from strangers.

The full report is at `security/strix-2026-08-10.md`. That file and `strix_runs/` are
**gitignored on purpose** — a document naming live vulnerabilities and their exploit shapes
stays local.

---

## 8. Where the numbers stand

- **7,263 lines** of Python across 28 modules
- **862 tests**, all offline against recorded fixtures, all passing
- **66 company records** across 50 runs — 25 priority, 10 keep, 20 drop, 4 error
- **Fit scores:** median 68, range 0-91
- **Total spend:** $0.085 OpenAI, 352 Serper credits, 202 email-provider credits, $0 on
  Sheets and HubSpot

---

## 9. What would make this more than a demo

Roughly in order of payoff.

1. **Pin dependency versions and add a lockfile.** `requirements.txt` is bare package names,
   so a vulnerability scan finds zero language files and reports clean — which means "nothing
   was checked," not "nothing is wrong." This is the easiest real win available.
2. **Guard the content-to-LLM path.** Scraped page text flows into the extraction, enrichment
   and drafting prompts with nothing in between. A hostile page could try to steer three
   stages at once. No confirmed exploit, but it is the largest unexamined surface here.
3. **Finish the community-signals measurement.** The instrumentation is done — the trace now
   reports how many candidates the model returned versus how many survived filtering — but
   the measurement itself has never been run against a fixed pool. Passers still sometimes
   ship with an empty pain section, which removes the strongest paragraph from the email.
4. **Concurrency.** Everything is sequential, one company at a time, no retry queue, no
   rate-limit backoff. 66 companies across 50 runs is demo pace. Async scraping and batched
   extraction is the unlock for real volume.
5. **Close the loop after send.** The pipeline ends at the push. No sequencing, no reply
   capture, nothing feeding a booked meeting back into the scoring. That gap is the whole
   difference between a lead-list generator and a GTM system.
6. **Build a calibration set.** Scores are judged but never validated. Nothing measures
   whether an 85 converts better than a 65. Twenty hand-labelled companies would turn the
   rubric from a considered opinion into something measurable.
7. **Decide what `fit_score` means** — near-term reply likelihood, or account value. It is
   currently used as both, and those two want different weights. See §6.
8. **Budget for volume.** Free tiers are the real ceiling: contacts plus enrichment costs 5+
   Serper credits per company, and 352 are already spent. Past roughly 200 companies a month,
   paid search or a Clay-style provider waterfall becomes necessary.

---

## 10. Two rules that are easy to break and expensive to break

**Never code an external API from memory.** Fetch the official docs first and save a
reference at `docs/tools/<name>.md` — install, auth, the exact call we make, free-tier caps,
gotchas. Read that file before touching the integration. There are 15 of them in there now.

**No skill or script re-implements a pipeline stage.** See §3. This rule has already been
broken once and cost two deleted skills and a silent quality regression that nobody caught
until the files were compared side by side.
