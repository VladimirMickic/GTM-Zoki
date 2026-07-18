"""S7a — stage 1 discover: NL query → Serper → gpt-4o-mini filters to real makers.

No approval step (decision locked): listicles/blogs/resellers are dropped by the
filter, domains deduped, capped at brief.max_companies.
"""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel

from gtm.contacts import serper_search
from gtm.costlog import CostLog
from gtm.extract import MODEL, PRICE_IN, PRICE_OUT, ExtractError

FILTER_PROMPT = """You are filtering Google results for a B2B prospecting pipeline.
For each result decide if it is the website of a company that MANUFACTURES drones
(is_manufacturer=true) vs a blog/listicle/news site/marketplace/reseller (false).
Extract the company name from the title/domain. Keep every result, one candidate each."""


class Candidate(BaseModel):
    company: str
    website: str
    is_manufacturer: bool


class CandidateList(BaseModel):
    candidates: list[Candidate] = []


def _domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def discover(
    query: str,
    max_companies: int = 10,
    *,
    search=serper_search,
    client=None,
    costlog: CostLog | None = None,
) -> list[Candidate]:
    results = search(query, num=10)
    if not results:
        return []
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    serp_text = "\n".join(f"- {r.get('title', '')} | {r.get('link', '')} | {r.get('snippet', '')}" for r in results)
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "system", "content": FILTER_PROMPT}, {"role": "user", "content": serp_text}],
        response_format=CandidateList,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="discover",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ExtractError("discover filter returned no parsed result")

    out, seen = [], set()
    for c in parsed.candidates:
        d = _domain(c.website)
        if c.is_manufacturer and d and d not in seen:
            seen.add(d)
            out.append(c)
        if len(out) >= max_companies:
            break
    return out
