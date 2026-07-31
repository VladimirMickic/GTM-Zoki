# Fit Reweight + Signal Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the Fit stage scoring points it has no evidence for, and make the Sheet's signal columns readable.

**Architecture:** Fit becomes two-phase. Claude scores 80 points from scrape data only (Physical 35, Field-deployed 25, Displacement 20), with a written band table per criterion whose bottom band is "no evidence" and an explicit ban on prior knowledge. Python then adds a deterministic Budget & procurement score (0-20) after the enrich stage, from fields that only exist post-enrich (`headcount`, `key_news`, `compliance_evidence`, `us_made_ndaa`). Separately, the news filter and the Sheet cell trimmer are repaired, and the dead community-signal path is instrumented before being changed.

**Tech Stack:** Python 3, Pydantic v2, pytest, Serper API, OpenAI `gpt-4o-mini`.

## Global Constraints

- Size remains the **only** hard disqualifier (`company/ICP.md`, locked 2026-07-28). Nothing in this plan adds a new auto-reject.
- Geography is **never** a scoring factor. Never award points for a US HQ, never deduct for a foreign one.
- Model routing per `CLAUDE.md`: `gpt-4o-mini` for bulk extraction, Claude for judgment. **Budget scoring adds zero LLM calls** — it is pure Python over already-fetched fields.
- Tier bands stay as written in `company/ICP.md`: `>=70` → `priority`, `40-69` → `keep`, `<40` → `drop`.
- Full untrimmed detail always stays in `data/runs/<run>/prospects.json`. Only the CSV/Sheet is capped.
- Recency markers must remain EXACTLY `[stale]` / `[undated]` — `gtm/draft.py::bad_markers` rejects anything else.
- Run the whole suite (`python -m pytest -q`, 703 tests passing at plan time) before each commit, not just the new test.
- No `cd` prefix in Bash commands; the tool already starts in the repo root.

## Recommended ship order

Parts C and D are small, independent, and produce the most visible demo improvement. Ship them first if time is short. Part A is the largest change and touches the most tests. Part B is a measurement task whose fix cannot be specified until the measurement lands.

| Part | What | Independent? |
|---|---|---|
| D | Sheet/CSV cell trimming bugs | yes — ship alone |
| C | News dedupe + recency | yes — ship alone |
| A | Fit rubric reweight, two-phase scoring | yes, but touches many tests |
| B | Community-signal instrumentation, then fix | measurement first |

---

## Part D — Sheet cell trimming

### Task D1: Trailing punctuation must not defeat source/marker protection

**Files:**
- Modify: `gtm/schema.py:59` (`_RECENCY_MARKER_RE`), `gtm/schema.py:86-99` (`_trim_keep_source`)
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_trim_keep_source(s: str, n: int) -> str` — unchanged signature, now tolerant of trailing punctuation after the source parenthetical and/or the recency marker.

**Background:** `data/runs/us-drone-20` shipped this cell to the Sheet:

```
Army awarded Anduril an $87M counter-drone task order, the first task order under a new
$20B Army contract vehicle — a real dollar award (not the vehicle's ceiling), evidence of…
```

The source `(breakingdefense.com, 2026-03)` was deleted because the raw signal ends `2026-03).` — with a full stop after the parenthesis. `_RECENCY_MARKER_RE` is anchored to `$` and `s.endswith(")")` is a literal last-character test, so both protections miss and the plain trimmer eats the evidence.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_schema.py
from gtm.schema import _trim_keep_source


def test_trim_keeps_source_when_a_full_stop_follows_the_parenthetical():
    signal = (
        "Army awarded Anduril an $87M counter-drone task order, the first task order "
        "under a new $20B Army contract vehicle — a real dollar award (not the "
        "vehicle's ceiling), evidence of an active, well-funded gov relationship "
        "(breakingdefense.com, 2026-03)."
    )
    out = _trim_keep_source(signal, 180)
    assert "breakingdefense.com, 2026-03" in out
    assert "…" in out


def test_trim_keeps_marker_when_a_full_stop_follows_it():
    signal = (
        "Air Force awarded Anduril a production contract for autonomous fighter "
        "aircraft (CCA — Collaborative Combat Aircraft), with the line capable of "
        "delivering up to 150 aircraft/year — signals major sustained gov demand and "
        "production scale-up (airandspaceforces.com, jpost.com) [undated]."
    )
    out = _trim_keep_source(signal, 180)
    assert out.rstrip().endswith("[undated]")
    assert "airandspaceforces.com" in out


def test_trim_still_handles_the_no_trailing_punctuation_case():
    signal = "Raised a $110M Series B to scale production (govconwire.com, 2026-02)"
    out = _trim_keep_source(signal, 180)
    assert out == signal  # short enough, untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_schema.py -k trim_keep -v`
Expected: first two FAIL — the source/marker are missing from the trimmed output.

- [ ] **Step 3: Implement**

Replace `gtm/schema.py:59` and the body of `_trim_keep_source`:

```python
# A trailing recency marker written by gtm/enrich.py's signal-dating logic:
# "[stale]", "[undated]". Short and bracketed, so it can't collide with prose.
# Trailing sentence punctuation is tolerated after it: Claude routinely writes
# "... (source) [undated]." and an anchored-to-$ match silently fell through to
# the plain trimmer, deleting source, date and marker together (us-drone-20).
_RECENCY_MARKER_RE = re.compile(r"\s*(\[[^\[\]]{1,20}\])\s*[.;,]?\s*$")
_SOURCE_TAIL_RE = re.compile(r"\s\(([^()]{1,120})\)\s*[.;,]?\s*$")


def _trim_keep_source(s: str, n: int) -> str:
    """Like _trim, but protects the two suffixes that carry the decision:
    the "(source, date)" parenthetical and a trailing "[stale]"/"[undated]" marker.
    Only the free text in front of them is trimmed.

    2026-07-24 fix: a cut source link is why community signals read as "no sources".
    2026-07-29 fix: the ")"-suffix test silently failed to fire on buying_signals,
    which end with the recency MARKER, not the parenthetical.
    2026-07-31 fix: both protections were last-character tests, so a trailing full
    stop ("... (breakingdefense.com, 2026-03).") defeated them and re-opened the
    exact same hole. Both are regexes now, and both tolerate trailing punctuation."""
    s = s.strip()
    marker = ""
    m = _RECENCY_MARKER_RE.search(s)
    if m:
        marker = " " + m.group(1)
        s = s[: m.start()].rstrip()
    source = ""
    m = _SOURCE_TAIL_RE.search(s)
    if m:
        source = f" ({m.group(1)})"
        s = s[: m.start()].rstrip()
    budget = max(n - len(source) - len(marker), 0)
    if len(s) > budget:
        s = s[:budget].rsplit(" ", 1)[0].rstrip() + "…"
    return s + source + marker
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: 703 + 3 passing, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add gtm/schema.py tests/test_schema.py
git commit -m "fix: trailing punctuation no longer deletes a signal's source and recency marker"
```

---

### Task D2: Keep the URL out of the news character budget

**Files:**
- Modify: `gtm/schema.py:46-48` (cap constants), and the long-list cell builder that calls `_trim_keep_source`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: `_trim_keep_source` from Task D1.
- Produces: `_trim_news_entry(s: str, n: int) -> str` — trims a `key_news` line's prose to `n` chars while preserving the full trailing `(https://...)` URL and any `[date: YYYY-MM]` stamp, neither of which is charged to `n`.

**Background:** `key_news` lines end with `(<url>)`, so D1's source protection preserves the URL — but charges its length to the 180-char budget. The breakingdefense URL is 103 characters, leaving 77 for the headline. The reader sees a headline fragment and a link.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py
from gtm.schema import _trim_news_entry


def test_news_entry_budget_excludes_the_url():
    line = (
        "Army awards Anduril counter-drone task order as first in new $20B contract "
        "vehicle — WASHINGTON — The Army-run counter-drone task force has selected "
        "Anduril's Lattice software as the command and control backbone in an $87 "
        "million award announced Friday "
        "(https://breakingdefense.com/2026/03/army-awards-anduril-counter-drone-task-"
        "order-as-first-in-new-20b-contract-vehicle/) [date: 2026-03]"
    )
    out = _trim_news_entry(line, 180)
    assert out.endswith("[date: 2026-03]")
    assert "breakingdefense.com/2026/03/army-awards" in out
    # 180 chars of actual prose survive, not 77.
    prose = out.split(" (http", 1)[0]
    assert len(prose) >= 170, prose
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_schema.py::test_news_entry_budget_excludes_the_url -v`
Expected: FAIL with `ImportError: cannot import name '_trim_news_entry'`.

- [ ] **Step 3: Implement**

Add to `gtm/schema.py`, below `_trim_keep_source`:

```python
_URL_TAIL_RE = re.compile(r"\s\((https?://[^\s()]+)\)")
_DATE_STAMP_RE = re.compile(r"\s*(\[date:\s*\d{4}-\d{2}\])\s*$")


def _trim_news_entry(s: str, n: int) -> str:
    """Trim a key_news line's prose to n chars, charging neither the trailing URL
    nor the "[date: YYYY-MM]" stamp to the budget.

    2026-07-31: _trim_keep_source protected the URL parenthetical but counted it —
    breakingdefense's 103-char URL left 77 chars for the headline, so every news
    cell in the Sheet read as a fragment. The URL is not prose; a reader scans past
    it. Budget the words, preserve the link whole."""
    s = s.strip()
    stamp = ""
    m = _DATE_STAMP_RE.search(s)
    if m:
        stamp = " " + m.group(1)
        s = s[: m.start()].rstrip()
    url = ""
    m = _URL_TAIL_RE.search(s)
    if m:
        url = f" ({m.group(1)})"
        s = (s[: m.start()] + s[m.end():]).rstrip()
    if len(s) > n:
        s = s[:n].rsplit(" ", 1)[0].rstrip() + "…"
    return s + url + stamp
```

- [ ] **Step 4: Route `key_news` through it and raise the item cap**

In `gtm/schema.py`, change the constants at lines 46-48:

```python
_LONG_LIST_COLS = ("key_news", "buying_signals", "community_signals")
_LIST_MAX_ITEMS = 5  # was 3 — find_news already caps at MAX_NEWS = 5, and dropping
                     # two of five hid whole events rather than trimming prose
_ENTRY_MAX_CHARS = 180  # per entry, prose only (URLs/markers are budgeted separately)
```

Then, wherever the long-list cell is assembled, dispatch `key_news` to `_trim_news_entry` and everything else to `_trim_keep_source`. Locate the call site first:

Run: `grep -n "_LONG_LIST_COLS\|_trim_keep_source" gtm/schema.py`

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_schema.py -v && python -m pytest -q`
Expected: all PASS. Existing tests that assert a 3-item cap will need updating to 5 — update them, the cap change is deliberate.

- [ ] **Step 6: Regenerate a demo CSV and eyeball it**

Run: `python -m gtm.run output us-drone-20`
Expected: the Anduril `buying_signals` cell now ends with `(breakingdefense.com, 2026-03)`, and `key_news` shows 5 entries with readable headlines.
Note: `cmd_output` may push to the Sheet if credentials are present — check with the user before running it, per `CLAUDE.md`'s approval gate.

- [ ] **Step 7: Commit**

```bash
git add gtm/schema.py tests/test_schema.py
git commit -m "fix: budget news cells by prose length, keep the URL whole, show all 5 items"
```

---

## Part C — News filter

### Task C1: Catch same-event/different-outlet duplicates

**Files:**
- Modify: `gtm/enrich.py:86` (`_DUPE_OVERLAP`), `gtm/enrich.py:89-103` (`_is_dupe`)
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_is_dupe(r: dict, kept: list[dict]) -> bool` — unchanged signature, now also matches on shared rare entities rather than headline Jaccard alone.

**Background:** measured on the `us-drone-20` Anduril SERP, every pair scores 0.07-0.30 Jaccard against a `_DUPE_OVERLAP` of 0.6. The two CCA stories ("Air Force Selects General Atomics and Anduril for CCA", "US Air Force awards production contracts to Anduril for...") score **0.30** and both survive. The threshold only ever caught syndicated near-identical headlines; the real failure mode passes clean.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enrich.py
from gtm.enrich import find_news


def test_same_event_different_outlet_is_deduped():
    results = [
        {"title": "Army awards Anduril counter-drone task order as first in new vehicle",
         "link": "https://breakingdefense.com/2026/03/army-awards-anduril/",
         "snippet": "The Army-run counter-drone task force has selected Anduril's Lattice"},
        {"title": "Air Force Selects General Atomics and Anduril for CCA production",
         "link": "https://www.airandspaceforces.com/air-force-anduril-cca-production/",
         "snippet": "In April 2024, the Air Force awarded contracts to continue designing"},
        {"title": "US Air Force awards production contracts to Anduril for CCA",
         "link": "https://www.jpost.com/defense-and-tech/article-899781",
         "snippet": "Anduril says the production line can deliver up to 150 aircraft/year"},
    ]
    out = find_news("Anduril", website="https://www.anduril.com/",
                    search=lambda q, num=10: results)
    assert len(out) == 2, out
    assert any("counter-drone" in line for line in out)
    assert sum("CCA" in line for line in out) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_enrich.py::test_same_event_different_outlet_is_deduped -v`
Expected: FAIL — `assert 3 == 2`.

- [ ] **Step 3: Implement**

Replace `gtm/enrich.py:86-103`:

```python
_DUPE_OVERLAP = 0.35  # Jaccard over headline content words. Was 0.6 until 2026-07-31:
                      # measured against the us-drone-20 Anduril SERP, every pair in a
                      # 5-result set scored 0.07-0.30, including two write-ups of the
                      # same CCA award at 0.30. 0.6 only caught syndicated duplicates.

# Rare, event-naming tokens. Two headlines sharing two of these are almost always the
# same story: the company name plus a programme/agency/dollar figure pins an event far
# more reliably than generic verbs like "awards" or "wins" do.
_ENTITY_RE = re.compile(r"\b(?:[A-Z]{2,}|\$[\d.]+[MBK]?)\b")


def _entities(title: str) -> set[str]:
    """Acronyms (CCA, NDAA, USAF) and dollar figures ($87M) from a headline."""
    return set(_ENTITY_RE.findall(title))


def _is_dupe(r: dict, kept: list[dict]) -> bool:
    """Same event, different outlet. Run us-drone-20 filled 5 news slots with 2 real
    events — the CCA contract appeared 3 times (YouTube, airandspaceforces, jpost) —
    so the signal stage saw far less than the slot count suggested.

    Two independent tests, either sufficient: headline-word Jaccard, and a shared
    rare entity (an acronym or a dollar figure). The entity test is what catches
    "Air Force Selects ... for CCA" against "Air Force awards ... for CCA", which
    share only 0.30 of their words but name the same programme."""
    tokens = _title_tokens(r.get("title", ""))
    ents = _entities(r.get("title", ""))
    if not tokens:
        return False
    for k in kept:
        other = _title_tokens(k.get("title", ""))
        if other and len(tokens & other) / len(tokens | other) >= _DUPE_OVERLAP:
            return True
        if ents and ents & _entities(k.get("title", "")):
            return True
    return False
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_enrich.py -v`
Expected: PASS. If an existing fixture test now over-dedupes, check the headlines by hand before loosening — a genuine second story about the same programme is rare enough that dropping it costs less than showing three copies.

- [ ] **Step 5: Commit**

```bash
git add gtm/enrich.py tests/test_enrich.py
git commit -m "fix: dedupe news by shared entity, not headline overlap alone"
```

---

### Task C2: Drop stale news when fresh news exists

**Files:**
- Modify: `gtm/enrich.py:128-141` (`find_news`)
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: `_news_date(r) -> str` (existing, returns `"YYYY-MM"` or `""`), `RECENCY_MONTHS` (existing, 12).
- Produces: `find_news(...) -> list[str]` — unchanged signature, now newest-first, with items older than `RECENCY_MONTHS` used only to backfill unfilled slots.

**Background:** `us-drone-20` shipped an April 2024 item — 24 months old against `RECENCY_MONTHS = 12` — holding a news slot. `[stale]` marking exists only on `buying_signals`; `key_news` has no recency handling at all.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enrich.py
from gtm.enrich import find_news


def test_stale_news_ranks_below_fresh_and_only_backfills():
    results = [
        {"title": "Old CCA award", "link": "https://x.com/a/2024/04/old/", "snippet": "old"},
        {"title": "New Army order", "link": "https://y.com/2026/03/new/", "snippet": "new"},
    ]
    out = find_news("Acme", website="", search=lambda q, num=10: results,
                    today="2026-07")
    assert out[0].startswith("New Army order"), out
    assert len(out) == 2  # stale still backfills an otherwise-empty slot
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_enrich.py::test_stale_news_ranks_below_fresh_and_only_backfills -v`
Expected: FAIL — `find_news()` got an unexpected keyword argument `today`, and ordering is source order.

- [ ] **Step 3: Implement**

Replace `find_news` in `gtm/enrich.py`:

```python
def _months_old(date: str, today: str) -> int:
    """Whole months between a "YYYY-MM" stamp and today. Undated sorts as fresh —
    an undated trade-press item is usually recent, and demoting it on a missing
    stamp would bury good news behind a dated-but-old one."""
    if not date:
        return 0
    (y1, m1), (y2, m2) = (int(x) for x in date.split("-")), (int(x) for x in today.split("-"))
    return (y2 - y1) * 12 + (m2 - m1)


def find_news(company: str, *, website: str = "", search=serper_search,
              today: str = "") -> list[str]:
    """Newest-first, with anything older than RECENCY_MONTHS demoted to backfill.

    2026-07-31: run us-drone-20 spent a news slot on an April-2024 CCA item, two
    years stale, while the freshness rules only ever applied to buying_signals."""
    today = today or date_module.today().strftime("%Y-%m")
    q = f'"{company}" drone (contract OR launch OR funding OR award OR NDAA OR "Blue UAS")'
    results = search(q, num=10)
    own = _domain(website)
    fresh: list[dict] = []
    stale: list[dict] = []
    for r in results:
        if _is_own_domain(own, r) or _domain(r.get("link", "")) in _NON_NEWS_HOSTS:
            continue
        if _is_dupe(r, fresh + stale):
            continue
        (stale if _months_old(_news_date(r), today) > RECENCY_MONTHS else fresh).append(r)
    kept = (fresh + stale)[:MAX_NEWS]
    return [_news_line(r) for r in kept]
```

Add the import at the top of `gtm/enrich.py` if absent: `from datetime import date as date_module`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_enrich.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gtm/enrich.py tests/test_enrich.py
git commit -m "feat: rank news newest-first, demote items older than RECENCY_MONTHS"
```

---

## Part A — Fit rubric reweight

### Task A1: Rewrite the ICP scoring section

**Files:**
- Modify: `company/ICP.md:93-144`
- Test: `tests/test_fit.py` (a guard test that the file still parses into the four expected criteria)

**Interfaces:**
- Consumes: nothing.
- Produces: the ICP text read by `build_fit_prompt(icp_text, ...)`. Downstream tasks depend on these exact criterion names: `Physical fit`, `Field-deployed`, `Displacement opportunity`, `Budget & procurement`.

**Background:** two criteria worth 40 of 100 points (`Field-deployed` 25, `Volume/price` 15) have **no band table at all** — only `Procurement` and `Displacement` were ever banded. Claude improvises the missing bands, and for "field-deployed" it reaches for the military archetype, so an ag sprayer trucked to a field daily scores below a defense company that names no airframe. Separately, `Volume/price` is sourced from Enrichment, which runs after Fit.

- [ ] **Step 1: Replace the "Fit scoring" table**

In `company/ICP.md`, replace the 5-row weight table with:

```markdown
## Fit scoring (used by the pipeline)

Scored in two phases. Claude scores 80 points from **scrape data only**; Python adds
the remaining 20 after the enrich stage, from fields that do not exist at Fit time.

| Signal | Weight | Phase | Source |
|---|---|---|---|
| Airframe physically fits a case line | 35 | Fit (Claude) | Scrape — dimensions/weights |
| Field-deployed / rugged use case | 25 | Fit (Claude) | Scrape — description, models, case_evidence |
| Displacement opportunity | 20 | Fit (Claude) | Scrape — case_evidence |
| Budget & procurement | 20 | Post-enrich (Python) | headcount, key_news, compliance_evidence |

**Every criterion's bottom band is "no evidence".** Missing evidence scores the bottom
band, never the midpoint — the rule Displacement has carried since 2026-07-28, now
applied to all four. A score the fields cannot support is worse than a low score: it
reads as a finding, and on a company Claude has never heard of it silently becomes 0.
```

- [ ] **Step 2: Add the missing band tables**

Add, replacing the old `Volume / price point` and `US-made / NDAA` prose:

```markdown
### Airframe physically fits a case line /35

| Band | Evidence |
|---|---|
| 30-35 | Published folded L×W×H fits a named case line — cite the line and the source |
| 20-29 | Inferred from weight/class alone, no published dimensions — write "inferred" |
| 8-19 | Airframe named but neither dimensions nor weight found |
| 0-7 | No airframe identified at all (`drone_models` and `drone_dimensions` both empty) |

Dimensions found by the web hunt (spec pages, reviews, Reddit) count as published —
cite the source. The 20-29 cap on weight-only inference is the old 26/30 rule rescaled.

### Field-deployed / rugged use case /25

Score **what the airframe survives, not who buys it.** A category word — "military",
"defense", "industrial" — is not evidence of field deployment. An agricultural sprayer
trucked to a field daily, eating dust and chemical wash, scores above a defense company
that names no airframe and no mission. All six strong-fit segments score on the same
table: defense/tactical, public safety, industrial inspection, survey/mapping, energy
and utilities, and search & rescue carry no inherent advantage over each other.

| Band | Evidence |
|---|---|
| 21-25 | Named harsh-environment duty cycle — daily field transport, vehicle-borne or backpack-carried, launched away from a hangar, weather/dust/chemical exposure |
| 15-20 | Field or outdoor use clearly stated, but no duty-cycle or environment detail |
| 8-14 | Mixed indoor/outdoor, or commercial/cinema use with no ruggedness claim |
| 0-7 | Indoor-only, racing, benchtop, or no use case found after the web hunt |

### Budget & procurement /20 (post-enrich, deterministic)

Replaced "Volume / price point" (15) and "Procurement & compliance fit" (15) on
2026-07-31. Both measured the same thing — can this buyer fund tooled custom foam —
and both were sourced from enrichment data that the Fit stage never sees, because
enrich runs after Fit and only on passers. On run us-drone-20 that produced a line
reading "no unit-price/volume evidence was captured this run" attached to a score of
10/15, filled in from what the model already knew about a famous company.

Scored by `gtm/budget.py::score_budget`, no LLM call, no prose judgment:

| Points | Component | Evidence |
|---|---|---|
| 8 | Procurement evidence | `us_made_ndaa` true, OR non-empty `compliance_evidence`, OR an award-shaped `key_news` line (contract, task order, NDAA, Blue UAS, framework, NATO stock number) |
| 7 / 4 / 1 / 0 | Scale | headcount >=50 / 11-49 / 1-10 / unknown |
| 5 | Capital event | a `key_news` line naming a funding round, Series, or raise |

Geography is not a component. A national MoD framework, a NATO stock number and a US
Blue UAS listing all satisfy "procurement evidence" identically.
```

- [ ] **Step 3: Keep the Displacement table unchanged, rescaled to /20**

The existing bands (13-15 in-house, 11-14 named competitor, 8-10 soft/generic, 3 unknown)
keep their ordering; rescale to: 17-20 in-house, 14-17 named competitor, 10-13 soft or
generic, 0-4 unknown after the web hunt. The "never award midpoint points for missing
evidence" sentence stays exactly as written.

- [ ] **Step 4: Commit**

```bash
git add company/ICP.md
git commit -m "docs: reweight fit rubric to 35/25/20/20, band every criterion, merge budget+procurement"
```

---

### Task A2: Evidence cap in `check_disqualifiers`

**Files:**
- Modify: `gtm/fit.py:79-103` (`check_disqualifiers`), `gtm/fit.py:148-158` (`apply_fit`)
- Test: `tests/test_fit.py`

**Interfaces:**
- Consumes: `DroneExtraction` (existing).
- Produces: `evidence_cap(ex: DroneExtraction) -> int | None` — returns `60` when the extraction identified no airframe at all, else `None`. `apply_fit(p, fit, cap=None)` gains an optional cap that clamps `fit_score` before the tier mapping.

**Background:** Anduril scored 83 (`priority`) with `drone_models: []` and `drone_dimensions: []`. A company whose airframe was never identified cannot be a top-tier prospect for a case built around a specific airframe, whatever the prose says.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fit.py
from gtm.extract import DroneExtraction
from gtm.fit import FitResult, apply_fit, evidence_cap
from gtm.schema import Prospect


def test_no_airframe_identified_caps_the_score_below_priority():
    ex = DroneExtraction(
        company_description="Anduril develops advanced defense technologies, "
                            "including drones, for military applications.",
        drone_models=[],
        drone_dimensions=[],
        drone_weights=["approximately 12 lbs"],
    )
    assert evidence_cap(ex) == 60


def test_a_named_model_lifts_the_cap():
    ex = DroneExtraction(drone_models=["Ghost-X"], drone_dimensions=[])
    assert evidence_cap(ex) is None


def test_apply_fit_clamps_to_the_cap_and_demotes_the_tier():
    p = Prospect(company="Anduril", website="https://www.anduril.com/")
    fit = FitResult(fit_score=83, fit_reason="...", best_case_line="AV-Field")
    apply_fit(p, fit, cap=60)
    assert p.fit_score == 60
    assert p.status == "keep"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_fit.py -k "evidence_cap or clamps" -v`
Expected: FAIL with `ImportError: cannot import name 'evidence_cap'`.

- [ ] **Step 3: Implement**

Add to `gtm/fit.py`:

```python
# A company whose airframe was never identified cannot be a top-tier prospect for a
# case built around a specific airframe. Run us-drone-20 scored Anduril 83/100 —
# priority tier, full drafted outreach — from a one-sentence description, with
# drone_models and drone_dimensions both empty. Three of its five rubric lines were
# scored from prior knowledge of a famous company; on an unknown maker they'd be 0.
NO_AIRFRAME_CAP = 60  # top of the "keep" band — still worth a look, never a priority


def evidence_cap(ex: DroneExtraction) -> int | None:
    """NO_AIRFRAME_CAP when neither a model name nor a dimension triple was found,
    else None. Deliberately does NOT consider drone_weights: a weight in prose
    ("approximately 12 lbs") is not an identified airframe, it's a number in a
    sentence — that is exactly the evidence Anduril was scored 22/30 on."""
    if not ex.drone_models and not ex.drone_dimensions:
        return NO_AIRFRAME_CAP
    return None
```

Then change `apply_fit`:

```python
def apply_fit(p: Prospect, fit: FitResult, *, cap: int | None = None) -> Prospect:
    p.fit_score = min(fit.fit_score, cap) if cap is not None else fit.fit_score
    p.fit_reason = fit.fit_reason
    if cap is not None and fit.fit_score > cap:
        p.fit_reason += (
            f"\nEvidence cap applied — no airframe identified (no model name, no "
            f"dimensions); raw score {fit.fit_score} capped to {cap}."
        )
    p.best_case_line = fit.best_case_line
    if fit.disqualified or p.fit_score < 40:
        p.status = "drop"
    elif p.fit_score >= 70:
        p.status = "priority"
    else:
        p.status = "keep"
    return p
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_fit.py -v`
Expected: PASS.

- [ ] **Step 5: Wire the cap into the fit command**

In `gtm/run.py::cmd_fit`, find the `apply_fit(...)` call and pass the cap. The extraction
for each prospect is already on the `Prospect`; rebuild a `DroneExtraction`-shaped view
from `p.drone_models` / `p.drone_dimensions` rather than re-reading the markdown:

Run: `grep -n "apply_fit" gtm/run.py`

Then pass `cap=NO_AIRFRAME_CAP if not p.drone_models and not p.drone_dimensions else None`.

- [ ] **Step 6: Run the whole suite and commit**

```bash
python -m pytest -q
git add gtm/fit.py gtm/run.py tests/test_fit.py
git commit -m "feat: cap fit at 60 when no airframe was identified"
```

---

### Task A3: Ban prior knowledge and require field citations in the fit prompt

**Files:**
- Modify: `gtm/fit.py:106-145` (`build_fit_prompt`)
- Test: `tests/test_fit.py`

**Interfaces:**
- Consumes: the ICP text from Task A1.
- Produces: `build_fit_prompt(icp_text, company, ex) -> str` — unchanged signature, new body.

**Background:** the Anduril `fit_reason` scored `Procurement 12/15` while its own text said "no specific named certification found" — the 12-15 band explicitly requires one. And `Volume/price 10/15` was justified by "Anduril is an established defense prime", a fact from training data, not from any field in the prompt.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fit.py
from gtm.extract import DroneExtraction
from gtm.fit import build_fit_prompt


def test_prompt_bans_prior_knowledge_and_demands_field_citations():
    prompt = build_fit_prompt("ICP TEXT", "Anduril", DroneExtraction())
    lowered = prompt.lower()
    assert "not evidence" in lowered
    assert "already know" in lowered
    assert "[field:" in prompt
    # 80-point scale: budget is scored later, in Python
    assert "80" in prompt
    assert "Budget & procurement" not in prompt
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_fit.py::test_prompt_bans_prior_knowledge_and_demands_field_citations -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Replace the tail of `build_fit_prompt` (keep the existing geography paragraph and the
disqualifier paragraph verbatim — both are still correct) and add:

```python
    return f"""...existing header, ICP, prospect fields, geography and disqualifier text...

Score ONLY the three scrape-phase criteria, out of 80 total: Physical fit /35,
Field-deployed /25, Displacement opportunity /20. Budget & procurement is scored later,
in Python, from enrichment data you do not have — do not score it and do not mention it.

Score ONLY from the fields listed above. What you already know about this company from
training is NOT evidence, however confident you are and however famous the company. If a
field is empty, the criterion it feeds scores its bottom band — the ICP's bottom band is
always "no evidence found", never a midpoint. A score you cannot trace to a field above
is the failure this instruction exists to prevent: it looks like a finding, and on a
company you have never heard of it silently collapses to zero.

Never score a band whose stated evidence requirement you did not find. If the band table
says "named programme or certification" and you found none, you are not in that band, no
matter what else the company is.

fit_reason format — one line per scrape-phase criterion, newline-separated ("\\n" in the
JSON string):

  "<Criterion> <score>/<max> — [field: <field name>] <plain-English why>"

<field name> is the exact field you read it from: description, drone_models,
drone_dimensions, drone_weights, case_evidence, compliance_evidence, us_made_ndaa — or
the literal "none found" when nothing supported the score, which must then be the bottom
band. Plain English only: expand any jargon or acronym on first use (e.g. "SRR (Short
Range Reconnaissance)"), and say "inferred" explicitly when a judgment is inferred rather
than published.

Reply with ONLY this JSON (no prose):
{{"fit_score": <0-80>, "fit_reason": "<one line per criterion, as specified above>",
"best_case_line": "<AV-Micro|AV-Field|AV-Ops|AV-Convoy|>", "disqualified": <true|false>}}"""
```

Update `FitResult.fit_score` to `Field(ge=0, le=80)` at `gtm/fit.py:45`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_fit.py -v`
Expected: PASS. Existing tests asserting a 0-100 `FitResult` will fail — update them to the 80-point scrape phase; this is the intended contract change.

- [ ] **Step 5: Commit**

```bash
git add gtm/fit.py tests/test_fit.py
git commit -m "feat: fit prompt scores 80 from scrape only, bans prior knowledge, requires field citations"
```

---

### Task A4: Deterministic post-enrich budget score

**Files:**
- Create: `gtm/budget.py`
- Test: `tests/test_budget.py`

**Interfaces:**
- Consumes: `Prospect` (`headcount: str`, `key_news: list[str]`, `compliance_evidence: str`, `us_made_ndaa: bool | None`).
- Produces: `score_budget(p: Prospect) -> tuple[int, str]` — points 0-20 and a one-line `fit_reason` fragment in the same `"<Criterion> <score>/<max> — [field: ...] <why>"` shape Task A3 defined.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_budget.py
from gtm.budget import score_budget
from gtm.schema import Prospect


def _p(**kw):
    return Prospect(company="X", website="https://x.com/", **kw)


def test_full_marks_for_award_scale_and_capital():
    p = _p(headcount="7000",
           key_news=["Army awards Anduril counter-drone task order (breakingdefense.com)",
                     "Anduril raises $1.5B Series G (techcrunch.com)"])
    points, line = score_budget(p)
    assert points == 20
    assert line.startswith("Budget & procurement 20/20 — [field:")


def test_unknown_everything_scores_zero_not_a_midpoint():
    points, line = score_budget(_p())
    assert points == 0
    assert "none found" in line


def test_headcount_bands():
    assert score_budget(_p(headcount="7000"))[0] == 7
    assert score_budget(_p(headcount="51-200"))[0] == 7
    assert score_budget(_p(headcount="25"))[0] == 4
    assert score_budget(_p(headcount="4"))[0] == 1


def test_compliance_evidence_alone_earns_the_procurement_component():
    assert score_budget(_p(compliance_evidence="NATO stock number 1550-99-123-4567"))[0] == 8


def test_geography_is_not_a_component():
    us = _p(us_made_ndaa=True)
    foreign = _p(compliance_evidence="Bundeswehr framework agreement")
    assert score_budget(us)[0] == score_budget(foreign)[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gtm.budget'`.

- [ ] **Step 3: Implement**

```python
"""Post-enrich budget scoring — the last 20 of the 100-point fit score.

Split out of the Fit stage on 2026-07-31. "Volume / price point" (15) and
"Procurement & compliance fit" (15) both asked Claude, at Fit time, to score
enrichment data that only exists after the enrich stage — which runs later, and only
on passers. Run us-drone-20 shows the result: a line reading "no unit-price/volume
evidence was captured this run" attached to 10/15, filled in from the model's own
knowledge of a famous company. On an unknown maker that same line scores 0.

Deterministic, zero LLM cost, every component traceable to a named field.
"""
from __future__ import annotations

import re

from gtm.schema import Prospect

PROCUREMENT_POINTS = 8
CAPITAL_POINTS = 5
_HEADCOUNT_BANDS = ((50, 7), (11, 4), (1, 1))  # (floor, points), highest first
MAX_BUDGET = 20

# Award-shaped news. Deliberately country-neutral: a NATO stock number, a national MoD
# framework and a US Blue UAS listing satisfy this identically (company/ICP.md).
_AWARD_RE = re.compile(
    r"\b(contract|task order|awarded?|procurement|framework|NDAA|Blue UAS|"
    r"NATO stock number|type certification|BVLOS)\b",
    re.IGNORECASE,
)
_CAPITAL_RE = re.compile(
    r"\b(series\s+[a-h]\b|raise[sd]?|raising|funding round|seed round|"
    r"\$[\d.]+\s*(?:m|b|million|billion)\b)",
    re.IGNORECASE,
)
_FIRST_INT = re.compile(r"\d+")


def _headcount_points(headcount: str) -> tuple[int, str]:
    """Bands off the first integer in the string — enrichment writes exact counts
    ("7000") and LinkedIn-style ranges ("51-200") interchangeably, and the low end
    of a range is the conservative read."""
    m = _FIRST_INT.search(headcount or "")
    if not m:
        return 0, ""
    n = int(m.group())
    for floor, points in _HEADCOUNT_BANDS:
        if n >= floor:
            return points, f"headcount {headcount}"
    return 0, ""


def score_budget(p: Prospect) -> tuple[int, str]:
    """(points 0-20, one fit_reason line). Never awards a midpoint for missing
    evidence: every component that finds nothing contributes exactly 0."""
    points = 0
    fields: list[str] = []
    whys: list[str] = []

    news = " | ".join(p.key_news or [])
    if p.us_made_ndaa or (p.compliance_evidence or "").strip() or _AWARD_RE.search(news):
        points += PROCUREMENT_POINTS
        if p.us_made_ndaa:
            fields.append("us_made_ndaa")
            whys.append("NDAA-compliant")
        if (p.compliance_evidence or "").strip():
            fields.append("compliance_evidence")
            whys.append(p.compliance_evidence.strip()[:60])
        elif _AWARD_RE.search(news):
            fields.append("key_news")
            whys.append("award/procurement evidence in the news")

    head_points, head_why = _headcount_points(p.headcount)
    if head_points:
        points += head_points
        fields.append("headcount")
        whys.append(head_why)

    if _CAPITAL_RE.search(news):
        points += CAPITAL_POINTS
        if "key_news" not in fields:
            fields.append("key_news")
        whys.append("capital event in the news")

    points = min(points, MAX_BUDGET)
    field_note = ", ".join(dict.fromkeys(fields)) if fields else "none found"
    why = "; ".join(whys) if whys else (
        "no procurement, scale or capital evidence after enrichment"
    )
    return points, f"Budget & procurement {points}/{MAX_BUDGET} — [field: {field_note}] {why}."
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_budget.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gtm/budget.py tests/test_budget.py
git commit -m "feat: deterministic post-enrich budget & procurement score"
```

---

### Task A5: Wire budget scoring into the enrich stage

**Files:**
- Modify: `gtm/run.py::cmd_enrich`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `score_budget` (Task A4), `NO_AIRFRAME_CAP` (Task A2).
- Produces: after `gtm.run enrich`, every passer's `fit_score` is the 0-100 total, `fit_reason` carries the Budget line, and `status` has been recomputed against the 70/40 bands.

**Background:** enrich gates on `status in ("priority", "keep")`, i.e. on the provisional 80-point score. A provisional 32/80 is the same 40% as the old 40/100 — the gate threshold must move with the scale or the pipeline silently narrows.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run.py
from gtm.run import apply_budget_scores
from gtm.schema import Prospect


def test_budget_is_added_after_enrich_and_the_tier_is_recomputed():
    p = Prospect(company="Anduril", website="https://www.anduril.com/", status="keep")
    p.fit_score = 55  # provisional, out of 80
    p.fit_reason = "Physical fit 8/35 — [field: none found] no airframe identified."
    p.headcount = "7000"
    p.key_news = ["Army awards Anduril counter-drone task order (breakingdefense.com)"]
    apply_budget_scores([p])
    assert p.fit_score == 70
    assert p.status == "priority"
    assert "Budget & procurement 15/20" in p.fit_reason


def test_budget_is_not_applied_twice_on_a_rerun():
    p = Prospect(company="X", website="https://x.com/", status="keep")
    p.fit_score = 55
    p.fit_reason = "Physical fit 30/35 — [field: drone_dimensions] fits AV-Field."
    p.headcount = "60"
    apply_budget_scores([p])
    apply_budget_scores([p])
    assert p.fit_score == 62
    assert p.fit_reason.count("Budget & procurement") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run.py -k budget -v`
Expected: FAIL with `ImportError: cannot import name 'apply_budget_scores'`.

- [ ] **Step 3: Implement**

Add to `gtm/run.py`, above `cmd_enrich`:

```python
def apply_budget_scores(prospects: list[Prospect]) -> int:
    """Fold the deterministic Budget & procurement score into each passer's total and
    recompute its tier. Idempotent — a rerun of `gtm.run enrich` must not stack a
    second Budget line or double the points."""
    from gtm.budget import score_budget

    scored = 0
    for p in prospects:
        if p.status not in ("priority", "keep"):
            continue
        if "Budget & procurement" in (p.fit_reason or ""):
            continue
        points, line = score_budget(p)
        p.fit_score = min(p.fit_score + points, 100)
        p.fit_reason = f"{p.fit_reason}\n{line}".strip()
        p.status = "priority" if p.fit_score >= 70 else "keep" if p.fit_score >= 40 else "drop"
        scored += 1
    return scored
```

Call it in `cmd_enrich` after enrichment has filled `headcount` / `key_news` and before
`save_state`, then print `f"budget scored for {n} prospect(s)"`.

- [ ] **Step 4: Move the enrich gate to the 80-point scale**

The `keep` floor at Fit time is now 32, not 40 (40% of 80). Find every threshold:

Run: `grep -rn "40\b" gtm/fit.py gtm/run.py`

Update `apply_fit`'s provisional mapping to `>= 56` → priority-provisional, `>= 32` →
keep-provisional, else drop — and add a comment naming the rescale so the next reader
does not "fix" it back to 70/40.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS. Fixture-based fit tests asserting 0-100 scores from the Fit stage need
updating to the 80-point provisional scale.

- [ ] **Step 6: Re-score an existing run end to end and compare**

Run: `python -m gtm.run fit us-drone-20 data/runs/us-drone-20/fit.json`
Expected: Anduril lands at or below 60 via the evidence cap, `status="keep"`, not
`priority`. Report the cost line.

- [ ] **Step 7: Commit**

```bash
git add gtm/run.py gtm/fit.py tests/test_run.py
git commit -m "feat: two-phase fit — 80 from scrape, 20 from deterministic post-enrich budget"
```

---

### Task A6: Update CLAUDE.md and docs/PLAN.md

**Files:**
- Modify: `CLAUDE.md` (Pipeline section, stage 4), `docs/PLAN.md`

- [ ] **Step 1: Update the stage-4 description**

In `CLAUDE.md`, replace the Fit bullet:

```markdown
4. **Fit** — two-phase. Claude scores 80 vs `company/ICP.md` from scrape data only
   (Physical 35 / Field-deployed 25 / Displacement 20); `gtm/budget.py::score_budget`
   adds a deterministic 0-20 Budget & procurement score after enrich, from `headcount`,
   `key_news` and `compliance_evidence` — fields that do not exist at Fit time. Size is
   still the only hard disqualifier; a company with no identified airframe is capped at
   60 (`gtm/fit.py::evidence_cap`) and can never reach priority tier.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md docs/PLAN.md
git commit -m "docs: describe two-phase fit scoring"
```

---

## Part B — Community signals

### Task B1: Instrument the funnel before changing it

**Files:**
- Modify: `gtm/enrich.py::find_community_signals`, `gtm/run.py::cmd_enrich`
- Test: `tests/test_enrich.py`

**Interfaces:**
- Consumes: `find_community_signals(p, *, search, client, costlog)`.
- Produces: `find_community_signals(..., trace: dict | None = None)` — when `trace` is passed, it is filled with `{"pooled": int, "third_party": int, "kept": int}` so the stage that zeroed out is identifiable.

**Background:** measured across all 26 runs in `data/runs/`, runs `us-drone-3` through `us-drone-7` produced community signals; **`us-drone-8` onward produced none — 0 of 13 passers.** `data/errors.log` records no community failures, so nothing crashed. The zero could come from any of three stages, and none of them logs a count:

1. Serper returning nothing for the query built by `_pain_queries`;
2. the `gpt-4o-mini` `_RELEVANCE_PROMPT` three-gate filter plus the `_has_problem` check rejecting every candidate;
3. Claude discarding the candidates in `build_signal_prompt` — `us-drone-20`'s `signals.json` has an explicit `"community_signals": []` for every company, which is consistent with either (2) handing Claude an empty list or (3) Claude rejecting a full one.

Do not tune the gates until the measurement says which one is dropping everything.
`enrich.py:235` records the design intent — "precision at this stage is cheap, recall is
not" — so a loosened gate must be justified against a measured number, not a guess.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_enrich.py
from gtm.enrich import find_community_signals
from gtm.schema import Prospect


def test_trace_records_each_funnel_stage():
    p = Prospect(company="Acme", website="https://acme.com/",
                 description="public safety drone maker", drone_models=["Falcon 3"])
    results = [{"title": "case cracked", "snippet": "my Falcon 3 case cracked in transit",
                "link": "https://reddit.com/r/drones/1"}]

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def parse(**kw):
                    raise AssertionError("not reached in this test")

    trace = {}
    find_community_signals(p, search=lambda q, num=10: results,
                           client=_FakeClient(), costlog=None, trace=trace)
    assert trace["pooled"] == 1
    assert trace["third_party"] == 1
    assert "kept" in trace
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_enrich.py::test_trace_records_each_funnel_stage -v`
Expected: FAIL — unexpected keyword argument `trace`.

- [ ] **Step 3: Implement**

```python
def find_community_signals(p: Prospect, *, search=serper_search, client=None,
                           costlog=None, trace: dict | None = None) -> list[str]:
    """...existing docstring...

    `trace`, when passed, is filled with per-stage counts. Added 2026-07-31: this
    funnel has returned zero for every passer since run us-drone-8 (0 of 13) and
    nothing logged which of its three stages — Serper, the gpt-4o-mini gates, or
    Claude's re-judgment in build_signal_prompt — was dropping everything."""
    pooled, seen_links = [], set()
    for q in _pain_queries(p):
        for r in search(q, num=10):
            link = r.get("link", "")
            if link in seen_links:
                continue
            seen_links.add(link)
            pooled.append(r)
    third_party = [r for r in pooled if not _is_own_post(p.company, r)]
    kept = _relevance_filter(third_party, client=client, costlog=costlog)
    if trace is not None:
        trace.update(pooled=len(pooled), third_party=len(third_party), kept=len(kept))
    return kept
```

In `cmd_enrich`, pass a `trace` dict per prospect and print one line each:
`print(f"  community candidates {p.company}: pooled={t['pooled']} third_party={t['third_party']} kept={t['kept']}")`

- [ ] **Step 4: Run the tests and commit**

```bash
python -m pytest tests/test_enrich.py -v && python -m pytest -q
git add gtm/enrich.py gtm/run.py tests/test_enrich.py
git commit -m "feat: trace the community-signal funnel per stage"
```

- [ ] **Step 5: Take the measurement on a live run**

Run: `python -m gtm.run enrich us-drone-20`
Cost: roughly 2 Serper credits and 1 `gpt-4o-mini` call per passer — about 10 credits
plus pennies for a 5-passer run. **Report the cost line.**

Record the three counts per company. Then, and only then, write Task B2 against whichever
stage the numbers indict:
- `pooled == 0` → the query is wrong; check `_infer_category` bucket assignment first
  (`enrich.py:241-279` documents this exact failure for Hylio on us-drone-13).
- `pooled > 0, kept == 0` → the `gpt-4o-mini` gates over-reject; the three gates plus
  `_has_problem` plus "prefer rejecting a borderline result" were each added separately
  and never re-measured together.
- `kept > 0` but `signals.json` still empty → Claude is discarding them in
  `build_signal_prompt`; the prompt needs to say a category-level signal is usable ammo.

---

## Self-review

**Spec coverage:**
- Full reweight → Tasks A1-A6. ✓
- Hard cap when models+dimensions empty → Task A2. ✓
- No-evidence band in every rubric row → Task A1 (all four criteria banded, bottom band stated globally). ✓
- Ban prior knowledge in `build_fit_prompt` → Task A3. ✓
- Field citation per `fit_reason` line → Task A3 (`[field: ...]`), carried into the Budget line by Task A4. ✓
- News dedupe threshold + entity overlap + recency → Tasks C1, C2. ✓
- "Budget & procurement 20 ENRICH ONLY" explained → Task A1's band table and Task A4's module docstring. ✓
- Community signals → Task B1 (measurement); B2 deferred by design, since the fix depends on the measurement.
- Truncated `buying_signals` / `key_news` columns → Tasks D1, D2. ✓

**Type consistency:** `score_budget` returns `tuple[int, str]` in A4 and is consumed that way in A5. `evidence_cap` returns `int | None` in A2 and is consumed as `cap=` by `apply_fit` in the same task. `find_community_signals`'s `trace` is `dict | None` in B1, passed a `dict` by `cmd_enrich`. Criterion names match between the ICP tables (A1), the prompt (A3) and the budget line (A4).

**Known gap, deliberate:** Task B2 has no steps because its content is determined by B1's measurement. Writing speculative steps for three mutually exclusive causes would be a placeholder.
