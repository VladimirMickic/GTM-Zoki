"""S5 — enrichment for fit passers only (3 Serper credits per company).

Python gathers raw signals: company LinkedIn, top-5 community signals, top-5 news with snippets.
Claude (orchestrator) synthesizes buying_signals + outreach_angle from them via
build_signal_prompt() — the company-research skill adds depth when run in-loop.
"""
from __future__ import annotations

import re

from gtm.contacts import serper_search
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


MAX_COMMUNITY_SIGNALS = 5


def find_community_signals(company: str, *, search=serper_search) -> list[str]:
    q = f'"{company}" drone (site:reddit.com OR site:x.com OR site:twitter.com OR site:rcgroups.com)'
    results = search(q, num=10)
    return [_news_line(r) for r in results[:MAX_COMMUNITY_SIGNALS]]


def enrich(p: Prospect, *, search=serper_search) -> Prospect:
    p.linkedin = find_company_linkedin(p.company, search=search)
    p.community_signals = find_community_signals(p.company, search=search)
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
