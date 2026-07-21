"""Classify a contact's job title into a seniority tier for persona-based email
tailoring. Pure Python, no LLM. The *doctrine* for each tier (what to pitch) lives
in company/voice-guide.md — this module only labels the tier."""
from __future__ import annotations

import re

# Checked high-to-low, first match wins. Finance is checked before c-suite so a
# CFO/"Chief Financial Officer"/"VP of Finance" lands in finance, not the generic
# exec bucket. VP/president = exec tier deliberately. Director split out of manager.
_FINANCE = ("cfo", "controller", "comptroller", "treasurer", "finance", "financial")
_C_SUITE = (
    "founder", "owner", "ceo", "cto", "coo", "chief",
    "president", "vice president", "vp",
)
_DIRECTOR = ("director", "head of")
_MANAGER = ("manager", "operations", "program", "logistics", "lead")


def classify_persona(title: str) -> str:
    t = title.lower().strip()
    if not t:
        return "unknown"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _FINANCE):
        return "finance"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _C_SUITE):
        return "c-suite"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _DIRECTOR):
        return "director"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _MANAGER):
        return "manager"
    return "ic"
