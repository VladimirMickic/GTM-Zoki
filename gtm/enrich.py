"""S5 — enrichment for fit passers only (5 Serper credits per company: 1 linkedin,
2 community-signal pain queries, 1 headcount, 1 news).

Python gathers raw signals: company LinkedIn, top-3 pain-focused community signals
(gpt-4o-mini relevance/rewrite pass over 2 SERP queries), employee-count band
(gpt-4o-mini parse of a LinkedIn/Craft/PitchBook query), top-5 news with snippets.
Claude (orchestrator) synthesizes buying_signals + outreach_angle from them via
build_signal_prompt() — the company-research skill adds depth when run in-loop.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from gtm.contacts import serper_search
from gtm.extract import MODEL, PRICE_IN, PRICE_OUT
from gtm.schema import Prospect

MAX_NEWS = 5
SNIPPET_WORDS = 25


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_company_linkedin(company: str, *, search=serper_search) -> str:
    """Only accepts a /company/ result whose URL slug overlaps the target
    company name — a bare `"{company}"` quoted search can surface an unrelated
    company's page (2026-07-21: AeroVironment matched Blue Halo LLC's LinkedIn,
    because Blue Halo was mentioned alongside AV in an unrelated result)."""
    target = _normalize(company)
    for r in search(f'site:linkedin.com/company "{company}"', num=10):
        link = r.get("link", "")
        if "/company/" not in link:
            continue
        slug = _normalize(link.rstrip("/").rsplit("/company/", 1)[-1].split("/")[0])
        if slug and (slug in target or target in slug):
            return link
    return ""


def _news_line(r: dict) -> str:
    title, link = r.get("title", ""), r.get("link", "")
    words = r.get("snippet", "").split()
    snippet = " ".join(words[:SNIPPET_WORDS]) + (" …" if len(words) > SNIPPET_WORDS else "")
    return f"{title} — {snippet} ({link})" if snippet else f"{title} ({link})"


def find_news(company: str, *, search=serper_search) -> list[str]:
    q = f'"{company}" drone (contract OR launch OR funding OR award OR NDAA OR "Blue UAS")'
    results = search(q, num=10)
    return [_news_line(r) for r in results[:MAX_NEWS]]


MAX_COMMUNITY_SIGNALS = 3  # 2026-07-27: cap tightened when signals became pain-quote-shaped


_MIN_HANDLE_OVERLAP = 6  # chars; below this, a short handle (e.g. "teal") false-matches too easily


def _is_own_post(company: str, r: dict) -> bool:
    """A "{company}" X/Twitter/Reddit search surfaces the company's own account
    posting about itself (2026-07-24: "Inspired Flight Technologies" returned
    three near-duplicate lines all from @InspiredFlight1's own feed) — that's
    marketing, not a third-party community signal. Drop any result whose link
    or title carries a handle that's a (digit-stripped) prefix match against
    the company name."""
    company_norm = _normalize(company)
    link, title = r.get("link", "").lower(), r.get("title", "").lower()
    handles = []
    m = re.search(r"(?:x|twitter)\.com/@?([a-z0-9_]+)", link)
    if m:
        handles.append(m.group(1))
    m = re.search(r"@([a-z0-9_]+)", title)
    if m:
        handles.append(m.group(1))
    for h in handles:
        h_norm = re.sub(r"\d+$", "", _normalize(h))  # strip trailing version digits, e.g. "1"
        if len(h_norm) >= _MIN_HANDLE_OVERLAP and (
            company_norm.startswith(h_norm) or h_norm.startswith(company_norm)
        ):
            return True
    return False


_PAIN_SITES = "(site:reddit.com OR site:rcgroups.com OR site:x.com OR site:twitter.com)"
_PAIN_TERMS = '(case OR transport OR foam OR broke OR cracked OR damaged)'

# A third, brand-list query ("(Pelican OR Nanuk OR SKB OR …) drone case (too heavy
# OR …)") was tried on 2026-07-27 and removed the same day: it returned 0 raw hits
# from Serper for every company — too many OR groups stacked with a quoted phrase —
# so it only ever cost a credit. Don't re-add it without measuring raw hits first.

# Keyword → generic ICP segment phrase (company/ICP.md "Strong-fit segments"),
# used when a company has no direct chatter of its own — the common case. Kept
# generically-attributed in the query itself; the LLM pass below is instructed
# to never imply a category hit is specifically about the prospect.
_CATEGORY_KEYWORDS = (
    ("public safety drone", ("public safety", "first responder", "police", "fire department")),
    ("search and rescue drone", ("search and rescue",)),
    ("industrial inspection drone", ("industrial", "inspection")),
    ("survey and mapping drone", ("survey", "mapping", "gis")),
    ("utility inspection drone", ("energy", "utility", "utilities", "powerline")),
)


def _infer_category(p: Prospect) -> str:
    """Cheap keyword bucket into an ICP segment phrase — no LLM call. us_made_ndaa
    is the strongest, cheapest defense signal already on the Prospect; description
    keywords cover the rest of company/ICP.md's "Strong-fit segments" list.

    Deliberately reads only fields the extract/fit stages have already filled:
    buying_signals is written by cmd_signals, which runs after cmd_enrich, so it is
    always [] here."""
    if p.us_made_ndaa is True:
        return "defense sUAS"
    text = p.description.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return category
    return "field-deployed drone"


def _pain_queries(p: Prospect) -> list[str]:
    queries = []
    if p.drone_models:
        model = p.drone_models[0]  # flagship/first-listed only — bounds Serper cost
        # "drone" is load-bearing, not decoration: cold run 2026-07-27 searched the
        # bare token "X55" (Arcsky's airframe) and got 10/10 non-drone hits — a
        # PowKiddy handheld console, a 7.5x55 rifle cartridge, a TP-Link router.
        # Short alphanumeric model names collide across whole product categories.
        queries.append(f'"{model}" drone {_PAIN_TERMS} {_PAIN_SITES}')
    queries.append(f"{_infer_category(p)} {_PAIN_TERMS} {_PAIN_SITES}")
    return queries


class _Signal(BaseModel):
    quote: str
    source: str


class _SignalList(BaseModel):
    signals: list[_Signal] = []


_RELEVANCE_PROMPT = """You are filtering search results for a B2B pipeline that sells rugged
transport cases to drone manufacturers. Keep a result ONLY if it passes ALL THREE gates.

Gate 0 — it must be about a drone. The hardware being carried, stored, or damaged has to be
a drone, UAV, quadcopter, airframe, or its flight gear (controller, batteries, payload,
propellers, gimbal). Short model names collide across unrelated product categories: "X55" is
also a handheld games console and a router, "Perimeter 8" is also a phrase about hardware
fasteners. If the text does not show the thing is an aircraft, REJECT it — no matter how
perfectly it describes transport damage. A console damaged in shipping is not our signal.

Gate 1 — subject matter. The text must be about transporting, storing, shipping, or
protecting hardware: a case, hard case, bag, backpack, pelican-style box, foam insert,
padding, or the act of transit/shipping/hauling gear. If you cannot point to a word in the
text naming one of those things, REJECT it. Assembly, repair, firmware, flight performance,
parts counts, and general build chatter are NOT transport topics — REJECT them even when they
mention a drone and sound technical.

Gate 2 — real pain. A real person must describe something going wrong or costing them:
an airframe cracked or damaged in transit, foam collapsing or deteriorating, a case too
heavy, too big, or that doesn't fit, gear rattling loose, a case that failed in the field.
Neutral mentions, marketing copy, product listings, and satisfied reviews REJECT.

Also REJECT: a result that matched only because the words of a drone's model name appear in
an unrelated sentence (e.g. "Perimeter 8" matching "there are some snaps in the perimeter, 8
of them"). Judge the sentence's actual meaning, not the keyword overlap. In both this case
and Gate 0, the failure looks the same from the outside — the keywords line up and the
sentence reads well — so check what the words actually refer to before keeping anything.

Never invent or paraphrase into a quote — use only what the title/snippet actually says. A
category-level result naming no company is fine; do not claim or imply it is about any
specific company. Prefer rejecting a borderline result over keeping it — an empty list is a
correct and useful answer.

For each kept result:
- quote: the pain in the person's own words, trimmed to the relevant sentence.
- source: the domain (e.g. "reddit.com") or a short label (e.g. "RCGroups").
Keep at most 3, most concrete/specific first. If nothing qualifies, return an empty list."""


def _relevance_filter(results: list[dict], *, client=None, costlog=None) -> list[str]:
    if not results:
        return []
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    serp_text = "\n".join(
        f"- {r.get('title', '')} | {r.get('snippet', '')} | {r.get('link', '')}" for r in results
    )
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "system", "content": _RELEVANCE_PROMPT}, {"role": "user", "content": serp_text}],
        response_format=_SignalList,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="community_signals",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        return []
    return [f'"{s.quote}" ({s.source})' for s in parsed.signals[:MAX_COMMUNITY_SIGNALS]]


def find_community_signals(p: Prospect, *, search=serper_search, client=None, costlog=None) -> list[str]:
    """Pain-focused, not mention-focused (2026-07-27 redesign): airframe-specific
    and ICP-category queries, pooled and deduped, then a cheap gpt-4o-mini pass
    keeps only genuine pain quotes and rewrites each as '"<quote>" (<source>)' —
    ammo for gtm/draft.py's pain block, not raw SERP noise."""
    pooled, seen_links = [], set()
    for q in _pain_queries(p):
        for r in search(q, num=10):
            link = r.get("link", "")
            if link in seen_links:
                continue
            seen_links.add(link)
            pooled.append(r)
    third_party = [r for r in pooled if not _is_own_post(p.company, r)]
    return _relevance_filter(third_party, client=client, costlog=costlog)


class _Headcount(BaseModel):
    band: str = ""


_HEADCOUNT_PROMPT = """From the search results below, find the employee headcount for the
named company. Use ONLY the text in the search results below — you may already know real
facts about well-known companies from training, but ignore all of that here; if your own
knowledge disagrees with the results, or the results say nothing, still go only by the
results, and return an empty band rather than filling in what you already know.

FIRST, check the result is the same company, not a different one with a similar name. A
count only counts if the result is that company's own page. Match on the website/domain
given above the results, and sanity-check the industry and location: a company called
"Arcsky" at arcskytech.com that makes drones in Austin is NOT the airline "ARC" at
arcsky.com, even though both are aviation and the names look identical. When a result's
domain, industry, or location contradicts the company you were given, discard that result
entirely — do not fall back to it because it's the only number you can see.

Report the headcount EXACTLY as a source states it — a range ("51-200") or an exact
count ("171") are both fine, but never convert one into the other: don't turn "51 total employees"
into a range like "1-50" or "51-200", and don't turn "51-200 employees" into a single number.

Sources disagree often. If more than one number appears, prefer a linkedin.com page over
craft.co, pitchbook.com, or any other aggregator — it's the company's own listing. If the
only sources are non-LinkedIn and they disagree with each other (e.g. one site says "5
employees", another says "50"), that is unresolvable — return an empty band rather than
picking one.

Never estimate, round, or infer a count from unrelated numbers (revenue, funding, follower
counts, founding year). If nothing states an employee count for this company, return an
empty band. Reply with only the count/band string (e.g. "51-200" or "171"), not the word
"employees"."""


def _domain(website: str) -> str:
    """Bare domain for entity-matching in the headcount prompt — the rule "is this
    the same company?" is unusable without it (arcskytech.com vs arcsky.com)."""
    d = re.sub(r"^https?://", "", website.strip().lower())
    return d.split("/")[0].removeprefix("www.")


def _parse_headcount(
    company: str, website: str, results: list[dict], *, client=None, costlog=None
) -> str:
    if not results:
        return ""
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    header = f"Company: {company}\n"
    domain = _domain(website)
    if domain:
        header += f"Company website: {domain}\n"
    serp_text = header + "\n".join(
        f"- {r.get('title', '')} | {r.get('snippet', '')} | {r.get('link', '')}" for r in results
    )
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "system", "content": _HEADCOUNT_PROMPT}, {"role": "user", "content": serp_text}],
        response_format=_Headcount,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="headcount",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    parsed = completion.choices[0].message.parsed
    return parsed.band if parsed is not None else ""


def find_headcount(
    company: str, *, website: str = "", search=serper_search, client=None, costlog=None
) -> str:
    """1 Serper credit + 1 gpt-4o-mini call. Reads only LinkedIn/Craft/PitchBook
    company-size listings, never guesses a number — "" when no source states one.
    `website` is the disambiguator, not decoration: a `"{company}" employees` search
    happily returns a same-named company in the same industry (2026-07-27: Arcsky
    the Austin drone maker returned the headcount of ARC, an airline)."""
    q = f'"{company}" employees (site:linkedin.com/company OR site:craft.co OR site:pitchbook.com)'
    results = search(q, num=10)
    return _parse_headcount(company, website, results, client=client, costlog=costlog)


def enrich(p: Prospect, *, search=serper_search, client=None, costlog=None) -> Prospect:
    p.linkedin = find_company_linkedin(p.company, search=search)
    p.community_signals = find_community_signals(p, search=search, client=client, costlog=costlog)
    p.headcount = find_headcount(
        p.company, website=p.website, search=search, client=client, costlog=costlog
    )
    p.key_news = find_news(p.company, search=search)
    return p


def build_signal_prompt(p: Prospect) -> str:
    return f"""From the evidence below, synthesize for {p.company}:
- buying_signals: concrete triggers matching our ICP watchlist (new launch, gov contract,
  NDAA/Blue UAS cert, funding, relevant hiring, new vertical). Only evidence-backed ones.
  Each list item is one line: "<what happened> — <why it matters to us> (<source>, <date>)".
  Plain English, expand jargon/acronyms on first use; omit the date if the evidence has none.
- outreach_angle: 2-3 sentences: (1) the strongest ICP outreach angle for this prospect,
  (2) why it's the strongest fit for THIS prospect specifically, (3) which piece of
  evidence (news / community signal / fit reason) backs it. Still a single string, no
  line breaks.

## Evidence
news: {p.key_news}
community signals: {p.community_signals}
linkedin: {p.linkedin}
description: {p.description}

Reply with ONLY this JSON (no prose):
{{"buying_signals": ["..."], "outreach_angle": "..."}}"""
