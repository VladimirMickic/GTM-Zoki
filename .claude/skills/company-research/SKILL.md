---
name: company-research
description: Run validated, high-accuracy web research on a company — profiles, competitors, reviews, news, hiring, growth signals, negativity, PR releases, or job-specific insights. Use when the user asks to research a company or prospect, prep for a sales call, build an account brief, or find specific intelligence (competitors, funding, hiring, complaints, etc.) about a named company. Sourced from LeadGrowGTM/research-process-builder — processes validated at 90-100% accuracy across 220+ tested search patterns.
allowed-tools: WebSearch, WebFetch
---

# company-research

Nine step-by-step research processes, each validated to 90%+ accuracy by running 200+ search patterns against 11 real companies (from $400B+ enterprises to bootstrapped startups). Each process is a fixed sequence of searches with exact queries, what to extract from each, early-stop conditions, a kill list of searches that waste time, and an output template.

Source: [LeadGrowGTM/research-process-builder](https://github.com/LeadGrowGTM/research-process-builder). This skill carries over only the validated, general-purpose processes — not the repo's internal Python/FireCrawl/Supabase pipeline (that's for their own scheduled monitors and isn't needed here; Claude Code's own `WebSearch`/`WebFetch` tools run these processes directly).

## Processes

| process | what it finds | steps | accuracy |
|---|---|---|---|
| [find-profiles](references/find-profiles.md) | company fact sheet — zoominfo, crunchbase, linkedin, rocketreach, pitchbook, tracxn | 6 | 100% |
| [find-competitors](references/find-competitors.md) | direct competitors with positioning and justification | 7 | 93% |
| [find-reviews](references/find-reviews.md) | individual reviews tagged positive/negative, three-sentence summaries | 6 | 95% |
| [find-news](references/find-news.md) | partnerships, acquisitions, funding, launches, expansions, leadership changes | 7 | 90% |
| [find-pr-releases](references/find-pr-releases.md) | official announcements, press releases, blog posts, wire distributions | 5 | 90% |
| [find-hiring](references/find-hiring.md) | open roles, departments hiring, ATS platform, hiring velocity | 5 | 93% |
| [find-job-role-insights](references/find-job-role-insights.md) | tech stack, pain points, strategic signals from a specific job description (companion to find-hiring) | 5 | 90% |
| [find-growth-signals](references/find-growth-signals.md) | blog activity, lead magnets, social presence, community, newsletters, pricing maturity | 7 | 93% |
| [find-negativity](references/find-negativity.md) | customer complaints, negative reviews, controversy, churn signals | 6 | 90% |

Also see [references/search-tips.md](references/search-tips.md) — tactical gotchas learned across all 220+ test searches (broken `site:` operators, query traps, high-leverage modifiers). Skim it before improvising a search that isn't in a process file.

## When to use

Trigger phrases: "research [company]", "prep me for the call with [company]", "find [company]'s competitors", "who is [company] hiring", "any bad reviews of [company]", "what's [company] been up to lately". Also useful ahead of a sales call captured by the `fireflies-processor` skill — run `find-profiles` and `find-news` on the prospect company before the call, so the brief has account context, not just the transcript.

## How to run a process

1. **Pick the process(es)** from the table above based on what the user actually asked for. Default to `find-profiles` alone if they just said "research this company" with no other signal — it's the highest-accuracy, broadest-coverage process and a good starting point. Chain more processes only if the ask calls for it (e.g. "prep me for a sales call" → find-profiles + find-news + find-growth-signals).
2. **Read the process file.** Each one is self-contained: inputs, ordered steps with exact search queries, what to extract, `stop if` early-exit conditions, a `do not search` kill list, and an output template.
3. **Fill in the `{{inputs}}`** (company name, domain, category, etc.) from what the user gave you. If `{{domain}}` is unknown, resolve it first with a quick search — don't guess.
4. **Execute steps in order** using `WebSearch` for each query and `WebFetch` on promising result URLs to pull the actual page content. Respect every `stop if` condition — the processes are tuned to stop once they have enough signal, not to exhaust every step.
5. **Skip everything in `do not search`** — these were tested and confirmed to waste searches or return noise.
6. **Fill the output template exactly as specified** in the process file, with real sources (URLs) cited per finding.

## Notes

- These processes assume a live web search tool (Claude Code's `WebSearch`/`WebFetch`). They do not require FireCrawl, SerperDev, or any API key — that infra exists in the source repo for their own automated pipeline, not for this skill.
- Every process file hardcodes `{{current_year}}`-style placeholders rather than a literal year — always substitute the actual current year when building queries, per the search-tips guidance on year modifiers.
- If a research need doesn't match any of the 9 processes here (e.g. pricing intelligence, market sizing, tech-stack detection), don't improvise from scratch — the source repo's `SKILL.md` documents the 6-phase methodology used to build these processes, in case a new one is worth building properly and validating rather than one-off searching.
