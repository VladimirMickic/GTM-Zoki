# GTM Helper Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-command test harness plus real resilience and operational control to the
demo pipeline — full-auto smoke run, multi-provider email verification, working fallback
scrapers, frozen briefs, structured checkpoint/exit-code/dry-run control, GitHub Issues as a
pipeline state machine, and (last) a HubSpot sink.

**Architecture:** Seven vertical slices, each landed + tested + live-smoked + committed before the
next. Every new external API gets a `docs/tools/<name>.md` reference fetched and saved **before**
any code touches it (project tool rule). Slice order is dependency-driven (see below). All work
is free-tier bounded.

**Tech Stack:** Python 3.12, Pydantic, pytest, requests, crawl4ai, openai (gpt-4o-mini). New:
Firecrawl + ScrapeGraphAI (fallback scrapers via API), Apify (fallback scraper via `apify-cli`
subprocess), MyEmailVerifier + Abstract (email verify), Prospeo (email find), GitHub REST API
(PAT), HubSpot CRM API (private-app token).

## Global Constraints

- **Free tier only** — no paid calls. Caps per provider documented in each slice.
- **TDD mandatory** — RED (watch it fail) → GREEN → refactor for every code change, prompt or
  logic (project convention, no exceptions).
- **Vertical slices** — one slice fully built + tested + live-smoked before the next.
- **Tool rule** — before coding any new external API, fetch official docs → `docs/tools/<name>.md`
  (install, auth, exact call for our use, free-tier caps, gotchas); read it before coding.
- **Log & skip** — a provider/stage failure logs to `data/errors.log` and falls through; never
  aborts the whole run.
- **Secret hygiene** — new keys go in `.env` (gitignored); `secret_guard.py` blocks reading it;
  Claude never reads/echoes keys. The user adds each key by hand.
- **Optional-provider pattern** — any provider whose key is absent stays a no-op / `_not_configured`
  stub and is skipped; the pipeline never raises at import for a missing optional key.
- **Git identity** — commits/pushes as `Vladimir Mickic <mickicvladimir98@gmail.com>`, no
  `Co-Authored-By` trailer. `git push` is run by the user (harness blocks it for the agent).
- **Schema is the contract** — cross-stage data changes go through `gtm/schema.py` (Pydantic).

## Decisions locked (from the grilling session, 2026-07-18)

1. **Phase goal:** harden real gaps first. Order: test harness → email → scrapers → ops trio
   (brief-freeze → checkpoints → GitHub Issues) → HubSpot last.
2. **Email fallback is a resilience play, not a hit-rate play.** Free pattern-matching already
   hits 14/15; this will not move that number — it survives Hunter being down or capped. Say so.
3. **Verify chain order: MyEmailVerifier → Abstract → Hunter.** Spend the generous free tier
   (MEV 100/day) first, preserve Hunter's 50/mo as last resort. Keys for MEV + Abstract are in
   `.env` already. MEV and Abstract are **verifiers only** (they do not find addresses).
4. **Finder chain: Prospeo → Hunter.** Prospeo first (75/mo free), Hunter second. Prospeo's
   `/email-finder` is deprecated — use the current `/enrich-person` endpoint (Task 2.0 confirms
   the live shape). ZeroBounce dropped.
5. **Scraper chain: crawl4ai → Firecrawl → ScrapeGraphAI → Apify.** Four total; each fallback is
   optional (stub without key). **Apify via the `apify-cli`, NOT the MCP server** — shell out to
   `apify call`. Apify is the anti-bot / social last resort: it can scrape LinkedIn + social where
   the others are blocked, so **LinkedIn/social hosts route straight to Apify** (deterministic
   rule in `scrape()`, not a fallthrough).
6. **No scraper-selection skill.** Scraper choice is deterministic and runs inside `scrape()` at
   the CLI layer — a skill loads into Claude's context but would never fire there. Instead: a
   code routing rule (social → Apify) + a `docs/tools/scrapers.md` "when to use which" reference
   table for humans and in-loop Claude. Lighter, and it actually executes.
7. **Smoke test: full-auto on 1 URL, always live.** Hits real scrape/extract/enrich/email APIs
   every run (user wants a true end-to-end test — accept the quota cost). The two human-judgment
   stages (fit, signals) are auto-filled by **gpt-4o-mini** reusing the existing prompts — a cheap
   stand-in, NOT the real Claude-orchestrator judgment, so smoke proves plumbing, not score
   quality. Sink writes (Sheet/HubSpot/GitHub) are OFF unless `--live` is passed.

---

## Missing from the ORIGINAL plan (answered for the user, tracked here)

From `docs/notes.md` + `docs/PLAN.md`, independent of the reference screenshots:
1. **HubSpot CRM push** — the brain dump's original sink. Shipped Google Sheets instead;
   deferred, never built. → Slice 7 here.
2. **Working fallback scrapers** — notes named crawl4ai + ScrapeGraphAI + Scrapling; only
   crawl4ai runs. → Slice 3 (Scrapling swapped for Apify per decision 5).
3. **Cold-email copy stage** — have `outreach_angle` (a line), not drafted emails. Still deferred
   (out of this plan; `cold-email` skill exists, unused).
4. **segment + QA stages** — PLAN "later" bucket, not started (out of this plan).

---

## Slice 1 — Full-auto smoke harness (build first: validates every later slice)

New `smoke <url>` subcommand runs the whole pipeline on one company unattended: discover-skip →
scrape+extract → auto-fit (gpt-4o-mini) → enrich+contacts → email waterfall → auto-signals
(gpt-4o-mini) → CSV. External research/email APIs run **live**; sink writes are skipped unless
`--live`. Reuses existing stage functions — no duplicate pipeline logic.

**Files:**
- Create: `gtm/smoke.py` — `auto_fit()`, `auto_signals()` (gpt-4o-mini judgment), `run_smoke()`
- Modify: `gtm/run.py` — add `case ["smoke", url]` / `["smoke", url, "--live"]` to `main()`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: `auto_fit(icp: str, company: str, ex: DroneExtraction, *, client=None) -> FitResult`
  — gpt-4o-mini answers `build_fit_prompt`, parsed into `FitResult`.
- Produces: `auto_signals(p: Prospect, *, client=None) -> dict` — gpt-4o-mini answers
  `build_signal_prompt`, parsed into `{"buying_signals": [...], "outreach_angle": "..."}`.
- Produces: `run_smoke(url: str, *, live: bool = False, run: str = "smoke") -> Prospect` —
  orchestrates one company end-to-end, returns the final `Prospect`.
- Consumes: `process_company`, `emails_for_prospect`, `run_dir`, `save_state` (run.py);
  `apply_fit`, `build_fit_prompt`, `FitResult`, `merge_signals` (fit.py); `enrich`,
  `build_signal_prompt` (enrich.py); `find_contacts`, `top_contact_fields` (contacts.py);
  `write_csv`, `push_to_sheet` (output.py).

### Task 1.1: auto_fit via gpt-4o-mini

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
from gtm.extract import DroneExtraction
from gtm.fit import FitResult
from gtm.smoke import auto_fit

class _FakeParse:
    def __init__(self, payload): self._p = payload
    class _Msg:
        def __init__(self, parsed): self.parsed = parsed; self.refusal = None
    def __call__(self, **kw):
        class C:
            class ch:
                message = None
                finish_reason = "stop"
            usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
            choices = [ch]
        C.choices[0].message = _FakeParse._Msg(self._p)
        return C

def test_auto_fit_parses_gpt_result():
    fake = FitResult(fit_score=72, fit_reason="x 12/15 — ok", best_case_line="AV-Field")
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"parse": _FakeParse(fake)})()})()})()
    r = auto_fit("ICP", "Teal", DroneExtraction(company_description="d"), client=client)
    assert r.fit_score == 72 and r.best_case_line == "AV-Field"
```

- [ ] **Step 2: Run test to verify it fails** — `pytest tests/test_smoke.py::test_auto_fit_parses_gpt_result -v` → FAIL (module missing).
- [ ] **Step 3: Write minimal implementation** — in `gtm/smoke.py`, mirror `extract.extract()`'s
  client pattern: build the OpenAI client if `client is None`, call
  `client.chat.completions.parse(model="gpt-4o-mini", messages=[{"role":"user","content":build_fit_prompt(icp,company,ex)}], response_format=FitResult)`, return `choices[0].message.parsed`;
  raise `RuntimeError` if `parsed is None`.
- [ ] **Step 4: Run test to verify it passes** — `pytest tests/test_smoke.py::test_auto_fit_parses_gpt_result -v` → PASS.
- [ ] **Step 5: Commit** — `git add gtm/smoke.py tests/test_smoke.py && git commit -m "feat: smoke auto_fit via gpt-4o-mini"`

### Task 1.2: auto_signals via gpt-4o-mini

- [ ] **Step 1: Write the failing test** — a `test_auto_signals_parses` mirroring 1.1 but with a
  small `SignalOut(BaseModel)` (`buying_signals: list[str]`, `outreach_angle: str`) as
  `response_format`; assert the returned dict has both keys.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `auto_signals(p, *, client=None) -> dict`: define a local
  `SignalOut` pydantic model, call `.parse` with `build_signal_prompt(p)`, return
  `parsed.model_dump()`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: smoke auto_signals via gpt-4o-mini"`

### Task 1.3: run_smoke orchestration (writes gated on --live)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py (additions)
from gtm.smoke import run_smoke

def test_run_smoke_skips_sink_when_not_live(monkeypatch, tmp_path):
    calls = {"push": 0}
    monkeypatch.setattr("gtm.smoke.push_to_sheet", lambda *a, **k: calls.__setitem__("push", calls["push"] + 1))
    # stub every live stage with a fast fake
    monkeypatch.setattr("gtm.smoke.process_company", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.enrich", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.find_contacts", lambda c: [])
    monkeypatch.setattr("gtm.smoke.emails_for_prospect", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.auto_fit", lambda *a, **k: __import__("gtm.fit", fromlist=["FitResult"]).FitResult(fit_score=80, fit_reason="r", best_case_line="AV-Field"))
    monkeypatch.setattr("gtm.smoke.auto_signals", lambda p, **k: {"buying_signals": [], "outreach_angle": "a"})
    monkeypatch.setattr("gtm.smoke.run_dir", lambda run: tmp_path)
    p = run_smoke("https://tealdrones.com", live=False)
    assert p.status == "priority" and calls["push"] == 0  # sink NOT called
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `run_smoke(url, *, live=False, run="smoke")`:
  build one `Prospect(company=company_from_url(url), website=url, source="smoke")`;
  `process_company(p)`; if `p.status not in ("drop","error")`: `apply_fit(p, auto_fit(ICP.read_text(), p.company, <DroneExtraction from p>))`;
  if `p.status in ("priority","keep")`: `enrich(p)`, contacts via `find_contacts`/`top_contact_fields`,
  `emails_for_prospect(p)`, then `s = auto_signals(p); p.buying_signals = s["buying_signals"]; p.outreach_angle = s["outreach_angle"]`;
  `save_state([p], run_dir(run))`; `write_csv([p], run_dir(run)/"prospects.csv")`;
  if `live`: `push_to_sheet([p])`. Print a per-stage `[smoke]` line each step.
- [ ] **Step 4: Run → PASS + full suite `pytest -q` green.**
- [ ] **Step 5: Commit** — `git commit -m "feat: run_smoke one-URL end-to-end, sink gated on --live"`

### Task 1.4: CLI wiring + live smoke

- [ ] **Step 1:** Add to `run.py::main()`: `case ["smoke", url]: from gtm.smoke import run_smoke; run_smoke(url)` and `case ["smoke", url, "--live"]: run_smoke(url, live=True)`. Update the module docstring usage block.
- [ ] **Step 2: Live run** (always-live external APIs): `python -m gtm.run smoke https://tealdrones.com` — expect all stages print, a `data/runs/smoke/prospects.csv` written, NO sheet row added.
- [ ] **Step 3:** Confirm the sheet was untouched (no `--live`). Then optionally `--live` once and confirm one row appends.
- [ ] **Step 4:** `superpowers:verification-before-completion` before calling the slice done; log any API surprise to `data/feedback.jsonl`.
- [ ] **Step 5: Commit** — `git commit -m "feat: gtm.run smoke CLI subcommand"`; ask user to `git push`.

---

## Slice 2 — Email provider fallback (verify chain MEV → Abstract → Hunter)

Generalize `gtm/emails.py` from two injected functions to an ordered list of provider objects,
each optionally offering `verify(email)` and/or `find(first, last, domain)`. The waterfall asks
each capability's chain in order until one answers; a quota/error skips to the next provider.
Tier logic (pattern → find → AI scan) and `EmailResult`/`_VERDICTS` are unchanged.

**Files:**
- Create: `gtm/email_providers.py`
- Modify: `gtm/emails.py` (`waterfall()` takes `providers: list[EmailProvider]`)
- Create: `docs/tools/myemailverifier.md`, `docs/tools/abstract.md`, `docs/tools/prospeo.md`
- Test: `tests/test_email_providers.py`, extend `tests/test_emails.py`

**Interfaces:**
- Produces: `class EmailProvider(Protocol)`: `name: str`; `verify(email) -> dict | None`
  (`{"status": <hunter-style>, "score": int}` or `None` = "not my job / quota hit");
  `find(first, last, domain) -> dict | None` (`{"email": str, "score": int}` or `None`).
  Adapters normalize each vendor's JSON into this shape so `verdict()`/`_VERDICTS` in `emails.py`
  stay unchanged.
- Produces: `default_providers() -> list[EmailProvider]` — ordered
  `[MyEmailVerifier, Abstract, Prospeo, Hunter]`, each included only if its env key is set. One
  ordered list serves both chains: verify walk skips find-only providers → MEV → Abstract →
  Hunter; find walk skips verify-only providers → Prospeo → Hunter.
- Consumes (unchanged): `EmailResult`, `verdict()`, `candidate_patterns()`, `_ai_hunt()` (emails.py).

### Task 2.0: Save tool references (blocks coding — tool rule)

- [ ] **Step 1:** Fetch MyEmailVerifier API docs → `docs/tools/myemailverifier.md`: base URL,
  single-email verify endpoint, auth, `status` values → verdict map (`ok`→`valid`,
  `invalid`→`invalid`, `catch-all`→`accept_all`, `unknown`→`unknown`), free tier (100/day, no CC),
  429 handling.
- [ ] **Step 2:** Fetch Abstract email-validation docs → `docs/tools/abstract.md`: endpoint
  `https://emailvalidation.abstractapi.com/v1/`, `api_key` query param, fields
  (`deliverability` DELIVERABLE/UNDELIVERABLE/UNKNOWN → valid/invalid/unknown, `is_catchall`→
  accept_all, `quality_score`), free tier (100/mo, 3 req/s).
- [ ] **Step 3:** Fetch Prospeo docs → `docs/tools/prospeo.md`: **current `/enrich-person`
  endpoint** (the old `POST https://api.prospeo.io/email-finder` is deprecated), Bearer/`X-KEY`
  auth, `first_name`+`last_name`+`company`(domain) inputs, response email + verification status,
  free tier (75/mo). Note the deprecation + the migrated endpoint explicitly.
- [ ] **Step 4: Commit** — `git add docs/tools/{myemailverifier,abstract,prospeo}.md && git commit -m "docs: email-provider API references (tool rule)"`

### Task 2.1: Provider protocol + Hunter adapter

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_providers.py
from gtm.email_providers import HunterProvider

def test_hunter_verify_normalizes(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"data": {"status": "valid", "score": 97}}
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    assert HunterProvider().verify("a@b.com") == {"status": "valid", "score": 97}

def test_hunter_verify_none_on_quota(monkeypatch):
    class R:
        status_code = 429
        def raise_for_status(self): raise AssertionError("should not raise")
        def json(self): return {}
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    assert HunterProvider().verify("a@b.com") is None
```

- [ ] **Step 2: Run → FAIL** (module missing).
- [ ] **Step 3: Implement** `gtm/email_providers.py`: a `Protocol`, and `HunterProvider` moving the
  `_hunter_get`/`HUNTER_*_URL` logic here. `verify` → `{"status","score"}`; return `None` on
  status 404/429/451 (miss/quota). `find` → `{"email","score"}` or `None`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: EmailProvider protocol + Hunter adapter"`

### Task 2.2: MyEmailVerifier + Abstract verify adapters

- [ ] **Step 1: Write failing tests** — one per adapter: mock `requests.get`, assert vendor JSON →
  `{"status": "valid", "score": N}` per the verdict maps in Task 2.0; a 429/quota → `None`;
  `find()` returns `None` (verify-only).
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `MyEmailVerifierProvider`, `AbstractProvider` (read the two tool docs
  first). Env keys: `MYEMAILVERIFIER_API_KEY`, `ABSTRACT_API_KEY`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: MyEmailVerifier + Abstract verify adapters"`

### Task 2.3: Prospeo find adapter

- [ ] **Step 1: Write failing test** — mock `requests.post` to `/enrich-person`; response with an
  email → `{"email":"j@x.com","score":<int>}`; miss/quota → `None`; `verify()` returns `None`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `ProspeoProvider` (env `PROSPEO_API_KEY`; find-only; POST
  `/enrich-person` with Bearer auth per `docs/tools/prospeo.md`). Read the tool doc first.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `git commit -m "feat: Prospeo email-finder adapter"`

### Task 2.4: default_providers() + waterfall() over chains

- [ ] **Step 1: Write failing tests**

```python
# tests/test_emails.py (additions)
from gtm.emails import waterfall

class FakeProvider:
    def __init__(self, name, verify_map=None, find_map=None):
        self.name = name; self._v = verify_map or {}; self._f = find_map or {}
    def verify(self, email): return self._v.get(email)
    def find(self, first, last, domain): return self._f.get((first, last, domain))

def test_waterfall_second_verifier_when_first_quota():
    p1 = FakeProvider("mev")  # returns None => quota/skip
    p2 = FakeProvider("hunter", verify_map={"jane.doe@x.com": {"status": "valid", "score": 90}})
    r = waterfall("Jane Doe", "x.com", providers=[p1, p2])
    assert r.email == "jane.doe@x.com" and r.tier == "pattern" and r.status == "verified"

def test_waterfall_find_chain_when_patterns_miss():
    p1 = FakeProvider("mev")
    p2 = FakeProvider("hunter",
                      find_map={("jane", "doe", "x.com"): {"email": "j.d@x.com", "score": 80}},
                      verify_map={"j.d@x.com": {"status": "valid", "score": 80}})
    r = waterfall("Jane Doe", "x.com", providers=[p1, p2])
    assert r.email == "j.d@x.com" and r.tier == "hunter"
```

- [ ] **Step 2: Run → FAIL** (`waterfall` has no `providers=`).
- [ ] **Step 3: Implement** — `waterfall(name, domain, *, providers=None, search=serper_search)`:
  `providers = providers or default_providers()`; `_verify_chain(email)` = first non-`None`
  verify; `_find_chain(...)` = first non-`None` find; tier 1 pattern loop verified via
  `_verify_chain`; tier 2 via `_find_chain` then verify; tier 3 `_ai_hunt` unchanged. Add
  `default_providers()` ordered `[MEV, Abstract, Prospeo, Hunter]`, key-gated (verify walk yields
  MEV then Abstract then Hunter; find walk yields Prospeo then Hunter).
- [ ] **Step 4: Run → full suite `pytest -q` green.**
- [ ] **Step 5: Commit** — `git commit -m "feat: waterfall over ordered provider chains, quota fallthrough"`

### Task 2.5: Live smoke (run.py needs no change — waterfall picks default_providers)

- [ ] **Step 1:** Verify keys present (never print): `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print({k: bool(os.environ.get(k)) for k in ('HUNTER_API_KEY','MYEMAILVERIFIER_API_KEY','ABSTRACT_API_KEY')})"`
- [ ] **Step 2:** `python -m gtm.run emails discover-3` (Paladin, prior 2/3 miss) — confirm the
  chain runs; MEV should now front the verify calls. Expect same-or-better fill, no crash.
- [ ] **Step 3:** Log to `data/feedback.jsonl` which provider answered; re-push sheet only if
  output changed (confirm via AskUserQuestion). Run `superpowers:verification-before-completion`.
- [ ] **Step 4: Commit** any fixes; ask user to `git push`.

---

## Slice 3 — Fallback scrapers (crawl4ai → Firecrawl → ScrapeGraphAI → Apify)

Infra already exists in `gtm/scrape.py` (`FALLBACK_ORDER`, `SCRAPERS` registry, `_not_configured`
stubs). Work = research + real adapters replacing three stubs, each `(url) -> markdown str | raise
ScrapeError`. Update `FALLBACK_ORDER` to `["crawl4ai", "firecrawl", "scrapegraphai", "apify"]`.
Plus a deterministic **social-host routing rule**: LinkedIn/Twitter/Instagram/Facebook hosts go
straight to Apify (the others cannot render them), instead of walking the chain from crawl4ai.

**Files:** Modify `gtm/scrape.py`; Create `docs/tools/firecrawl.md`, `docs/tools/scrapegraphai.md`,
`docs/tools/apify.md`, `docs/tools/scrapers.md` (the "when to use which" table — replaces the idea
of a scraper-selection skill); Test `tests/test_scrape.py` (extend).

### Task 3.0: Save tool references + selection table (blocks coding)
- [ ] Fetch + write `docs/tools/firecrawl.md` (scrape endpoint returning markdown, `Authorization: Bearer`, 500 trial credits, **confirm anti-bot/proxy support — this is what beats Cloudflare**).
- [ ] `docs/tools/scrapegraphai.md` (markdownify/scrape endpoint, API key, free tier, note it overlaps our S2 extraction so we only use its markdown).
- [ ] `docs/tools/apify.md` — **CLI, not MCP**: install (`curl -fsSL https://apify.com/install-cli.sh | bash`), `apify login` (token), run pattern `apify call apify/website-content-crawler -i <input.json> --output-dataset` (or `-o`), parse dataset JSON items' `markdown`/`text`; also note the LinkedIn/social actors; ~$5/mo free credits; anti-bot/proxy support. Reference: https://github.com/apify/apify-cli and https://docs.apify.com/cli/docs/reference.
- [ ] `docs/tools/scrapers.md` — the selection table: crawl4ai (default, free, local; general sites) → Firecrawl (managed, anti-bot; JS-heavy/Cloudflare) → ScrapeGraphAI (managed; last generic resort) → Apify (anti-bot + **social/LinkedIn**, CLI). Include the "social host → Apify directly" rule so in-loop Claude and humans know the routing.
- [ ] Commit: `git commit -m "docs: fallback-scraper references + selection table (tool rule)"`

### Task 3.1: Firecrawl adapter
- [ ] **Step 1:** Failing test — mock `requests.post`, Firecrawl JSON `{"data":{"markdown":"# ..."}}` → returned markdown string; no key → `ScrapeError` (via `_not_configured` behavior).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `scrape_firecrawl(url)` behind `FIRECRAWL_API_KEY`; register in `SCRAPERS`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: Firecrawl scraper adapter`.

### Task 3.2: ScrapeGraphAI adapter
- [ ] Failing test (mock the markdownify call → markdown); implement `scrape_scrapegraphai(url)`
  behind `SCRAPEGRAPHAI_API_KEY`; register; run → PASS; commit `feat: ScrapeGraphAI scraper adapter`.

### Task 3.3: Apify adapter (via apify-cli subprocess, not MCP)
- [ ] Failing test — mock `subprocess.run` returning a fake dataset JSON
  (`[{"markdown": "# ..."}]`); assert `scrape_apify(url)` shells out to `apify call
  apify/website-content-crawler` with a start-URL input and returns the joined `markdown`. When
  the `apify` binary is absent / not logged in → `ScrapeError` (stub behavior, like the others).
- [ ] Implement `scrape_apify(url)`: write a temp input JSON (`{"startUrls":[{"url":url}]}`), run
  `apify call apify/website-content-crawler -i <tmp> -o <tmp-out>` (or `--output-dataset`), read
  the dataset JSON, join items' `markdown`/`text`. Register replacing `_not_configured("apify")`.
  Gate on `shutil.which("apify")` so no binary → clean `ScrapeError`. Read `docs/tools/apify.md` first.
- [ ] Run → PASS; commit `feat: Apify scraper adapter via apify-cli`.

### Task 3.4: Social-host routing rule
- [ ] Failing test — `scrape("https://www.linkedin.com/company/teal")` (with a fake registry)
  calls the Apify scraper first, NOT crawl4ai. Assert routing by host, not fallthrough.
- [ ] Implement in `scrape()`: if the host matches `{linkedin.com, twitter.com, x.com,
  instagram.com, facebook.com}`, prepend `apify` to the chain (or set it as `preferred`). Run → PASS;
  commit `feat: route social/LinkedIn hosts straight to Apify`.

### Task 3.5: Live smoke — the real Cloudflare case
- [ ] Re-run the Red Cat URL (the one Cloudflare block in `data/errors.log`) through the full
  chain: `python -m gtm.run smoke <redcat-url>`. Confirm a fallback (Firecrawl or Apify with
  anti-bot) returns markdown where crawl4ai failed. The `scrape()` loop already walks the chain —
  no orchestration change beyond Task 3.4. Log the result to `data/feedback.jsonl`; run
  `superpowers:verification-before-completion`; ask user to push.

---

## Slice 4 — Brief immutability (freeze at init)

Freeze the brief at run start into `brief.lock.json`; later stages load the lock, not the editable
`brief.md`. Prerequisite for checkpoint/resume (Slice 5) so resume trusts a frozen brief.

**Files:** Modify `gtm/brief.py` (add `freeze_brief`, `load_frozen`), `gtm/run.py` (`cmd_start`
freezes; later stages that need brief fields load the lock). Test: `tests/test_brief.py` (extend).

### Task 4.1: freeze_brief (idempotent, tamper-evident)
- [ ] **Step 1:** Failing test — `freeze_brief(brief, tmp_path)` writes `brief.lock.json` ==
  `brief.model_dump()`; calling again with the same brief is a no-op; calling with a
  different-content brief raises `ValueError("brief already frozen")`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement `freeze_brief(brief, rdir) -> Path` and `load_frozen(rdir) -> Brief`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: freeze/load brief lock`.

### Task 4.2: cmd_start freezes; stages read the lock
- [ ] **Step 1:** Failing test — after `cmd_start` writes the lock, editing `brief.md` and calling
  `load_frozen(run_dir)` still returns the original values.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** `cmd_start` calls `freeze_brief(brief, run_dir(brief.run))` after `load_brief`;
  `smoke` writes a lock too. Any later stage needing brief fields uses `load_frozen`.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: freeze brief at run init, stages read the lock`.

### Task 4.3: Live smoke
- [ ] Start a run, edit `brief.md` `max_companies`, run a later stage, confirm frozen value wins;
  log; commit; push.

---

## Slice 5 — Checkpoints / exit codes / dry-run

**Files:** Create `gtm/control.py`; modify `gtm/run.py` (`main()` maps exceptions → exit codes;
stages raise `CheckpointPending`; honor `--dry-run`). Test: `tests/test_control.py`.

**Exit-code taxonomy:** `0` success · `5` checkpoint pending (human edit → resume) · `6` standards
failed (invalid brief/config) · `1` unexpected error.

### Task 5.1: ExitCode + CheckpointPending
- [ ] Failing test asserting `ExitCode.SUCCESS==0/CHECKPOINT==5/STANDARDS==6/ERROR==1` and that
  `CheckpointPending(file=..., action=..., resume=...)` carries those attributes.
- [ ] Implement `IntEnum` + exception in `gtm/control.py`; run → PASS; commit.

### Task 5.2: --dry-run write guard (reuse smoke's sink gate)
- [ ] Failing test — a `--dry-run` start injects fakes for `push_to_sheet` (+ future GitHub/HubSpot)
  and asserts they are NOT called, while scrape/extract still run. Implement a single
  `writes_enabled(live: bool)` guard in `gtm/control.py` reused by smoke and the normal flow (DRY).
- [ ] Run → PASS; commit `feat: --dry-run write guard`.

### Task 5.3: fit + signals become explicit checkpoints
- [ ] Failing test — a start with judgment pending exits `5` and prints the file to edit + resume
  command; feeding the JSON answer and re-running resumes cleanly.
- [ ] Implement: `cmd_start` raises `CheckpointPending(file="fit.json", action="score prospects",
  resume="python -m gtm.run fit <run> fit.json")` after printing prompts; `main()` catches it,
  prints, `sys.exit(5)`. Same for signals. Run → PASS; commit.

### Task 5.4: Live smoke
- [ ] Full `--dry-run` run (no live writes), then a real run exiting `5` at the fit checkpoint and
  resuming; log; commit; push.

---

## Slice 6 — GitHub Issues state machine

One Issue per run; labels track lifecycle; checkpoint pauses post as comments. No `gh` CLI → GitHub
REST via `requests` + PAT (`GITHUB_TOKEN`). Repo `VladimirMickic/GTM-Zoki`. Best-effort (log & skip).

**Files:** Create `gtm/github_state.py`, `docs/tools/github-issues.md`; modify `gtm/run.py` (stage
entry/exit/checkpoint hooks). Test: `tests/test_github_state.py`.

### Task 6.0: docs/tools/github-issues.md
- [ ] REST endpoints: create issue, replace labels (PATCH), create comment; PAT scope (`repo` or
  fine-grained issues:write); rate limits. Commit.

### Task 6.1: github_state adapter (mocked requests)
- [ ] Failing tests — `open_run_issue(run)` is idempotent via a `.github_issue` sidecar in the run
  dir (returns the stored number, no duplicate create); `set_stage_labels(issue, stage, status)`
  PATCHes exactly the 3 label dimensions (`stage:*`, `status:*`, `run:*`);
  `post_checkpoint_comment(issue, file, action, resume)` posts one comment. All failures log & skip.
- [ ] Implement; run → PASS; commit.

### Task 6.2: wire into run.py stage lifecycle
- [ ] Failing test — a stage transition calls `set_stage_labels` with `status:running` on entry and
  `status:complete` on exit (inject a fake `github_state`, assert calls). A `CheckpointPending`
  sets `status:checkpoint` + posts the resume comment; an exception sets `status:failed`.
- [ ] Implement thin hooks in each `cmd_*`; label vocabulary derived from stage names, validated
  once at run start (pre-flight). Run → PASS; commit.

### Task 6.3: Live smoke
- [ ] One end-to-end run against the real repo: issue opens, labels transition, checkpoint posts a
  comment; re-run confirms idempotency (no duplicate issue). Log; commit; push.

---

## Slice 7 — HubSpot sink (your original #1 gap; last per decision)

Push priority/keep prospects to HubSpot CRM (free tier, private-app token). Runs alongside the
Sheet, not instead of it. Best-effort; gated behind `--live` write guard (Slice 5) + token.

**Files:** Create `gtm/hubspot.py`, `docs/tools/hubspot.md`; modify `gtm/run.py` (`cmd_output`
also upserts to HubSpot when `HUBSPOT_SERVICE_KEY` present + writes enabled). Test: `tests/test_hubspot.py`.

### Task 7.0: docs/tools/hubspot.md
- [ ] CRM v3 companies+contacts upsert endpoints, private-app token auth, free-tier limits, the
  properties we map (company→company object; contact_name/title/linkedin/email→contact object,
  associated to the company). Commit.

### Task 7.1: field mapping + upsert (mocked requests)
- [ ] Failing test — `push_to_hubspot([prospect])` maps a `Prospect` to a company payload +
  contact payloads (split `contact_name`/`contact_emails` parallel), calls the upsert endpoints
  (mock `requests`), and returns a count; missing token → no-op returning 0. Idempotent via a
  domain-based dedupe/search-before-create.
- [ ] Implement; run → PASS; commit.

### Task 7.2: wire into cmd_output + live smoke
- [ ] `cmd_output` calls `push_to_hubspot(prospects)` when `HUBSPOT_SERVICE_KEY` set and writes enabled.
  Test the gate. Live: push one run's prospects, confirm the company + contacts appear in HubSpot.
  Log; commit; push.

---

## Self-review notes

- **Spec coverage:** test harness (S1), email fallback (S2), scrapers incl. Apify (S3), brief
  freeze (S4), checkpoints/exit-codes/dry-run (S5), GitHub Issues (S6), HubSpot (S7) — all
  grilling decisions covered. Verify order MEV→Abstract→Hunter is set in `default_providers()`
  (Task 2.4). Smoke is always-live external with gpt-4o-mini judgment + sink gated on `--live`
  (S1). Finder chain Prospeo then Hunter (Task 2.3/2.4). Scraper selection is code + a
  `docs/tools/scrapers.md` table, not a skill (S3); social/LinkedIn routes straight to Apify.
- **Type consistency:** `EmailProvider.verify → {"status","score"}|None`, `.find →
  {"email","score"}|None` used identically across Tasks 2.1–2.4; `EmailResult`/`verdict()`
  unchanged. `CheckpointPending(file, action, resume)` defined in 5.1, consumed identically in
  5.3 and 6.2. `writes_enabled`/sink-gate is one mechanism shared by S1 and S5 (DRY).
- **Ordering/deps:** S1 first (tests everything after). S4 before S5 (resume needs frozen brief).
  S5 before S6 (issues mirror checkpoint state). S7 last (user's explicit "HubSpot later").
- **Keys the user must add per slice:** S2 has MEV+Abstract; add `PROSPEO_API_KEY` for the finder
  fallback; S3 `FIRECRAWL_API_KEY`, `SCRAPEGRAPHAI_API_KEY`, plus `apify login` (token) for the
  Apify CLI (each optional/stubbed without); S6 `GITHUB_TOKEN`; S7 `HUBSPOT_SERVICE_KEY`.
- **Deferred, not in this plan:** cold-email drafting, segment/QA stages,
  Supabase/Trigger.dev/Bison from the reference screenshots.
