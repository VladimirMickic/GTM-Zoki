# Community Signals + Expanded Outreach Angle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Reddit-only, first-hit-only `reddit_signal` with a multi-source,
top-5 `community_signals` list, and expand `outreach_angle` from one bare sentence into
angle + why-it-fits + supporting evidence.

**Architecture:** `gtm/schema.py`'s `reddit_signal: str` field becomes
`community_signals: list[str]`, same sheet-column slot, added to the existing
newline-join group (alongside `key_news`/`buying_signals`). `gtm/enrich.py`'s
`find_reddit_signal` becomes `find_community_signals`, broadening its Serper query from
`site:reddit.com` only to `site:reddit.com OR site:x.com OR site:twitter.com OR
site:rcgroups.com`, and returning the top 5 hits (reusing the existing `_news_line`
formatter) instead of the first. `build_signal_prompt`'s evidence block and its
`outreach_angle` instruction are updated to match.

**Tech Stack:** Python 3, Pydantic (existing), pytest. No new libraries, no new Serper
call — same one query, just a wider `site:` clause and a `[:5]` slice instead of
first-match-only.

## Global Constraints

- Git identity: `Vladimir Mickic <mickicvladimir98@gmail.com>`. NO `Co-Authored-By` trailer.
- Work directly on `main` (established project convention — no feature branch). Never push
  unless the user explicitly asks.
- TDD: RED → GREEN per task.
- Keep it lean (CLAUDE.md): no speculative generality.
- Spec of record: `docs/superpowers/specs/2026-07-20-community-signals-outreach-angle-design.md`.

---

### Task 1: `gtm/schema.py` — rename `reddit_signal` to `community_signals` (list)

**Files:**
- Modify: `gtm/schema.py`
- Test: `tests/test_schema.py`
- Modify (housekeeping, not test-covered — confirmed via grep no test loads this file):
  `tests/fixtures/enrich_teal.json`

**Interfaces:**
- Consumes: nothing (schema-only change).
- Produces: `Prospect.community_signals: list[str] = []` (replaces `reddit_signal: str`).
  `SHEET_COLUMNS` has `"community_signals"` in the exact slot `"reddit_signal"` used to
  occupy (between `"linkedin"` and `"outreach_angle"`). `to_sheet_row` renders it
  newline-joined, same as `key_news`/`buying_signals`. Task 2 (`gtm/enrich.py`) depends on
  this field existing.

- [ ] **Step 1: Write the failing test**

In `tests/test_schema.py`, replace the existing `test_news_and_signals_render_one_per_line`
with:

```python
def test_news_and_signals_render_one_per_line():
    # feedback 2026-07-18: one line per point in the sheet, not run-on "; " strings
    p = Prospect(
        company="X", website="https://x.com",
        key_news=["A — a (url1)", "B — b (url2)"],
        buying_signals=["Signal one — why (src)", "Signal two — why (src)"],
        community_signals=["Reddit thread — hot take (url3)", "X post — reveal (url4)"],
    )
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("key_news")] == "A — a (url1)\nB — b (url2)"
    assert row[SHEET_COLUMNS.index("buying_signals")] == "Signal one — why (src)\nSignal two — why (src)"
    assert row[SHEET_COLUMNS.index("community_signals")] == "Reddit thread — hot take (url3)\nX post — reveal (url4)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schema.py::test_news_and_signals_render_one_per_line -v`
Expected: FAIL — `ValueError: 'community_signals' is not in list` (raised by
`SHEET_COLUMNS.index("community_signals")`, since the column doesn't exist yet).

- [ ] **Step 3: Rename the field, column, and join group**

In `gtm/schema.py`, in `SHEET_COLUMNS`, change:

```python
    "reddit_signal",
```

to:

```python
    "community_signals",
```

In the `Prospect` class, change:

```python
    reddit_signal: str = ""
```

to:

```python
    community_signals: list[str] = []
```

In `to_sheet_row`, change:

```python
                sep = "\n" if col in ("key_news", "buying_signals") else "; "
```

to:

```python
                sep = "\n" if col in ("key_news", "buying_signals", "community_signals") else "; "
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (all tests in the file, no regression).

- [ ] **Step 5: Housekeeping — rename the field in the orphaned fixture**

`tests/fixtures/enrich_teal.json` is not loaded by any test (confirmed: `grep -rln
"enrich_teal.json" tests/ gtm/` returns nothing), but keep it consistent with the current
schema. Change:

```json
  "reddit_signal": "Are made-in-America drones really great value? Teal ... — https://www.reddit.com/r/drones/comments/15ltup8/are_madeinamerica_drones_really_great_value_teal/",
```

to:

```json
  "community_signals": ["Are made-in-America drones really great value? Teal ... — https://www.reddit.com/r/drones/comments/15ltup8/are_madeinamerica_drones_really_great_value_teal/"],
```

- [ ] **Step 6: Commit**

```bash
git add gtm/schema.py tests/test_schema.py tests/fixtures/enrich_teal.json
git commit -m "feat: schema — reddit_signal str becomes community_signals list"
```

---

### Task 2: `gtm/enrich.py` — multi-source `find_community_signals` + expanded outreach angle

**Files:**
- Modify: `gtm/enrich.py`
- Test: `tests/test_enrich.py`
- Modify (docs, no test coverage): `docs/PLAN.md`, `docs/data-flow.html`

**Interfaces:**
- Consumes: `Prospect.community_signals: list[str]` (Task 1).
- Produces: `find_community_signals(company: str, *, search=serper_search) -> list[str]`
  (replaces `find_reddit_signal`). `enrich(p)` sets `p.community_signals` instead of
  `p.reddit_signal`. `build_signal_prompt(p)`'s evidence block and `outreach_angle`
  instruction text change (signature unchanged).

- [ ] **Step 1: Write the failing tests**

In `tests/test_enrich.py`, change the import line:

```python
from gtm.enrich import build_signal_prompt, enrich, find_company_linkedin, find_news, find_reddit_signal
```

to:

```python
from gtm.enrich import build_signal_prompt, enrich, find_community_signals, find_company_linkedin, find_news
```

Replace the `SERPS` dict's `"reddit"` key (6 items now, matching the `"news"` key's
cap-at-5 pattern) — replace:

```python
    "reddit": [
        {"title": "Teal 2 field review : r/UAVmapping", "link": "https://reddit.com/r/UAVmapping/abc", "snippet": "impressed with thermal"},
    ],
```

with:

```python
    "reddit": [
        {"title": "Teal 2 field review : r/UAVmapping", "link": "https://reddit.com/r/UAVmapping/abc", "snippet": "impressed with thermal"},
        {"title": "Teal on X: launch thread", "link": "https://x.com/teal/status/1", "snippet": "exciting reveal"},
        {"title": "RCGroups build thread", "link": "https://rcgroups.com/forums/showthread.php?t=1", "snippet": "comparing frames"},
        {"title": "Fourth item", "link": "https://example.com/r4", "snippet": "misc"},
        {"title": "Fifth item", "link": "https://example.com/r5", "snippet": "misc"},
        {"title": "Sixth item", "link": "https://example.com/r6", "snippet": "misc"},
    ],
```

Replace `test_reddit_signal_is_title_plus_link` with:

```python
def test_community_signals_multi_source_capped_at_five():
    sigs = find_community_signals("Teal Drones", search=fake_search)
    assert len(sigs) == 5
    assert "Teal 2 field review" in sigs[0]
    assert "reddit.com" in sigs[0]
```

Replace `test_enrich_fills_prospect_fields`'s reddit assertion — change:

```python
    assert p.reddit_signal
```

to:

```python
    assert len(p.community_signals) == 5
```

Replace `test_empty_serps_leave_fields_blank`'s reddit assertion — change:

```python
    assert p.reddit_signal == ""
```

to:

```python
    assert p.community_signals == []
```

Replace `test_signal_prompt_has_evidence_and_contract`'s `Prospect(...)` construction —
change:

```python
    p = Prospect(company="Teal Drones", website="https://t.com", key_news=["Teal wins SRR (url)"], reddit_signal="review — url")
```

to:

```python
    p = Prospect(company="Teal Drones", website="https://t.com", key_news=["Teal wins SRR (url)"], community_signals=["review — url"])
```

Add a new test for the expanded `outreach_angle` instruction, appended after
`test_signal_prompt_demands_lines_with_source_and_date`:

```python
def test_signal_prompt_expands_outreach_angle_instruction():
    p = Prospect(company="X", website="https://x.com")
    prompt = build_signal_prompt(p)
    assert "2-3 sentences" in prompt
    assert "why it's the strongest fit" in prompt
    assert "community signal" in prompt.lower()
```

Replace `test_news_and_reddit_queries_carry_drone_disambiguator` with:

```python
def test_news_and_community_signals_queries_carry_drone_disambiguator():
    # discover-3 2026-07-18: "Paladin" news returned lenders, awards, r/Fantasy
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    find_news("Paladin", search=spy)
    find_community_signals("Paladin", search=spy)
    assert all("drone" in q.lower() for q in captured), captured
    assert all(
        site in captured[1]
        for site in ("site:reddit.com", "site:x.com", "site:twitter.com", "site:rcgroups.com")
    ), captured[1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_enrich.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_community_signals' from 'gtm.enrich'`
(the import line at the top of the file fails before any individual test runs).

- [ ] **Step 3: Implement the broadened, multi-hit signal finder**

In `gtm/enrich.py`, replace:

```python
def find_reddit_signal(company: str, *, search=serper_search) -> str:
    for r in search(f'site:reddit.com "{company}" drone', num=10):
        if r.get("link"):
            return f"{r.get('title', '')} — {r['link']}"
    return ""
```

with:

```python
MAX_COMMUNITY_SIGNALS = 5


def find_community_signals(company: str, *, search=serper_search) -> list[str]:
    q = f'"{company}" drone (site:reddit.com OR site:x.com OR site:twitter.com OR site:rcgroups.com)'
    results = search(q, num=10)
    return [_news_line(r) for r in results[:MAX_COMMUNITY_SIGNALS]]
```

(`_news_line` is the existing helper defined above `find_news` in this file — it already
formats `f"{title} — {snippet} ({link})"`, no change needed there.)

Then replace:

```python
def enrich(p: Prospect, *, search=serper_search) -> Prospect:
    p.linkedin = find_company_linkedin(p.company, search=search)
    p.reddit_signal = find_reddit_signal(p.company, search=search)
    p.key_news = find_news(p.company, search=search)
    return p
```

with:

```python
def enrich(p: Prospect, *, search=serper_search) -> Prospect:
    p.linkedin = find_company_linkedin(p.company, search=search)
    p.community_signals = find_community_signals(p.company, search=search)
    p.key_news = find_news(p.company, search=search)
    return p
```

Then replace `build_signal_prompt` with:

```python
def build_signal_prompt(p: Prospect) -> str:
    return f"""From the evidence below, synthesize for {p.company}:
- buying_signals: concrete triggers matching our ICP watchlist (new launch, gov contract,
  NDAA/Blue UAS cert, funding, relevant hiring, new vertical). Only evidence-backed ones.
  Each list item is one line: "<what happened> — <why it matters to us> (<source>, <date>)".
  Plain English, expand jargon/acronyms on first use; omit the date if the evidence has none.
- outreach_angle: 2-3 sentences: (1) the strongest ICP outreach angle for this prospect,
  (2) why it's the strongest fit for THIS prospect specifically, (3) which piece of
  evidence (news / community signal / fit reason) backs it. Still a single string, no
  line breaks.

## Evidence
news: {p.key_news}
community signals: {p.community_signals}
linkedin: {p.linkedin}
description: {p.description}

Reply with ONLY this JSON (no prose):
{{"buying_signals": ["..."], "outreach_angle": "..."}}"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_enrich.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full suite for no regression**

Run: `pytest -q`
Expected: all pass, same total count as before this plan (no tests added or removed net —
Task 1 kept the same test count, Task 2 replaced 2 old tests with 2 renamed + 1 new, net
+1 to the suite).

- [ ] **Step 6: Update docs for the field rename**

In `docs/PLAN.md`, change:

```
fit_score · fit_reason · buying_signals · key_news · linkedin · reddit_signal · outreach_angle ·
```

to:

```
fit_score · fit_reason · buying_signals · key_news · linkedin · community_signals · outreach_angle ·
```

In `docs/data-flow.html`, change:

```
          <p class="rec"><b>record</b> <span class="plus">+=</span> contact_name, contact_title, contact_linkedin, key_news, linkedin, reddit_signal, buying_signals, outreach_angle</p>
```

to:

```
          <p class="rec"><b>record</b> <span class="plus">+=</span> contact_name, contact_title, contact_linkedin, key_news, linkedin, community_signals, buying_signals, outreach_angle</p>
```

- [ ] **Step 7: Commit**

```bash
git add gtm/enrich.py tests/test_enrich.py docs/PLAN.md docs/data-flow.html
git commit -m "feat: enrich — multi-source community_signals, expanded outreach_angle"
```

---

## Live smoke (after Task 2)

Run `enrich` + `signals` against a real run with priority/keep prospects (e.g.
`data/runs/discover-3`, per the ledger):

```bash
python -m gtm.run enrich discover-3
```

Expected: the printed SIGNAL PROMPTS include a `community signals:` evidence line (may be
empty list if no real hits — that's fine, same log-and-skip-shaped behavior as before) and
the prompt's `outreach_angle` instruction shows the expanded 3-part wording. No code
change from the smoke; confirms the real `enrich()` call path and prompt shape both work
end to end.

## Self-review notes

- **Spec coverage:** field rename to a list + broadened multi-source query + top-5 cap
  (Task 1 + Task 2), expanded `outreach_angle` instruction (Task 2), test/fixture/docs
  renames (Task 1 Step 5, Task 2 Steps 1 and 6). All spec sections covered.
- **No scope creep:** `gtm/run.py`'s `merge_signals` untouched (spec confirms
  `community_signals` is set directly by `enrich()`, not merged from `signals.json`).
  `gtm/draft.py`/`qa_check` untouched (spec confirms `community_signals` was never fed into
  the draft prompt or QA evidence, and stays that way).
  No new Serper call — same one query per field, just a wider `site:` clause and a `[:5]`
  slice.
- **Type consistency:** `find_community_signals` returns `list[str]` everywhere it's
  referenced (schema field, `enrich()` assignment, test assertions).
