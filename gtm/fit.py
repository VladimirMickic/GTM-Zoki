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
    fit_score: int = Field(ge=0, le=80)
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


# A company whose airframe was never identified cannot be a top-tier prospect for a
# case built around a specific airframe. Run us-drone-20 scored Anduril 83/100 —
# priority tier, full drafted outreach — from a one-sentence description, with
# drone_models and drone_dimensions both empty. Three of its five rubric lines were
# scored from prior knowledge of a famous company; on an unknown maker they'd be 0.
NO_AIRFRAME_CAP = 48  # 0-80 provisional scale (rescaled from 60/100 on 2026-07-31);
# top of the provisional "keep" band — still worth a look, never a priority


def evidence_cap(ex: DroneExtraction) -> int | None:
    """NO_AIRFRAME_CAP when neither a model name nor a dimension triple was found,
    else None. Deliberately does NOT consider drone_weights: a weight in prose
    ("approximately 12 lbs") is not an identified airframe, it's a number in a
    sentence — that is exactly the evidence Anduril was scored 22/30 on."""
    if not ex.drone_models and not ex.drone_dimensions:
        return NO_AIRFRAME_CAP
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

Geography is NOT a scoring factor, in either direction. We ship worldwide, and where a
company is headquartered tells us nothing about whether our case fits its airframe or
whether it can pay for one. Never award points for a US HQ and never deduct points for a
foreign one, and never mention geography or the US as a requirement in fit_reason. If a
run's brief asked for US/NDAA companies only, that filtering already happened before this
prospect reached you — it is not something to re-apply here as a score. `us_made_ndaa`
and `compliance_evidence` are procurement evidence, not geography, but they are also not
yours to score: like the rest of Budget/procurement, they are scored later, in Python,
from enrichment data you do not have — do not score them and do not mention them here.

Size is the only hard disqualifier, and both of its bounds are already checked
deterministically before you see this. Set `disqualified: true` only if the text shows a
size problem the dimension parser could not (e.g. the spec sheet describes a 6-metre
wingspan in prose with no L×W×H triple). Do NOT set it for being foreign, indoor-only,
software-only, or a reseller — those are score penalties inside the rubric.

Score ONLY the three scrape-phase criteria, out of 80 total: Physical fit /35,
Field-deployed /25, Displacement opportunity /20. Budget/procurement is scored later,
in Python, from enrichment data you do not have — do not score it and do not mention it.

Score ONLY from the fields listed above. What you already know about this company from
training is NOT evidence, however confident you are and however famous the company. If a
field is empty, the criterion it feeds scores its bottom band — the ICP's bottom band is
always "no evidence found", never a midpoint. A score you cannot trace to a field above
is the failure this instruction exists to prevent: it looks like a finding, and on a
company you have never heard of it silently collapses to zero.

Never score a band whose stated evidence requirement you did not find. If the band table
says "named programme or certification" and you found none, you are not in that band, no
matter what else the company is.

fit_reason format — one line per scrape-phase criterion, newline-separated ("\\n" in the
JSON string):

  "<Criterion> <score>/<max> — [field: <field name>] <plain-English why>"

<field name> is the exact field you read it from: description, drone_models,
drone_dimensions, drone_weights, case_evidence — or the literal "none found" when
nothing supported the score, which must then be the bottom band. (compliance_evidence and
us_made_ndaa feed Budget/procurement, which you do not score — never cite them here.)
Plain English only: expand any jargon or acronym on first use (e.g. "SRR (Short Range
Reconnaissance)"), and say "inferred" explicitly when a judgment is inferred rather than
published.

Reply with ONLY this JSON (no prose):
{{"fit_score": <0-80>, "fit_reason": "<one line per criterion, as specified above>",
"best_case_line": "<AV-Micro|AV-Field|AV-Ops|AV-Convoy|>", "disqualified": <true|false>}}"""


def apply_fit(p: Prospect, fit: FitResult, *, cap: int | None = None) -> Prospect:
    p.fit_score = min(fit.fit_score, cap) if cap is not None else fit.fit_score
    p.fit_reason = fit.fit_reason
    if cap is not None and fit.fit_score > cap:
        p.fit_reason += (
            f"\nEvidence cap applied — no airframe identified (no model name, no "
            f"dimensions); raw score {fit.fit_score} capped to {cap}."
        )
    p.best_case_line = fit.best_case_line
    # Provisional (pre-enrich) gate on the 0-80 scrape-phase scale — rescaled 2026-07-31
    # from the old 70/40 (0-100) thresholds: 70*0.8=56, 40*0.8=32. This is deliberately
    # NOT the same as the final 70/40 bands applied to the assembled 100-point total
    # after gtm/run.py::apply_budget_scores runs — do not "fix" these back to 70/40.
    if fit.disqualified or p.fit_score < 32:
        p.status = "drop"
    elif p.fit_score >= 56:
        p.status = "priority"
    else:
        p.status = "keep"
    return p
