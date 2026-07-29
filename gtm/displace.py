"""New stage: turn a detected competitor case into cited email ammo.

detect_competitor() is pure Python (regex against case_evidence, already
extracted by gtm/extract.py) — zero extra LLM cost, credit-efficient per
CLAUDE.md. build_displacement_prompt() is a Claude-checkpoint prompt, same
pattern as gtm/enrich.py::build_signal_prompt — Claude does the research
judgment (via the reddit-find and company-research skills), Python only
builds the prompt and detects the trigger.
"""
from __future__ import annotations

import re

# Canonical home for the rugged-case-brand keyword list — gtm/segment.py
# imports this rather than keeping its own copy.
_RUGGED_BRANDS = ("pelican", "seahorse", "nanuk", "skb", "hardigg", "explorer case")

# In-house enclosures — the OEM builds and warehouses its own housing for the
# airframe (a drone-in-a-box dock, a self-tooled hard case). Ordered most
# specific first; the first match names the label. Detected in 2026-07-28 after
# run test-batch-1 mislabeled Easy Aerial (a DiB vendor) as having no case
# situation at all, because only third-party brands were detectable.
_INHOUSE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"drone[\s-]?in[\s-]?a[\s-]?box", re.IGNORECASE), "drone-in-a-box enclosure"),
    (re.compile(r"\bdock(?:ing)?\s+station\b", re.IGNORECASE), "docking station"),
    (re.compile(r"\bbase\s+station\b", re.IGNORECASE), "base station enclosure"),
    # "ground station" houses the aircraft; "ground CONTROL station" is a
    # handheld/laptop controller and never matches this pattern.
    (re.compile(r"\bground\s+station\b", re.IGNORECASE), "base station enclosure"),
    (
        re.compile(
            r"\b(?:our own|its own|their own|in[\s-]house|proprietary|self[\s-]tooled|custom[\s-]molded|"
            r"custom[\s-]moulded|purpose[\s-]built)\b[^.]{0,60}?\b(?:case|enclosure|housing|container|box)\b",
            re.IGNORECASE,
        ),
        "OEM-built case",
    ),
    # An unbranded case that simply ships with the drone: someone tooled it, and
    # since no third-party brand is named it is the OEM's own supply line.
    (re.compile(r"\b(?:include[sd]?|ships? (?:with|in)|comes with)\b[^.]{0,40}?\bhard(?:[\s-]shell)?\s+case\b", re.IGNORECASE), "OEM-supplied hard case"),
)

_MODEL_TOKEN = re.compile(r"\b\d[\dA-Za-z-]*\b")
# Spec-rating shapes that look like model numbers but aren't — never treat a
# match as a competitor model number if it also matches one of these.
_SPEC_SHAPES = (
    re.compile(r"^IP\d+$", re.IGNORECASE),
    re.compile(r"^\d+MM$", re.IGNORECASE),
)
_MIL_STD_TOKEN = re.compile(r"MIL-STD", re.IGNORECASE)


def detect_competitor(case_evidence: str) -> str:
    """Deterministic brand detection, no LLM call. Returns "<Brand>" or
    "<Brand> <model>" (e.g. "Pelican 1520") when a model-number-shaped token
    appears in the same short evidence string, "" if no known brand matches.

    Model tokens must start with a digit and must not be a spec-rating shape
    (IP67, 5mm) or a MIL-STD reference — those are common in the same
    sentence as a competitor case but are not the case's model number."""
    evidence = case_evidence or ""
    lowered = evidence.lower()
    for brand in _RUGGED_BRANDS:
        idx = lowered.find(brand)
        if idx == -1:
            continue
        name = "Explorer Case" if brand == "explorer case" else brand.title()
        remainder = evidence[idx + len(brand):]
        model = None
        for candidate in _MODEL_TOKEN.finditer(remainder):
            token = candidate.group()
            if any(shape.match(token) for shape in _SPEC_SHAPES):
                continue
            # A MIL-STD reference like "MIL-STD-810" trails a numeric token
            # ("810") right after the "MIL-STD" text — skip it.
            preceding = remainder[: candidate.start()]
            if _MIL_STD_TOKEN.search(preceding[-10:]):
                continue
            model = candidate
            break
        return f"{name} {model.group()}" if model else name
    return ""


def detect_inhouse_case(case_evidence: str) -> str:
    """Deterministic detection of an OEM-built enclosure, no LLM call. Returns a
    short label ("drone-in-a-box enclosure", "docking station", "OEM-built case",
    ...) or "" when the evidence shows no self-built housing.

    Defers to detect_competitor: if a third-party rugged brand is named in the
    same evidence string, that case is bought, not built, and the named-brand
    displacement pitch owns it."""
    evidence = case_evidence or ""
    if detect_competitor(evidence):
        return ""
    for pattern, label in _INHOUSE_PATTERNS:
        if pattern.search(evidence):
            return label
    return ""


def build_displacement_prompt(company: str, competitor: str, *, inhouse: bool = False) -> str:
    if inhouse:
        return f"""Research displacement ammo for {company}, who build and ship their own
{competitor} rather than buying a case from anyone (an OEM in-house enclosure, not a
third-party product).

This is the harder, higher-value pitch: we are not replacing a competitor's case, we are
taking over a manufacturing line they run themselves. Use the reddit-find and
company-research skills — not a single search — to find 2-3 concrete, cited costs or
complaints about carrying that enclosure in-house: tooling and mold spend, warehousing
and spares, field failures or damage reports from operators, lead-time or revision pain
when the airframe changes. Plain English, one line each: "<cost or complaint> — <source/context>".

Reply with ONLY this JSON (no prose), keyed by company name:
{{"{company}": {{"competitor_weaknesses": ["...", "..."]}}}}"""

    return f"""Research displacement ammo for {company}, whose drones currently ship in a
{competitor} case (a named competitor product, not ours).

Use the reddit-find and company-research skills — not a single search — to find 2-3
concrete, cited weaknesses or complaints about the {competitor} specifically (e.g. "too
heavy", "cracks in cold weather", reddit threads calling it out by name). Plain English,
one line per weakness: "<complaint> — <source/context>".

Reply with ONLY this JSON (no prose), keyed by company name:
{{"{company}": {{"competitor_weaknesses": ["...", "..."]}}}}"""
