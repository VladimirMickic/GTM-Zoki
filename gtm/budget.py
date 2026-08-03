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
    # award(?:s|ed|ee)? — NOT `awarded?`, which parses as `awarde` + optional `d` and so
    # matches neither the bare noun "award" nor the far more common verb "awards".
    r"\b(contracts?|task order|award(?:s|ed|ee)?|procurement|framework|NDAA|Blue UAS|"
    r"NATO stock number|type certification|BVLOS)\b",
    re.IGNORECASE,
)
# The word alternatives each carry their own \b; the dollar alternative must NOT, because
# a leading \b before "$" demands a word character immediately before the "$" — which never
# happens in prose, so the whole branch was dead. Keep the two halves separated at the top
# level of the alternation.
_CAPITAL_RE = re.compile(
    r"\b(?:series\s+[a-h]\b|raise[sd]?\b|raising\b|funding round\b|seed round\b)"
    r"|\$[\d.]+\s*(?:m|b|million|billion)\b",
    re.IGNORECASE,
)

# --- False-positive vetoes (2026-08-03). Both regexes above were widened on 2026-08-02
# and each widening brought a class of headline that is not evidence this company can pay
# for or procure anything. Both vetoes are applied per news item, never to the joined
# blob, so one bad headline cannot lend its points to an unrelated one. ---

# Market-size and forecast journalism: "Drone market to hit $12 billion by 2030". The
# dollar figure is the industry's, not the company's. Deliberately keyed on the subject
# noun (market/industry/sector) or the analyst framing, NOT on the word "billion" — a real
# raise can be that big, and Anduril's $1.5B Series G must keep its points.
_MARKET_SIZE_RE = re.compile(
    r"\b(?:market|industry|sector|segment)\b[^.]{0,60}?\$[\d.]+\s*(?:m|b|million|billion)\b"
    r"|\$[\d.]+\s*(?:m|b|million|billion)\b[^.]{0,60}?\b(?:market|industry|sector|segment)\b"
    r"|\b(?:forecast|projected|projection|expected to reach|to reach|to hit|estimated at|"
    r"valued at|worth|cagr|analysts?)\b[^.]{0,60}?\$[\d.]+\s*(?:m|b|million|billion)\b",
    re.IGNORECASE,
)

# Trophies, not contracts: "wins an Edison Award", "award-winning". These veto ONLY the
# weak bare-`award` branch of _AWARD_RE (see _has_award below) — a headline naming a real
# contract, task order or certification keeps its points even when it also mentions a
# trophy. Known cost: a genuinely procurement-flavoured "Innovation Award" (AFWERX and
# friends) loses its points here, which is acceptable because those items almost always
# also say "contract" or "SBIR" and are caught by the strong branch instead.
_TROPHY_RE = re.compile(
    r"\baward[- ]winning\b"
    r"|\bawards?\s+(?:season|show|ceremony|gala|night|finalists?|categor\w+)\b"
    r"|\b(?:finalist|shortlisted|nominee|nominated|honou?ree)\b[^.]{0,40}?\bawards?\b"
    r"|\b(?:edison|innovation|design|product|startup|excellence|breakthrough|"
    r"best[- ]of[- ]\w+|people'?s\s+choice|readers'?\s+choice)\s+awards?\b",
    re.IGNORECASE,
)
# The half of _AWARD_RE that survives a trophy veto — everything except bare `award(s)`.
# `awarded`/`awardee` stay here: nobody is "awarded" an Edison, they win one.
_STRONG_AWARD_RE = re.compile(
    r"\b(contracts?|task order|award(?:ed|ee)|procurement|framework|NDAA|Blue UAS|"
    r"NATO stock number|type certification|BVLOS)\b",
    re.IGNORECASE,
)


def _has_award(item: str) -> bool:
    """Procurement evidence in one news item. The strong tokens stand on their own; the
    bare noun/verb `award(s)` only counts when the item is not trophy-shaped."""
    if _STRONG_AWARD_RE.search(item):
        return True
    return bool(_AWARD_RE.search(item)) and not _TROPHY_RE.search(item)


def _has_capital(item: str) -> bool:
    """Capital evidence in one news item, minus market-size journalism."""
    return bool(_CAPITAL_RE.search(item)) and not _MARKET_SIZE_RE.search(item)


_FIRST_INT = re.compile(r"\d+")
# Thousands separators inside a number, e.g. the comma in LinkedIn's own band labels
# ("1,001-5,000", "10,001+"), which _HEADCOUNT_PROMPT asks enrichment to reproduce verbatim.
_GROUPING = re.compile(r"[,\s](?=\d)")


def _headcount_points(headcount: str) -> tuple[int, str]:
    """Bands off the first integer in the string — enrichment writes exact counts
    ("7000") and LinkedIn-style ranges ("51-200", "5,001-10,000") interchangeably, and the
    low end of a range is the conservative read. Separators are stripped first, so a
    comma-grouped band reads as one number rather than as its leading digit run."""
    m = _FIRST_INT.search(_GROUPING.sub("", headcount or ""))
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

    # Per item, not over the joined list: the vetoes in _has_award/_has_capital are
    # judgments about one headline, and a blob lets a vetoed headline's neighbours
    # supply the words that clear it (2026-08-03).
    items = p.key_news or []
    news_award = any(_has_award(i) for i in items)
    news_capital = any(_has_capital(i) for i in items)

    if p.us_made_ndaa or (p.compliance_evidence or "").strip() or news_award:
        points += PROCUREMENT_POINTS
        if p.us_made_ndaa:
            fields.append("us_made_ndaa")
            whys.append("NDAA-compliant")
        if (p.compliance_evidence or "").strip():
            fields.append("compliance_evidence")
            whys.append(p.compliance_evidence.strip()[:60])
        elif news_award:
            fields.append("key_news")
            whys.append("award/procurement evidence in the news")

    head_points, head_why = _headcount_points(p.headcount)
    if head_points:
        points += head_points
        fields.append("headcount")
        whys.append(head_why)

    if news_capital:
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
