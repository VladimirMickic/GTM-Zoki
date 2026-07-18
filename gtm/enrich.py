"""S5 — enrichment for fit passers only (3 Serper credits per company).

Python gathers raw signals: company LinkedIn, one Reddit mention, top-5 news with snippets.
Claude (orchestrator) synthesizes buying_signals + outreach_angle from them via
build_signal_prompt() — the company-research skill adds depth when run in-loop.
"""
from __future__ import annotations

from gtm.contacts import serper_search
from gtm.schema import Prospect

MAX_NEWS = 5
SNIPPET_WORDS = 25


def find_company_linkedin(company: str, *, search=serper_search) -> str:
    for r in search(f'site:linkedin.com/company "{company}"', num=10):
        if "/company/" in r.get("link", ""):
            return r["link"]
    return ""


def find_reddit_signal(company: str, *, search=serper_search) -> str:
    for r in search(f'site:reddit.com "{company}"', num=10):
        if r.get("link"):
            return f"{r.get('title', '')} — {r['link']}"
    return ""


def _news_line(r: dict) -> str:
    title, link = r.get("title", ""), r.get("link", "")
    words = r.get("snippet", "").split()
    snippet = " ".join(words[:SNIPPET_WORDS]) + (" …" if len(words) > SNIPPET_WORDS else "")
    return f"{title} — {snippet} ({link})" if snippet else f"{title} ({link})"


def find_news(company: str, *, search=serper_search) -> list[str]:
    q = f'"{company}" (contract OR launch OR funding OR award OR NDAA OR "Blue UAS")'
    results = search(q, num=10)
    return [_news_line(r) for r in results[:MAX_NEWS]]


def enrich(p: Prospect, *, search=serper_search) -> Prospect:
    p.linkedin = find_company_linkedin(p.company, search=search)
    p.reddit_signal = find_reddit_signal(p.company, search=search)
    p.key_news = find_news(p.company, search=search)
    return p


def build_signal_prompt(p: Prospect) -> str:
    return f"""From the evidence below, synthesize for {p.company}:
- buying_signals: concrete triggers matching our ICP watchlist (new launch, gov contract,
  NDAA/Blue UAS cert, funding, relevant hiring, new vertical). Only evidence-backed ones.
  Each list item is one line: "<what happened> — <why it matters to us> (<source>, <date>)".
  Plain English, expand jargon/acronyms on first use; omit the date if the evidence has none.
- outreach_angle: ONE sentence picking the strongest ICP outreach angle for this prospect.

## Evidence
news: {p.key_news}
reddit: {p.reddit_signal}
linkedin: {p.linkedin}
description: {p.description}

Reply with ONLY this JSON (no prose):
{{"buying_signals": ["..."], "outreach_angle": "..."}}"""
