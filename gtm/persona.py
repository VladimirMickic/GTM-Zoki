"""Classify a contact's job title into a seniority tier for persona-based email
tailoring. Pure Python, no LLM. The *doctrine* for each tier (what to pitch) lives
in company/voice-guide.md — this module only labels the tier."""
from __future__ import annotations

import re

# checked high-to-low, first match wins. VP/president = exec tier deliberately.
_C_SUITE = (
    "founder", "owner", "ceo", "cto", "coo", "cfo", "chief",
    "president", "vice president", "vp",
)
_MANAGER = ("director", "head of", "manager", "operations", "program", "logistics", "lead")


def classify_persona(title: str) -> str:
    t = title.lower().strip()
    if not t:
        return "unknown"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _C_SUITE):
        return "c-suite"
    if any(re.search(rf"\b{re.escape(kw)}\b", t) for kw in _MANAGER):
        return "manager"
    return "ic"
