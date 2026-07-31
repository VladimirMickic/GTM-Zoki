"""S7a — stage 1 discover: NL query → Serper → gpt-4o-mini filters to real makers.

No approval step (decision locked): listicles/blogs/resellers are dropped by the
filter, domains deduped, capped at brief.max_companies.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from gtm.contacts import serper_search
from gtm.costlog import CostLog
from gtm.extract import MODEL, PRICE_IN, PRICE_OUT, ExtractError

FILTER_PROMPT = """You are filtering Google results for a B2B prospecting pipeline.
For each result decide if it is the website of a company that MANUFACTURES drones
(is_manufacturer=true) vs a blog/listicle/news site/marketplace/reseller (false).
Reseller/dealer giveaways (always false): sells multiple brands' drones (e.g. DJI +
Autel + Freefly on one site), shop/store/bundle/dealer language, "solutions" or
"NDAA-compliant drones" catalog landing pages that list other makers' aircraft.
A manufacturer sells only its own airframes. When unsure, mark false.
The link must be the manufacturer's own domain: a news/media/trade site writing ABOUT
a maker is false even if the company itself qualifies — we need their site, not coverage.
Extract the company name from the title/domain. Keep every result, one candidate each."""


class Candidate(BaseModel):
    company: str
    website: str
    is_manufacturer: bool


class CandidateList(BaseModel):
    candidates: list[Candidate] = []


DENYLIST_FILE = "company/denylist.md"


def _domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


# Words that say "drone company" rather than *which* drone company. Matched alone they
# hand any industry domain to any maker: "US Drone Makers" claimed dronelife.us off the
# bare token "drone". Only barred as standalone candidates — joined forms ("tealdrones")
# stay, because those are distinctive.
GENERIC_NAME_TOKENS = {
    "aerial", "aeronautics", "aerospace", "aviation", "company", "corp", "corporation",
    "defense", "drone", "drones", "group", "holdings", "inc", "industries", "international",
    "llc", "ltd", "maker", "makers", "robotics", "solutions", "systems", "tech",
    "technologies", "technology", "uas", "uav", "unmanned",
}


def _name_matches_domain(company: str, domain: str) -> bool:
    """True if the company's name plausibly owns the domain (guards against
    articles/listicles ABOUT a maker passing with the publisher's URL)."""
    tokens = re.findall(r"[a-z0-9]+", company.lower())
    if not tokens:
        return False
    candidates = {t for t in tokens if len(t) >= 4 and t not in GENERIC_NAME_TOKENS}
    candidates.update(a + b for a, b in zip(tokens, tokens[1:]))  # "red cat" → "redcat"
    candidates.add("".join(tokens))
    domain_flat = re.sub(r"[^a-z0-9]", "", domain.lower())
    if any(c in domain_flat for c in candidates):
        return True
    # A short distinctive token ("AAI Corporation" at aai.com) can't be substring-matched
    # — 3 letters hit half the web — so it has to BE the domain's own label. Checking only
    # the first label keeps a country-code TLD from lending "us"/"co" to a listicle.
    label = domain.lower().split(".")[0]
    return any(2 <= len(t) <= 3 and t == label for t in tokens)


def load_denylist(path: str | Path = DENYLIST_FILE) -> set[str]:
    """Domains discover() must never emit: '- <domain> — <reason>' lines, prose ignored."""
    path = Path(path)
    if not path.exists():
        return set()
    domains = set()
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("- "):
            domain = line.lstrip()[2:].split()[0]
            domains.add(domain.removeprefix("www."))
    return domains


_US_CLAUSE = '(NDAA OR "Blue UAS" OR "made in USA" OR "US-made")'

# Region codes worth spelling out for a search engine; anything else is used verbatim,
# so `region: "Nordics"` works without a code change.
_REGION_PHRASES = {"us": "United States", "uk": "United Kingdom", "eu": "Europe", "ca": "Canada"}


def region_query(query: str, region: str, *, require_us: bool = False) -> str:
    """Append the region phrase unless the query already carries it, or `require_us`
    already narrowed the search to the US (stacking both over-constrains the SERP)."""
    region = (region or "").strip()
    if not region or (require_us and region.lower() == "us"):
        return query
    phrase = _REGION_PHRASES.get(region.lower(), region)
    if phrase.lower() in query.lower() or region.lower() in query.lower().split():
        return query
    return f"{query} {phrase}"


def discover(
    query: str,
    max_companies: int = 10,
    *,
    search=serper_search,
    client=None,
    costlog: CostLog | None = None,
    denylist: set[str] | None = None,
    require_us: bool = False,
    region: str = "",
) -> list[Candidate]:
    """`require_us` and `region` are the only places geography enters the pipeline. Both
    narrow the *search*, so a geography-scoped run costs the same and the fit rubric
    downstream stays geography-blind. `require_us` is the strict NDAA/Blue-UAS form;
    `region` (2026-07-30, `Brief.region`, default "us") is the soft default that stops a
    missing region from being a blocking question."""
    if denylist is None:
        denylist = load_denylist()
    if require_us and "ndaa" not in query.lower():
        query = f"{query} {_US_CLAUSE}"
    query = region_query(query, region, require_us=require_us)
    results = search(query, num=max(10, max_companies * 4))
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
        if c.is_manufacturer and d and d not in seen and d not in denylist and _name_matches_domain(c.company, d):
            seen.add(d)
            out.append(c)
        if len(out) >= max_companies:
            break
    return out
