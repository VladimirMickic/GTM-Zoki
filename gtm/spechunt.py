"""Pre-fit evidence hunt — when the site doesn't publish dims or case info, search the
wider web (specs pages, reviews, Reddit, unboxings) before fit is judged.

Runs in cmd_start for any company missing drone_dimensions or case_evidence, so a huge
military airframe is caught by real dimensions, and the upgrade-gap signal gets scored
on evidence instead of a placeholder (feedback 2026-07-18). 2 Serper credits + one
gpt-4o-mini call per hunted company.
"""
from __future__ import annotations

from pydantic import BaseModel

from gtm.contacts import serper_search
from gtm.costlog import CostLog
from gtm.extract import MODEL, PRICE_IN, PRICE_OUT

HUNT_PROMPT = """You extract drone facts from Google search snippets for one company.
Only state what the snippets support — leave fields empty when unsure.
- drone_dimensions: physical L x W x H only, verbatim with units, prefixed by model when
  stated, noting folded/unfolded (e.g. "X10: 13.7 x 9.8 x 4.6 in folded"). No performance specs.
- drone_weights: airframe weights only, verbatim with units.
- case_evidence: 1-2 sentences on what the drone ships/packs in — hard case, soft bag,
  backpack, a named case partner — or empty if the snippets never say."""


class SpecFindings(BaseModel):
    drone_dimensions: list[str] = []
    drone_weights: list[str] = []
    case_evidence: str = ""


def build_spec_queries(company: str, models: list[str]) -> list[str]:
    subject = models[0] if models else company
    return [
        f'"{subject}" drone dimensions specs folded weight',
        f'"{company}" drone case OR "carrying case" OR backpack OR unboxing OR "ships with"',
    ]


def hunt_specs(
    company: str,
    models: list[str],
    *,
    search=serper_search,
    client=None,
    costlog: CostLog | None = None,
) -> SpecFindings:
    results = []
    for q in build_spec_queries(company, models):
        results.extend(search(q, num=10))
    if not results:
        return SpecFindings()
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    serp_text = "\n".join(
        f"- {r.get('title', '')} | {r.get('snippet', '')}" for r in results
    )
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": HUNT_PROMPT},
            {"role": "user", "content": f"Company: {company}\nModels: {models}\n\n{serp_text}"},
        ],
        response_format=SpecFindings,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="spechunt",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        return SpecFindings()
    parsed.drone_dimensions = [d for d in parsed.drone_dimensions if d.strip()]
    parsed.drone_weights = [w for w in parsed.drone_weights if w.strip()]
    return parsed
