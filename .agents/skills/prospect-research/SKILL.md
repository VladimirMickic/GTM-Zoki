---
name: prospect-research
description: Find and rank the real decision-makers at one drone-manufacturer prospect (name/title/LinkedIn), plus the outreach angle and buying signals to hand to cold-email. Use for a manual one-off deep dive outside a pipeline run (`gtm/run.py`) — for full 0-100 ICP scoring, run the pipeline's Fit stage instead, don't reproduce it by hand.
allowed-tools: Read, Write, WebSearch, WebFetch
---

# prospect-research

Manual companion to the pipeline's contact-discovery step (`gtm/contacts.py`'s
`find_contacts`, which only runs automatically for companies that already passed the
automated Fit stage). This skill exists for the case that stage doesn't cover: identifying
the right people at one company *before or outside* a full pipeline run.

**Not this skill's job:** full 0-100 ICP scoring. That's `gtm/fit.py`'s rubric, run via
`python -m gtm.run fit` — it's Claude judgment already automated end-to-end. Re-deriving the
weighted score by hand duplicates it and drifts out of sync the moment `ICP.md`'s rubric
changes. This skill only checks disqualifiers (cheap, and worth doing before spending
searches on a company that's an auto-reject) — never award a point score.

## Phase 0: Load ICP
Read `company/ICP.md` for the 5 disqualifiers, the 4 locked outreach angles, and the
buying-signals list. Don't invent angles or signals outside this file.

## Phase 1: Quick disqualifier gate
Two fast searches, enough to bail early — not a scoring pass:
1. `{company} drone specs weight class` — toy/hobby (<250g, sub-$500) or indoor/racing-only?
2. `{company} drone manufacturer OR reseller OR distributor` — do they actually make the
   hardware, or resell someone else's?

**Stop here** (skip to Phase 4, write as reject, no contact search) if either confirms a
disqualifier: toy/hobby class, indoor-only, software-only, pure reseller/distributor, or an
airframe already known to be too large for AV-Convoy.

## Phase 2: Find contacts
Same query pattern as the pipeline's `build_contact_query`:

```
site:linkedin.com/in "{company}" drone
```

For each result with `/in/` in the link: strip `| LinkedIn`/`- LinkedIn` from the title,
split on ` - ` (or ` – `/` — `) into name and title, drop a trailing `at {company}`/`@ {company}`.
Discard results without a `/in/` link (company pages, articles).

Rank candidates by title, highest first — same keyword weights as `gtm/contacts.py`'s
`_RANK_KEYWORDS` (first keyword match wins, case-insensitive whole-word):

| keyword | score | keyword | score |
|---|---|---|---|
| founder | 100 | head of | 80 |
| ceo | 95 | director | 75 |
| chief | 90 | operations | 70 |
| vp / vice president | 85 | product | 65 |
| | | program | 60 |
| | | logistics | 60 |
| | | sales | 50 |
| | | manager | 40 |

No keyword match → rank 0 (keep, don't discard — still a real lead). Take the top 3.

## Phase 3: Angle and signals
Pick exactly one outreach angle from `ICP.md`'s locked list (new model launch /
defense-NDAA win / field-harsh-environment marketing / generic-case-today) — the one best
supported by what Phase 1's search and any additional news search turned up, not the one
that sounds best. Note buying signals found (from `ICP.md`'s categories) and 1-3 dated
key-news items with sources.

## Phase 4: Output Brief
```
## Prospect Research: {company}

**Disqualified:** {no | which one, and the evidence}

**Top contacts** (ranked)
1. {name} — {title} — {linkedin url} (rank {score})
2. ...
3. ...

**Outreach angle:** {one of the 4 locked angles}
**Buying signals found:** {list}
**Key news:** {1-3 dated items with source}
```

Hand `outreach_angle`, `buying_signals`, `key_news`, and the top contact's title straight
to the `cold-email` skill — don't re-summarize them differently there. For the actual
priority score (0-100), run the pipeline's Fit stage rather than estimating one here.

## Quality Gates
- [ ] Disqualifier check ran before any contact search, not after
- [ ] No 0-100 fit score written anywhere in the output
- [ ] Contact ranking follows `_RANK_KEYWORDS` order, not a guessed ranking
- [ ] Zero-keyword-match contacts kept (ranked last), not discarded
- [ ] Outreach angle is one of ICP.md's 4, not invented

## Self-improvement
If, while running this skill, you get corrected on scope, a query pattern, the ranking
logic, or any other instruction here — edit this file to bake the correction in before you
finish. A correction that isn't written back just recurs next time, including in sessions
with no memory of this one (this skill is mirrored for both Claude Code and Codex via
`.agents/skills`, neither of which shares the other's session memory).
