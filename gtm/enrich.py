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
from datetime import date

from pydantic import BaseModel

from gtm.contacts import serper_search
from gtm.extract import MODEL, PRICE_IN, PRICE_OUT
from gtm.schema import Prospect

MAX_NEWS = 5
SNIPPET_WORDS = 25
# A signal older than this is context, not a reason to email today. Everything in
# run test-batch-1 was 1-2 years old and still got written up as fresh news.
RECENCY_MONTHS = 12


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


def _is_own_domain(own: str, r: dict) -> bool:
    """The prospect's own site is not news about the prospect. Run test-batch-1
    scraped Easy Aerial's homepage footer into key_news, which then fed a buying
    signal. Matches the bare domain and any subdomain of it (news.x.com)."""
    if not own:
        return False
    link = _domain(r.get("link", ""))
    return link == own or link.endswith(f".{own}")


def find_news(company: str, *, website: str = "", search=serper_search) -> list[str]:
    q = f'"{company}" drone (contract OR launch OR funding OR award OR NDAA OR "Blue UAS")'
    results = search(q, num=10)
    own = _domain(website)
    third_party = [r for r in results if not _is_own_domain(own, r)]
    return [_news_line(r) for r in third_party[:MAX_NEWS]]


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
#
# Every phrase must contain "drone" — same load-bearing rule as the model query
# (see _pain_queries). Locked by test_every_category_phrase_says_drone.
_CATEGORY_KEYWORDS = (
    ("public safety drone", ("public safety", "first responder", "police", "fire department")),
    ("search and rescue drone", ("search and rescue",)),
    # Agriculture before survey/mapping (added 2026-07-29): ag-drone copy routinely
    # says "crop mapping" / "field mapping", so survey-first swallowed the whole
    # segment. Measured the same day, 10 raw hits: "agricultural spray drone"
    # returned 10/10 real ag-operator threads (r/farming, r/Agriculture,
    # r/diydrones). Live run us-drone-13 (Hylio, "AgDrones ... crop treatments") is
    # the miss that prompted this — it had no bucket at all and hit the fallback.
    ("agricultural spray drone", ("agricultur", "spray", "crop", "farm")),
    # survey/mapping before industrial/inspection: "industrial" is a generic
    # adjective most makers use ("industrial drones"), while "surveying"/"mapping"
    # name an actual job — and the job is what operators talk about on forums.
    ("survey and mapping drone", ("survey", "mapping", "gis")),
    ("industrial inspection drone", ("industrial", "inspection")),
    ("utility inspection drone", ("energy", "utility", "utilities", "powerline")),
)
# Fallback when the description names no use case.
#
# 2026-07-27 measurements, all on 10 raw results each: mission-level phrasings
# reach nobody — "defense sUAS" returned pure defense-policy content (Pentagon
# demos, r/AirForce career threads, IDF posts) and "defense drone" collided with
# FTL: Faster Than Light, which has a "Defense Drone" item (4/10 hits were
# r/ftlgame). A gear-level phrase ("drone case foam") is far better targeted — 8/10
# results carried pain vocabulary, in r/drones, r/dji and r/fpv.
#
# Benched 2026-07-27, put in use 2026-07-29. The bench reason: live-running it
# showed the relevance filter could not hold the extra recall — Neros and Skyfront
# each went from 0 signals to 3, and 5 of those 6 were satisfied DIY chatter ("I
# laser cut a custom foam insert for my drone", "The foam is pick and pull").
#
# Two measurements on 2026-07-29 retired that objection:
#
# 1. The old mission-level fallback, "field-deployed drone", scored 0/10 on-topic —
#    r/ftlgame, r/WarCollege, r/amateurradio (antenna deployment), r/LancerRPG.
#    "deployed" collides across whole genres, the same trap "defense drone" hit.
#    This phrase scored 10/10 transport-case content on the same query shape.
# 2. The bench predates the second gate. find_community_signals became
#    candidates-NOT-a-verdict on 2026-07-28 — one day after the bench — so Claude
#    re-judges every candidate in build_signal_prompt. Re-running the current
#    filter on live SERP confirmed it still leaks (it now rejects the laser-cut
#    quote, but kept "It's only $30 and has 2 separate layers of tear-away foam").
#    That leak is now Claude's to drop, and costs prompt tokens. A fallback that
#    reaches r/LancerRPG costs the entire pain block.
#
# So: precision at this stage is cheap, recall is not. If Claude is ever removed
# from the loop, re-measure before trusting this.
_GEAR_LEVEL_CATEGORY = "drone case foam"
_DEFAULT_CATEGORY = _GEAR_LEVEL_CATEGORY


def _infer_category(p: Prospect) -> str:
    """Cheap keyword bucket into an ICP segment phrase — no LLM call, sourced from
    company/ICP.md's "Strong-fit segments" list.

    us_made_ndaa is deliberately NOT consulted. Until 2026-07-27 it was checked
    first and short-circuited to "defense sUAS". It is a *procurement* attribute,
    not a use case, and nearly every US maker in our ICP has it — so it swallowed
    almost every company and routed them all to the one query measured at 0 yield.
    On the Arcsky cold run it beat out an explicit "surveying, mapping, and
    infrastructure inspection" description, even though Arcsky's real operator
    community sits in r/UAVmapping and r/Surveying.

    Deliberately reads only fields the extract/fit stages have already filled:
    buying_signals is written by cmd_signals, which runs after cmd_enrich, so it is
    always [] here.

    Scans description + case_evidence + drone_models, not description alone
    (widened 2026-07-28): the use case is often named in what they ship in or
    what they call the airframe ("Guardian Public Safety UAV") rather than in
    marketing copy. description-only matching meant any company whose niche
    only showed up in those other fields fell through to the fallback — the
    coarseness the GTM-engineer review flagged (gtm/enrich.py's community-signal
    sourcing, `_GEAR_LEVEL_CATEGORY`).

    Widening what gets scanned was only half that fix, though. Live run
    us-drone-13 (2026-07-29) hit the fallback anyway: Hylio's description says
    "AgDrones ... agricultural operators ... crop treatments" and there was no
    agriculture bucket to match. Scanning more fields cannot help a segment with
    no phrase behind it — hence the bucket added the same day. When a live run
    lands on the fallback, check for a missing bucket before assuming the text
    was thin.

    p.segment is NOT consulted: assign_segment runs in a later pipeline stage
    (cmd_segment, after cmd_enrich) and is always "" here."""
    text = " ".join((p.description, p.case_evidence, " ".join(p.drone_models))).lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return category
    return _DEFAULT_CATEGORY


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
    # Structural Gate 2 (2026-07-27): the model must name the harm in its own words.
    # A yes/no gate leaked 5 of 6 topically-perfect but painless quotes ("I laser cut
    # a custom foam insert for my drone"); making it articulate what went wrong is
    # far harder to fake than answering "is this pain?" — it cannot fill this in for
    # a setup that works. Enforced by _has_problem, not by trusting the prompt.
    problem: str = ""


# Fillers a model reaches for when told to fill a field it has nothing for.
_NON_PROBLEMS = {"", "-", "--", "n/a", "na", "none", "nothing", "no problem",
                 "no issue", "no issues", "unknown", "unclear", "not stated", "null"}


def _has_problem(sig: "_Signal") -> bool:
    return sig.problem.strip().strip(".").lower() not in _NON_PROBLEMS


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

For every result you keep, fill the "problem" field with the specific thing that went
wrong, in your own words (e.g. "foam degrades and the airframe cracks in transit"). If you
cannot quote a word in the text describing damage, failure, cost, frustration, or a
workaround someone was forced into, then there is no problem to name — leave "problem"
empty and do not include the result at all. Never write "none", "n/a" or similar to fill
the field: an empty "problem" means the result is discarded, which is the correct outcome.
Describing a setup that WORKS is not pain:
"Our drones are stored in a plastic case with a BMS. The case connects to the 12-volt port
on the technician's vehicle" is a REJECT — it names a drone and a case and passes Gates 0
and 1, but nothing in it goes wrong. A satisfied or neutral description of how someone
transports their gear is the most common false positive here; it reads relevant precisely
because the vocabulary matches.

Also beware "case" in a non-physical sense — a legal case, a court case, a use case, or
the phrase "that's not the case" is not a transport container. REJECT those.

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
    kept = [s for s in parsed.signals if _has_problem(s)]
    return [f'"{s.quote}" ({s.source})' for s in kept[:MAX_COMMUNITY_SIGNALS]]


def find_community_signals(p: Prospect, *, search=serper_search, client=None, costlog=None) -> list[str]:
    """Pain-focused, not mention-focused (2026-07-27 redesign): airframe-specific
    and ICP-category queries, pooled and deduped, then a cheap gpt-4o-mini pass
    narrows to candidate pain quotes, rewritten as '"<quote>" (<source>)'.
    NOT a verdict (2026-07-28): live testing showed gpt-4o-mini can't reliably
    tell genuine pain from a satisfied setup described in the same vocabulary.
    These candidates get shown to Claude in build_signal_prompt, whose reply
    (merged via gtm/run.py::merge_signals) is what actually lands in
    p.community_signals — ammo for gtm/draft.py's pain block, not raw SERP noise."""
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
    p.key_news = find_news(p.company, website=p.website, search=search)
    return p


_SIGNAL_DATE_PROMPT = """From the search results below, find the specific date the event
described actually happened for {company}: "{claim}"

Return ISO format: YYYY-MM-DD if a full date is given, YYYY-MM if only month/year is known,
or "" if nothing here dates this specific event. Do not return a date for a different event
about {company} that merely shares a topic — only a date clearly tied to this claim counts."""


class _SignalDate(BaseModel):
    date: str


def _parse_iso_partial(s: str) -> date | None:
    """YYYY-MM-DD or YYYY-MM -> a date (day defaults to 1). None if unparseable —
    a model that ignores the requested format must not crash the pass, just miss."""
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def _insert_dated(line: str, iso: str) -> str:
    """Splice a found date into the line's trailing "(source)" parenthetical —
    "(TechCrunch)" -> "(TechCrunch, dated 2026-03)" — or append one if the line
    has no parenthetical at all."""
    if line.endswith(")") and " (" in line:
        head, _, tail = line[:-1].rpartition(" (")
        return f"{head} ({tail}, dated {iso})"
    return f"{line} (dated {iso})"


def date_undated_signal(
    company: str, claim: str, *, search=serper_search, client=None, costlog=None
) -> str:
    """One follow-up Serper search + gpt-4o-mini extraction attempt to pin down a
    date for a single [undated] buying-signal claim. Returns an ISO date/month
    string, or "" if no result dates this specific event — the caller must leave
    the signal marked [undated] rather than invent a date."""
    results = search(f'"{company}" {claim}', num=5)
    if costlog is not None:
        costlog.record_serper(stage="signal_dating")
    if not results:
        return ""
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
        messages=[
            {"role": "system", "content": _SIGNAL_DATE_PROMPT.format(company=company, claim=claim)},
            {"role": "user", "content": serp_text},
        ],
        response_format=_SignalDate,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="signal_dating",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    parsed = completion.choices[0].message.parsed
    return parsed.date.strip() if parsed and parsed.date else ""


def redate_undated_signals(
    p: Prospect, *, search=serper_search, client=None, costlog=None, today: date | None = None
) -> int:
    """Mutates p.buying_signals in place: every line ending [undated] gets one
    follow-up dating attempt (date_undated_signal). A date found replaces the
    marker with the real date, plus [stale] if it's older than RECENCY_MONTHS —
    a line where nothing was found is left exactly as Claude wrote it, still
    [undated]. Returns how many lines were successfully dated.

    This is the gap flagged 2026-07-29: undated signals got a marker and nothing
    else, permanently — there was no attempt to actually find out when they
    happened, even though the marker itself is a strong signal something IS
    dateable (the trigger_phrase/draft-opener rules exist because of it).
    """
    now = today or date.today()
    dated_count = 0
    updated = []
    for line in p.buying_signals:
        if not line.rstrip().endswith("[undated]"):
            updated.append(line)
            continue
        base = line.rstrip()[: -len("[undated]")].rstrip()
        found = date_undated_signal(p.company, base, search=search, client=client, costlog=costlog)
        parsed = _parse_iso_partial(found) if found else None
        if parsed is None:
            updated.append(line)
            continue
        dated_line = _insert_dated(base, found)
        if _months_between(parsed, now) > RECENCY_MONTHS:
            dated_line += " [stale]"
        updated.append(dated_line)
        dated_count += 1
    p.buying_signals = updated
    return dated_count


def build_signal_prompt(p: Prospect, *, today: date | None = None) -> str:
    now = today or date.today()
    return f"""From the evidence below, synthesize for {p.company}:
- buying_signals: concrete triggers matching our ICP watchlist (new launch, gov contract,
  NDAA/Blue UAS or equivalent national cert, funding, relevant hiring, new vertical). Only
  evidence-backed ones.
  Each list item is one line: "<what happened> — <why it matters to us> (<source>, <date>)".
  Plain English, expand jargon/acronyms on first use.

  **Dating (today is {now.isoformat()}).** Every signal carries a date when the evidence
  gives one. Anything older than {RECENCY_MONTHS} months gets " [stale]" appended to the
  line; a signal with no date at all gets " [undated]". Keep them — they are still context
  for the pitch — but they may not be used as an email opener, so the marker has to be
  there. Run test-batch-1 opened a July-2026 email with "congrats" on a 2025 event; that is
  the failure these markers prevent.

  **Not a buying signal — never list these, marked or otherwise:**
  · an unawarded bid or proposal ("is proposing", "has bid", "submitted a proposal", an
    SBIR/RFP response) — nobody has spent anything yet;
  · an equity or analyst note (price target, stock rating, upgraded/downgraded, market cap)
    — that's a trader's opinion, not a company event;
  · a contract *ceiling* on a shared multi-award vehicle (IDIQ, GSA schedule, BPA) reported
    as this company's own money. The ceiling is what a pool of vendors may compete for. Only
    a task order actually awarded to {p.company}, at its own stated value, counts;
  · a directory, database or profile page (Crunchbase, ZoomInfo, a listing site) — a record
    that they exist is not an event;
  · anything sourced from {p.company}'s own site or press page describing what they sell.
- trigger_phrase: the freshest FRESH signal (never a [stale] or [undated] one) reduced to a
  short NOUN PHRASE, 6 words or fewer, that reads correctly after a possessive — the draft
  uses it as "Saw {p.company}'s <trigger_phrase> — congrats." So: "Air Force Phase Three
  award", "$1.8M CBP contract", "Blue UAS certification". NOT a clause ("Awarded an Air
  Force contract to test..."), NOT the company's own name, NOT a passive participle
  ("Knighthawk 2 launched"). Return "" when no fresh signal exists or none reduces to a
  clean phrase — "" correctly blocks the row rather than shipping broken English.
- outreach_angle: 2-3 sentences: (1) the strongest ICP outreach angle for this prospect,
  (2) why it's the strongest fit for THIS prospect specifically, (3) which piece of
  evidence (news / community signal / fit reason) backs it. Still a single string, no
  line breaks.
- community_signals: the candidates below are gpt-4o-mini's first pass, NOT a verdict —
  live testing (2026-07-27/28) showed it keeps satisfied/neutral quotes that merely use
  the right vocabulary (e.g. a working setup described in detail reads as "relevant" even
  though nothing went wrong). Re-judge each candidate yourself: keep it only if a real
  person describes something actually going wrong or costing them (damage, failure,
  a workaround they were forced into) — drop anything that's a satisfied description, a
  neutral mention, or off-topic. Return the survivors verbatim (same quote/source format);
  an empty list is a correct answer if none hold up.

## Evidence
news: {p.key_news}
community signal candidates (unconfirmed — see community_signals above): {p.community_signals}
linkedin: {p.linkedin}
description: {p.description}

Reply with ONLY this JSON (no prose):
{{"buying_signals": ["..."], "trigger_phrase": "...", "outreach_angle": "...", "community_signals": ["..."]}}"""
