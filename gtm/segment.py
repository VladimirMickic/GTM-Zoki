"""New stage: deterministic bucketing into one of ICP.md's 4 outreach angles.

Pure Python, no LLM call — assign_segment() picks which angle draft's prompt
should lean into. Checked in priority order (first match wins): the highest-
weighted Fit signal (NDAA/defense) is the strongest hook when present; a named
competitor (gtm/displace.py) is a stronger, more specific hook than a blank
slate.
"""
from __future__ import annotations

from gtm.displace import detect_competitor
from gtm.schema import Prospect

_UPGRADE_KEYWORDS = ("soft bag", "backpack", "soft case", "generic case", "foam insert")
_LAUNCH_KEYWORDS = ("launch", "new model", "unveil", "announc")


def assign_segment(p: Prospect) -> str:
    if p.us_made_ndaa is True:
        return "defense-ndaa-win"

    if detect_competitor(p.case_evidence):
        return "competitor-displacement"

    evidence = p.case_evidence.lower()
    if any(kw in evidence for kw in _UPGRADE_KEYWORDS):
        return "generic-case-upgrade"

    if any(kw in s.lower() for s in p.buying_signals for kw in _LAUNCH_KEYWORDS):
        return "new-model-launch"

    return "field-harsh-environment"
