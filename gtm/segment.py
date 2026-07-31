"""New stage: deterministic bucketing into one of ICP.md's 4 outreach angles.

Pure Python, no LLM call — assign_segment() picks which angle draft's prompt
should lean into. Checked in priority order (first match wins), most specific
hook first:

1. competitor-displacement    — a named incumbent case (gtm/displace.py)
2. oem-inhouse-displacement   — they build their own enclosure (dock, DiB, molded case)
3. generic-case-upgrade       — a soft/generic case, upgrade with no named target
4. new-model-launch           — a fresh airframe that needs a case built around it
5. procurement-compliance-win — a procurement credential, any country
6. field-harsh-environment    — fallback

Compliance sits *late* on purpose. Until 2026-07-28 it was checked first and
returned immediately, but NDAA compliance is near-universal among the makers
this ICP targets, so ~every qualified prospect collapsed into that one bucket
and four of five branches were unreachable — the drafts in run test-batch-1
read near-identically for exactly this reason. A procurement credential says
the buyer *can* spend; a competitor case or a new airframe says what to open
the email with, which is the more specific hook.
"""
from __future__ import annotations

from gtm.displace import detect_competitor, detect_inhouse_case
from gtm.schema import Prospect

_UPGRADE_KEYWORDS = ("soft bag", "backpack", "soft case", "generic case", "foam insert")
_LAUNCH_KEYWORDS = ("launch", "new model", "unveil", "announc")


def assign_segment(p: Prospect) -> str:
    if detect_competitor(p.case_evidence):
        return "competitor-displacement"

    # An OEM that tools its own enclosure (drone-in-a-box dock, self-molded hard
    # case) is the highest-value displacement target, not the lowest — the pitch
    # is "stop running a case factory", not "swap your Pelican". Checked before
    # the generic-upgrade keywords, which a DiB spec sheet often also trips.
    if detect_inhouse_case(p.case_evidence):
        return "oem-inhouse-displacement"

    evidence = p.case_evidence.lower()
    if any(kw in evidence for kw in _UPGRADE_KEYWORDS):
        return "generic-case-upgrade"

    if any(kw in s.lower() for s in p.buying_signals for kw in _LAUNCH_KEYWORDS):
        return "new-model-launch"

    # Geography-neutral (ICP.md "Budget & procurement"): NDAA is one
    # route into this bucket, a NATO stock number or national MoD framework is
    # another. The segment name is interpolated straight into the draft prompt,
    # so it must not carry US program wording onto a non-US prospect.
    if p.us_made_ndaa is True or p.compliance_evidence.strip():
        return "procurement-compliance-win"

    return "field-harsh-environment"
