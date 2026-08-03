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
