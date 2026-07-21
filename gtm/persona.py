"""Classify a contact's job title into a seniority tier for persona-based email
tailoring. Pure Python, no LLM. The *doctrine* for each tier (what to pitch) lives
in company/voice-guide.md — this module only labels the tier."""
from __future__ import annotations

import re

from gtm.schema import CONTACT_FIELD_SEP

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


def distinct_tiers_present(contact_titles: str) -> list[str]:
    """contact_titles: the CONTACT_FIELD_SEP-joined Prospect.contact_title field.
    Returns distinct classify_persona() tiers, in first-seen order. Blank/empty
    titles produce ["unknown"] (a single default draft, never zero)."""
    titles = [t.strip() for t in contact_titles.split(CONTACT_FIELD_SEP)] if contact_titles else [""]
    tiers: list[str] = []
    for t in titles:
        tier = classify_persona(t)
        if tier not in tiers:
            tiers.append(tier)
    return tiers
