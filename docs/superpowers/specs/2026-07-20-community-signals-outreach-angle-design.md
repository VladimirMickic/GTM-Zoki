# Design: community_signals + expanded outreach_angle

Date: 2026-07-20
Status: approved (user)

## Context

User-reported output/sheet gaps (this is sub-project A of a 3-part backlog: A = this
design, B = contacts as a separate sheet tab, C = missing drone models/dimensions bug —
decided order A → B → C):

1. `reddit_signal` only searches `site:reddit.com` and returns the FIRST hit as a single
   string — misses non-Reddit chatter (X/Twitter, RC/drone forums) and drops every hit
   after the first.
2. `outreach_angle` is capped at "ONE sentence" — too thin for the draft/QA stages to work
   with.

## Current behavior (`gtm/enrich.py`, `gtm/schema.py`)

- `find_reddit_signal(company) -> str`: queries `site:reddit.com "{company}" drone`,
  returns `f"{title} — {link}"` for the first result with a link, else `""`.
- `Prospect.reddit_signal: str = ""`, sheet column `reddit_signal`, joined as a single
  string in `to_sheet_row` (not in the `"\n"`-join group).
- `build_signal_prompt` embeds `reddit: {p.reddit_signal}` as one line of evidence and
  asks for `outreach_angle` as "ONE sentence picking the strongest ICP outreach angle."

## Changes

### `gtm/enrich.py`

Replace `find_reddit_signal` with:

```python
MAX_COMMUNITY_SIGNALS = 5

def find_community_signals(company: str, *, search=serper_search) -> list[str]:
    q = f'"{company}" drone (site:reddit.com OR site:x.com OR site:twitter.com OR site:rcgroups.com)'
    results = search(q, num=10)
    return [_news_line(r) for r in results[:MAX_COMMUNITY_SIGNALS]]
```

Reuses the existing `_news_line` formatter (title — snippet (link)) for consistency with
`find_news`. `enrich()` sets `p.community_signals = find_community_signals(p.company, search=search)`
instead of `p.reddit_signal = find_reddit_signal(...)`.

`build_signal_prompt`'s evidence block: `reddit: {p.reddit_signal}` → `community signals:
{p.community_signals}`. Its `outreach_angle` instruction changes from:

> outreach_angle: ONE sentence picking the strongest ICP outreach angle for this prospect.

to:

> outreach_angle: 2-3 sentences — (1) the strongest ICP outreach angle for this prospect,
> (2) why it's the strongest fit for THIS prospect specifically, (3) which piece of
> evidence (news/community signal/fit reason) backs it. Still a single string field.

### `gtm/schema.py`

- `reddit_signal: str = ""` → `community_signals: list[str] = []`.
- `SHEET_COLUMNS`: `"reddit_signal"` → `"community_signals"`, same position (between
  `linkedin` and `outreach_angle`).
- `to_sheet_row`'s newline-join group: `("key_news", "buying_signals")` →
  `("key_news", "buying_signals", "community_signals")`.

### Tests

- `tests/test_enrich.py`: rename `find_reddit_signal` references to
  `find_community_signals`; update `test_reddit_signal_is_title_plus_link` to assert the
  broadened query string (all 4 `site:` clauses present) and that it returns a list capped
  at 5; update the `enrich()` test to assert `p.community_signals` is a non-empty list;
  update the empty-result test to assert `p.community_signals == []`; update the
  `build_signal_prompt` shape test's `Prospect(...)` construction from `reddit_signal=` to
  `community_signals=` and assert the new evidence line + the expanded angle instruction
  text appear in the prompt.
- `tests/fixtures/enrich_teal.json`: `"reddit_signal": "..."` → `"community_signals":
  ["..."]` (existing single value becomes a one-item list; fixture's Serper response mock
  should also cover a second/third hit if the fixture drives `find_community_signals`
  directly, otherwise the single-item list is sufficient for a merge/state fixture).
- Schema/output test covering `to_sheet_row`: assert `community_signals` renders
  newline-joined like `key_news`/`buying_signals`.

### Docs

- `docs/PLAN.md` line 40: `reddit_signal` → `community_signals` in the field list.
- `docs/data-flow.html` line 242: same rename in the enrich-stage record diagram.

## Out of scope

- No change to `merge_signals` in `gtm/run.py` — it only merges `buying_signals` and
  `outreach_angle`; `community_signals` is set directly by `enrich()`, unaffected.
- No change to `gtm/draft.py` or `qa_check` — `community_signals` was never fed into the
  draft prompt or QA evidence (only `buying_signals`/`key_news`/`fit_reason` are), and
  stays that way; it continues to flow into `buying_signals`/`outreach_angle` synthesis via
  `build_signal_prompt`, same as `reddit_signal` did.
- No new Serper call — same 1-query-per-field budget as before, just a broader query
  string and a `[:5]` slice instead of first-match-only.
