"""S3 — fit scoring vs company/ICP.md.

Claude (the orchestrator) does the judgment: build_fit_prompt() → Claude answers with
FitResult JSON. Python does the deterministic part: the two hard disqualifiers it can
prove — both of them size bounds — and threshold → status mapping.

Size is the ONLY hard constraint (locked 2026-07-28). Geography is not a constraint at
all: a non-US manufacturer is scored identically to a US one. Anything else that used to
auto-reject (indoor-only, software-only, reseller) is now a score penalty inside the
rubric, judged by Claude, not a deterministic rejection here.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from gtm.extract import DroneExtraction
from gtm.schema import Prospect

TOY_WEIGHT_G = 250
# AV-Convoy internal usable dimensions (company/ICP.md) — the largest case we make.
# An airframe whose folded footprint doesn't fit here is custom-quote only.
MAX_CASE_IN = (40.0, 24.0, 16.0)

_WEIGHT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|lbs?|oz)\b", re.I)
_TO_GRAMS = {"g": 1.0, "kg": 1000.0, "lb": 453.6, "lbs": 453.6, "oz": 28.35}

# "13.7 x 9.8 x 3.5 in", "685 × 385 × 175 mm", "13.7x9.8x3.5in" — three numbers joined
# by x/×/*, with the unit stated once at the end (the near-universal spec-sheet shape).
_DIMS = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(in|inch|inches|\"|mm|cm|m)?\b",
    re.I,
)
_TO_INCHES = {"in": 1.0, "inch": 1.0, "inches": 1.0, '"': 1.0,
              "mm": 1 / 25.4, "cm": 1 / 2.54, "m": 39.3701}
# An unlabelled triple is ambiguous. Spec sheets that omit the unit are overwhelmingly
# metric-mm (three 3-digit numbers) or imperial-inch (three small numbers); guessing
# wrong in the "too big" direction would silently drop a good prospect, so an
# unlabelled triple is never used for the oversize check at all — see _dims_inches.
_UNFOLDED = re.compile(r"\bunfolded|deployed|rotors? (?:out|extended)|arms? (?:out|extended)\b", re.I)


class FitResult(BaseModel):
    fit_score: int = Field(ge=0, le=100)
    fit_reason: str
    best_case_line: str  # AV-Micro / AV-Field / AV-Ops / AV-Convoy / ""
    disqualified: bool = False


def _weights_g(sizes: list[str]) -> list[float]:
    out = []
    for s in sizes:
        for num, unit in _WEIGHT.findall(s):
            out.append(float(num.replace(",", ".")) * _TO_GRAMS[unit.lower()])
    return out


def _dims_inches(sizes: list[str]) -> list[tuple[float, tuple[float, float, float]]]:
    """Every L×W×H triple found, normalized to inches and sorted descending, paired
    with nothing else. Unit-less triples are skipped: see _TO_INCHES' note — an
    unlabelled "685 x 385 x 175" is almost certainly mm, but acting on that guess
    would drop a perfectly good prospect if it were inches, and a false drop is the
    expensive error here. Unfolded/deployed dimensions are also skipped; the ICP's
    limit is explicitly on the *folded/packed* footprint."""
    out = []
    for s in sizes:
        if _UNFOLDED.search(s):
            continue
        for a, b, c, unit in _DIMS.findall(s):
            if not unit:
                continue
            factor = _TO_INCHES[unit.lower()]
            triple = tuple(sorted((float(x.replace(",", ".")) * factor for x in (a, b, c)), reverse=True))
            out.append((max(triple), triple))
    return out


def check_disqualifiers(ex: DroneExtraction) -> str | None:
    """Deterministic pre-checks only; every other judgment is Claude's call.

    Both checks are size bounds, because size is the only hard constraint
    (company/ICP.md, locked 2026-07-28). Geography is deliberately NOT checked —
    ex.us_made_ndaa is evidence for the Procurement & compliance rubric signal, never
    a gate."""
    weights = _weights_g(ex.drone_weights)
    if weights and max(weights) < TOY_WEIGHT_G:
        return f"toy/hobby: heaviest airframe {max(weights):.0f}g < {TOY_WEIGHT_G}g"

    # Oversize: the SMALLEST published folded footprint decides. A maker with a
    # 6-metre fixed-wing and a pocketable quad is still a prospect for the quad, so
    # only reject when nothing they publish fits AV-Convoy.
    dims = _dims_inches(ex.drone_dimensions)
    if dims:
        smallest_max, triple = min(dims)
        if not all(d <= limit for d, limit in zip(triple, MAX_CASE_IN)):
            fits = " × ".join(f"{d:.1f}" for d in triple)
            limit = " × ".join(f"{d:.0f}" for d in MAX_CASE_IN)
            return (
                f"oversize: smallest published folded footprint {fits} in exceeds "
                f"AV-Convoy {limit} in — custom-quote only"
            )
    return None


def build_fit_prompt(icp_text: str, company: str, ex: DroneExtraction) -> str:
    return f"""Score this drone manufacturer against our ICP. Apply the scoring weights and
hard disqualifiers exactly as written in the ICP.

## ICP
{icp_text}

## Prospect: {company}
- description: {ex.company_description}
- drone_models: {ex.drone_models}
- drone_dimensions: {ex.drone_dimensions}
- drone_weights: {ex.drone_weights}
- case_evidence (what they ship in today): {ex.case_evidence or "unknown — web hunt found nothing"}
- us_made_ndaa: {ex.us_made_ndaa}
- compliance_evidence (non-US procurement credentials): {ex.compliance_evidence or "none found"}
- hq_country: {ex.hq_country or "unknown"}

Geography is NOT a scoring factor. We ship worldwide, and where a company is
headquartered tells us nothing about whether our case fits its airframe or whether it
can pay for one. Score `us_made_ndaa: true` as one route into the top band of
"Procurement & compliance fit" — never as a bonus in its own right — and score a non-US
company on its own credentials (compliance_evidence) using exactly the same band table.
A non-US company with a national defense framework scores the same 12-15 as a US company
with Blue UAS. Never deduct points for a foreign HQ, and never mention the US as a
requirement in fit_reason.

Size is the only hard disqualifier, and both of its bounds are already checked
deterministically before you see this. Set `disqualified: true` only if the text shows a
size problem the dimension parser could not (e.g. the spec sheet describes a 6-metre
wingspan in prose with no L×W×H triple). Do NOT set it for being foreign, indoor-only,
software-only, or a reseller — those are score penalties inside the rubric.

fit_reason format — one line per ICP scoring signal, newline-separated ("\\n" in the JSON
string): "<Criterion> <score>/<max> — <plain-English why>". Plain English only: expand any
jargon/acronym on first use (e.g. "SRR (Short Range Reconnaissance)"), and say so explicitly
when a judgment is inferred rather than published (e.g. dimensions inferred from weight).

Reply with ONLY this JSON (no prose):
{{"fit_score": <0-100>, "fit_reason": "<one line per signal, as specified above>",
"best_case_line": "<AV-Micro|AV-Field|AV-Ops|AV-Convoy|>", "disqualified": <true|false>}}"""


def apply_fit(p: Prospect, fit: FitResult) -> Prospect:
    p.fit_score = fit.fit_score
    p.fit_reason = fit.fit_reason
    p.best_case_line = fit.best_case_line
    if fit.disqualified or fit.fit_score < 40:
        p.status = "drop"
    elif fit.fit_score >= 70:
        p.status = "priority"
    else:
        p.status = "keep"
    return p
