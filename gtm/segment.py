"""New stage: deterministic bucketing into one of ICP.md's 4 outreach angles.

Pure Python, no LLM call — assign_segment() picks which angle draft's prompt
should lean into. Checked in priority order (first match wins): the highest-
weighted Fit signal (NDAA/defense) is the strongest hook when present.
"""
from __future__ import annotations

from gtm.schema import Prospect

_UPGRADE_KEYWORDS = ("soft bag", "backpack", "soft case", "generic case", "foam insert")
_RUGGED_BRANDS = ("pelican", "seahorse", "nanuk", "skb", "hardigg", "explorer case")
_LAUNCH_KEYWORDS = ("launch", "new model", "unveil", "announc")


def assign_segment(p: Prospect) -> str:
    if p.us_made_ndaa is True:
        return "defense-ndaa-win"

    evidence = p.case_evidence.lower()
    has_upgrade_kw = any(kw in evidence for kw in _UPGRADE_KEYWORDS)
    has_brand = any(brand in evidence for brand in _RUGGED_BRANDS)
    if has_upgrade_kw and not has_brand:
        return "generic-case-upgrade"

    if any(kw in s.lower() for s in p.buying_signals for kw in _LAUNCH_KEYWORDS):
        return "new-model-launch"

    return "field-harsh-environment"
