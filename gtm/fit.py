"""S3 — fit scoring vs company/ICP.md.

Claude (the orchestrator) does the judgment: build_fit_prompt() → Claude answers with
FitResult JSON. Python does the deterministic part: hard disqualifiers it can prove
(all airframes under 250g = toy/hobby) and threshold → status mapping.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from gtm.extract import DroneExtraction
from gtm.schema import Prospect

TOY_WEIGHT_G = 250

_WEIGHT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|lbs?|oz)\b", re.I)
_TO_GRAMS = {"g": 1.0, "kg": 1000.0, "lb": 453.6, "lbs": 453.6, "oz": 28.35}


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


def check_disqualifiers(ex: DroneExtraction) -> str | None:
    """Deterministic pre-checks only; textual disqualifiers are Claude's call."""
    weights = _weights_g(ex.drone_weights)
    if weights and max(weights) < TOY_WEIGHT_G:
        return f"toy/hobby: heaviest airframe {max(weights):.0f}g < {TOY_WEIGHT_G}g"
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
- us_made_ndaa: {ex.us_made_ndaa}

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
