"""New stage: draft cold emails via a Claude checkpoint prompt (build_draft_prompt),
then automated gpt-4.1-mini fact-check (qa_check) once merged.

Claude does the judgment (drafting, matching company/voice-guide.md's tone) —
Python only builds the prompt and, after the human round-trip, fact-checks it.
One call per (prospect, persona tier present) pair — a CFO and a director at
the same company never get the same email.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from gtm.costlog import CostLog
from gtm.schema import DraftSet, Prospect

MODEL = "gpt-4.1-mini"
# docs/tools/openai.md — confirmed live 2026-07-20, still API-accessible though
# retired from the ChatGPT consumer UI.
PRICE_IN, PRICE_OUT = 0.40 / 1e6, 1.60 / 1e6


class QAError(Exception):
    pass


class QAResult(BaseModel):
    flag: str = ""  # empty = every claim is supported; else a short note of what isn't


# 2026-07-25 (user challenge): a drafted email with nothing specific to say is
# worse than no email — QA only fact-checks claims, it never catches "true but
# generic". Gate the draft itself on whether we actually have ammo; talking
# points are still generated for every tier regardless.
NO_DRAFT_FLAG = "n/a — talking-points only, signal too thin to draft a specific email"

# 2026-07-27 (user, with 8 worked example emails): body length is set by fit tier,
# not one flat cap. The old ~150-char cap was the root cause of "generic" drafts —
# company/voice-guide.md demands a 4-block structure (trigger · what we build ·
# the pain · close) and 150 chars only ever fit the skeleton, so the pain block
# (the part that makes the email land) was structurally impossible to write.
_TIER_SHAPE = {
    "priority": (
        "Tier 1 (priority)",
        "all four blocks — opener · what we build · the pain · close",
        "~450-700 characters",
    ),
    "keep": (
        "Tier 2 (keep)",
        "three blocks — opener · what we build (pain folded into the value line) · close",
        "~250-350 characters",
    ),
}
_DEFAULT_SHAPE = _TIER_SHAPE["priority"]

# 2026-07-28: a priority prospect with no researched pain still gets an email — it just
# loses Block 3. Requesting a pain block with no pain evidence is what forces the model
# to invent one (cold-0727/Arcsky). Tier 2 is already 3-block and keeps its own shape.
_NO_PAIN_SHAPE = (
    "Tier 1 (priority), no researched pain",
    "three blocks — opener · what we build · close",
    "~250-400 characters",
)

_NO_PAIN_RULE = (
    "\n- NO RESEARCHED PAIN: community_signals and competitor_weaknesses are both empty for "
    "this prospect. Do NOT assert any consequence they experience (damage, cracked or bent "
    "airframes, warranty claims, downtime, lost jobs), and do NOT attribute a claim to "
    "operators, buyers, customers, forums, or groups — nothing in the evidence supports one. "
    "The trigger and the value line carry this email."
)

REFERENCE_TOKEN = "{{reference_customer}}"


def check_reference_customer(p: Prospect, draft: DraftSet, others: list[str]) -> str:
    """Deterministic guard for the voice guide's "Social proof" hard rule: a draft
    may never name a real company as our customer.

    AeroVault is a demo company with no customers, so named social proof is written
    as the literal {{reference_customer}} token and filled at send time. The failure
    this exists to catch: the user's own worked examples name "Teal Drones" as a
    customer, and Teal Drones is itself a priority prospect in this pipeline — an
    email to Teal citing Teal as a reference is the worst possible send. Flags any
    run-mate's company name appearing in the draft body, and the recipient's own
    name appearing next to the reference token.

    Returns "" when clean, else the flag text (same contract as qa_check).
    """
    bodies = f"{draft.initial_body}\n{draft.initial_body_alt}"
    hits = [c for c in others if c and c != p.company and c.lower() in bodies.lower()]
    if hits:
        return (
            f"names another prospect ({', '.join(sorted(set(hits)))}) in the body — social "
            f"proof must use the literal {REFERENCE_TOKEN} token, never a hardcoded company"
        )
    return ""


# The guide mandates these two lines be identical in every draft (Block 1 opener is
# "{{first_name}}," on its own line, Signature is "{{sender_name}}"), so they are
# structural boilerplate, not evidence two tiers share a skeleton.
_MANDATED_LINES = {"{{first_name}},", "{{sender_name}}"}
_SKELETON_WORDS = 5      # a paragraph's "shape" = how it opens
# >half the real paragraphs opening alike = same email. Deliberately not stricter:
# the guide itself supplies a default opener ("Saw {{company_name}}'s
# {{trigger_event}} — congrats.") and a default close ("Would it be a bad idea..."),
# so two tiers sharing exactly those two is compliance, not duplication. It takes a
# shared *body* block on top of them to cross this line.
_SKELETON_LIMIT = 0.5


def _paragraph_skeletons(body: str) -> list[str]:
    """Each real paragraph reduced to its opening few words, lowercased. Two drafts
    that share most of these are the same email with synonyms swapped in."""
    out = []
    for para in body.split("\n\n"):
        para = para.strip()
        if not para or para in _MANDATED_LINES:
            continue
        words = re.sub(r"[^\w\s{}]", " ", para.lower()).split()
        if words:
            out.append(" ".join(words[:_SKELETON_WORDS]))
    return out


def check_tier_distinctness(p: Prospect, tier: str, draft: DraftSet) -> str:
    """Deterministic guard for the voice guide's "Banned skeleton" hard rule: two
    persona tiers at the same company must never get the same sentence skeleton.

    qa_check cannot catch this — it sees one draft at a time and only fact-checks
    claims against evidence, so a CFO and a director can both receive the same email
    with every claim true. The failure this exists to catch (cold-0727/Arcsky,
    2026-07-28): the `unknown` and `c-suite` tiers shipped the identical subject
    "transport for the new Xplorer" and four paragraphs that differed only in
    wording, and both were marked qa_flag="passed".

    Returns "" when clean, else the flag text (same contract as check_reference_customer).
    """
    if not draft.initial_subject:
        return ""
    mine = _paragraph_skeletons(draft.initial_body)
    for other_tier, other in p.drafts_by_tier.items():
        if other_tier == tier or not other.initial_subject:
            continue
        if draft.initial_subject.strip().lower() == other.initial_subject.strip().lower():
            return (
                f"subject line is identical to the {other_tier} tier's "
                f'("{draft.initial_subject}") — each persona tier needs its own'
            )
        theirs = _paragraph_skeletons(other.initial_body)
        if not mine or not theirs:
            continue
        shared = len(set(mine) & set(theirs))
        if shared / min(len(mine), len(theirs)) > _SKELETON_LIMIT:
            return (
                f"reuses the {other_tier} tier's sentence skeleton ({shared} of "
                f"{min(len(mine), len(theirs))} paragraphs open identically) — the two tiers must "
                f"differ in structure, not just wording"
            )
    return ""


def is_thin_signal(p: Prospect) -> bool:
    """A tier's prospect lacks enough concrete ammo (a named competitor weakness,
    direct case evidence, or an evidence-backed buying signal) to write an email that
    isn't generic filler.

    2-of-3, per the 2026-07-27 decision. The original all-three gate skipped 100% of
    contacts on the us-drone-6 run: drone makers essentially never name the case vendor
    they ship in (it's a commodity add-on, not a headline product), so
    competitor_weaknesses is empty almost always and it alone blocked every draft. Two
    concrete sources is still real ammo — the 2026-07-25 principle (never send a
    "true but empty" email) holds, the threshold was just set where nothing passes.
    """
    return sum(bool(x) for x in (p.competitor_weaknesses, p.case_evidence, p.buying_signals)) < 2


def has_pain_source(p: Prospect) -> bool:
    """Whether any researched evidence of a pain exists for this prospect.

    The voice guide's Block 3 asserts a consequence the prospect feels; only these two
    fields record one. case_evidence describes what they ship in today and buying_signals
    describe a trigger event — neither is evidence that anything hurts, and treating them
    as such is what let cold-0727/Arcsky ship "a cracked arm or a gimbal out of true"
    with nothing behind it (2026-07-28).
    """
    return bool(p.community_signals or p.competitor_weaknesses)


# Validated 2026-07-28 against every stored data/runs/*/prospects.json: these flag both
# cold-0727/Arcsky tiers and nothing else. The attribution list is not optional — Arcsky's
# c-suite draft contains no consequence word at all and fabricates purely by attributing a
# claim ("the surveying buyers ... in the mapping groups are asking").
_CONSEQUENCE_WORDS = (
    "cracked", "crack", "snapped", "broken", "breaks", "damaged", "damage", "dented",
    "bent", "shattered", "scratched", "warranty", "rma", "downtime", "grounded",
    "out of true", "failure", "fails", "replacement cost", "insurance claim",
)
_ATTRIBUTION_PATTERNS = (
    r"operators? (say|report|complain)",
    r"buyers?[^.]{0,40}(are )?asking",
    r"customers? (say|report)",
    r"crews? (say|report)",
    r"we hear",
    r"on reddit",
    r"in the [a-z ]{0,20}(groups|forums|threads|subreddit)",
)


def check_pain_grounding(p: Prospect, draft: DraftSet) -> str:
    """Deterministic guard for the voice guide's Block 3 grounding rule: a draft may not
    assert a pain the prospect has no researched evidence for.

    qa_check cannot catch this — its flag scope is stats, contracts, certifications, and
    events, and a fabricated consequence is none of those. The failure this exists to catch
    (cold-0727/Arcsky, 2026-07-28): both tiers shipped qa_flag="passed" while
    community_signals and competitor_weaknesses were empty, one asserting "a cracked arm or
    a gimbal out of true" and the other attributing a claim to "buyers ... in the mapping
    groups". A prior hand-rewrite reworded both rather than removing them.

    Armed ONLY when no pain evidence exists, which keeps the blast radius small: four of the
    seven stored drafts that do have evidence use "damage" legitimately in the value line.
    A false positive costs one pass through the existing redraft loop.

    Returns "" when clean, else the flag text (same contract as check_reference_customer).
    """
    if has_pain_source(p):
        return ""
    body = f"{draft.initial_body}\n{draft.initial_body_alt}".lower()
    hits = sorted({w for w in _CONSEQUENCE_WORDS if w in body})
    if hits:
        return (
            f"asserts a consequence ({', '.join(hits[:3])}) with no pain evidence — "
            f"community_signals and competitor_weaknesses are both empty for {p.company}, "
            f"so nothing supports it; drop the claim"
        )
    for pat in _ATTRIBUTION_PATTERNS:
        m = re.search(pat, body)
        if m:
            return (
                f'attributes a claim to third parties ("{m.group(0)}") with no pain '
                f"evidence — community_signals is empty for {p.company}, so no operator or "
                f"buyer complaint was ever researched; drop the claim"
            )
    return ""


def build_draft_prompt(
    voice_guide: str, p: Prospect, tier: str, sibling_tiers: list[str] | None = None
) -> str:
    contact_block = ""
    if tier != "unknown":
        contact_block = (
            f"\n## This contact (tailor the pitch to their seniority)\n"
            f"- persona tier: {tier}\n"
            f"This draft is for every contact at {p.company} classified into the '{tier}' "
            f"tier (gtm/persona.py::classify_persona) — apply the matching rule from the "
            f"voice guide's \"Persona tailoring\" section.\n"
        )

    tailoring_line = (
        f"Tailor the value prop to the '{tier}' persona tier (see the voice guide's "
        f'"Persona tailoring").'
        if tier != "unknown"
        else "Tailor the value prop to the general pain points in outreach_angle / buying_signals — "
        "no persona tier is known for this contact."
    )

    competitor_block = ""
    if p.competitor_weaknesses:
        weaknesses = "\n".join(f"- {w}" for w in p.competitor_weaknesses)
        competitor_block = (
            f"\n## Displacement ammo — {p.company} currently ships in a {p.competitor} case\n"
            f"Name {p.competitor} specifically in the value prop and cite ONE of these "
            f"researched weaknesses verbatim — never a generic \"better than X\" claim:\n"
            f"{weaknesses}\n"
        )

    # Each tier is prompted separately from the same evidence, so without naming the
    # siblings the likely outcome is one email reworded per tier — cold-0727/Arcsky
    # shipped two tiers with a byte-identical subject. check_tier_distinctness catches
    # that afterwards; this is what stops it being written in the first place.
    others = [t for t in (sibling_tiers or []) if t != tier]
    sibling_block = ""
    if others:
        sibling_block = (
            f"\n- OTHER TIERS AT THIS COMPANY: separate emails are also being written for the "
            f"{', '.join(repr(t) for t in others)} tier(s) from this same evidence. Yours must "
            f"not be a reworded copy of theirs — the voice guide bans two tiers sharing a "
            f"sentence skeleton. Differ in STRUCTURE: a different subject line (never the same "
            f"one twice), a different opening move, and the pain block written to what THIS "
            f"tier is measured on."
        )

    thin = is_thin_signal(p)

    if thin:
        draft_section = f"""## Email draft — SKIP
Signal is too thin to draft a specific, non-generic email right now (fewer than two of
competitor_weaknesses / case_evidence / buying_signals are present for {p.company}). Do NOT
draft an email — a generic "true but empty" email is worse than none. Set "draft_initial"
to {{}} in the reply JSON; pain_points/talking_points below are the deliverable for this tier."""
        reply_schema = f'{{"{p.company}": {{"{tier}": {{"pain_points": "...", "talking_points": "...", "draft_initial": {{}}}}}}}}'
    else:
        pain = has_pain_source(p)
        if pain:
            band, blocks, length = _TIER_SHAPE.get(p.status, _DEFAULT_SHAPE)
        elif p.status == "keep":
            band, blocks, length = _TIER_SHAPE["keep"]
        else:
            band, blocks, length = _NO_PAIN_SHAPE

        pain_block, close_num = "", 3
        if pain:
            close_num = 4
            pain_block = (
                f"3. **The pain** — the consequence THIS tier ('{tier}') feels, per the voice "
                f'guide\'s "Persona\n   tailoring". Ground it in community_signals / '
                f"competitor_weaknesses. Without this\n   block the email is just a product "
                f"description.\n"
            )
        no_pain_rule = "" if pain else _NO_PAIN_RULE

        draft_section = f"""## Email draft (self-enforce — from the voice guide's "Email structure")
Draft ONE email (no follow-up), 2 versions. Match the voice guide's example emails for
{band} at the '{tier}' persona tier — those are the length/rhythm anchors.

1. **Opener** — "{{{{first_name}}}}," on its own line, then one line naming their real
   trigger ("Saw {{{{company_name}}}}'s {{{{trigger_event}}}} — congrats."). The trigger must come
   from buying_signals / key_news — never invented. No generic greeting, no banned opener.
2. **What we build** — foam-fitted to one airframe (aircraft + controller + batteries +
   payload seated together), IP67 / MIL-STD-810H, US-made. Name a mechanism or spec, never a
   bare comparative. Social proof goes here, as the literal token {{{{reference_customer}}}} —
   NEVER a hardcoded company name (AeroVault is a demo company with no customers, and naming
   another prospect from this run as a customer is the exact failure this token prevents).
{pain_block}{close_num}. **Close** — ONE low-pressure closed-ended ask, negative-CTA preferred ("Would it be a bad
   idea for us to grab 15 minutes...?"). A single genuine question may precede it. Never
   stack asks. Then {{{{sender_name}}}} on its own line, nothing after.

### Format (self-enforce — do not exceed)
- This prospect is {band}: write {blocks}, body {length}.
- Subject line: under 60 characters, TRIGGER-FIRST or AIRFRAME-FIRST — lead with the
  prospect's own event, airframe, or pain, never with our product-line names (AV-Field,
  AV-Micro, AV-Ops, AV-Convoy) — the prospect has never heard them. Good:
  "field kit for {{{{airframe_name}}}}". Bad: "AV-Field case for X?".
- Plain-text paragraphs separated by blank lines. No links, no bullet lists.
- Variables (double-brace): {{{{first_name}}}}, {{{{company_name}}}}, {{{{airframe_name}}}},
  {{{{trigger_event}}}}, {{{{case_line}}}}, {{{{reference_customer}}}}, {{{{sender_name}}}}.
- BANNED SKELETON — do not write the compressed one-liner shape
  "{{{{first_name}}}} — saw {{{{trigger_event}}}}. We build MIL-STD cases sized to it. Worth a quick
  look?". It satisfies every other rule and still reads like a bot. v1 and v2 must differ in
  STRUCTURE, not just wording: one leads with the congratulation, the other with a question
  about their current setup.
- No banned phrases (see voice guide).{sibling_block}{no_pain_rule}"""
        reply_schema = (
            f'{{"{p.company}": {{"{tier}": {{"pain_points": "...", "talking_points": "...", '
            f'"draft_initial": {{"v1": {{"subject": "...", "body": "..."}}, '
            f'"v2": {{"subject": "...", "body": "..."}}}}}}}}}}'
        )

    return f"""For {p.company}, produce pain points + talking points (always), and an email
draft when the signal supports one. Follow company/voice-guide.md exactly — its tone, banned
phrases, signature, and format rules below are non-negotiable:

## Voice guide
{voice_guide}

## This prospect
- outreach_angle (the hook — use this, don't invent a new one): {p.outreach_angle}
- segment (which angle category to lean into): {p.segment}
- buying_signals (the {{{{trigger_event}}}} must come from here or key_news): {p.buying_signals}
- key_news: {p.key_news}
- community_signals (real operator complaints — ammo for the pain block): {p.community_signals}
- fit_reason: {p.fit_reason}
- competitor / competitor_weaknesses: {p.competitor} / {p.competitor_weaknesses}
- case_evidence: {p.case_evidence}
- drone_models (fills {{{{airframe_name}}}} — use the flagship, not the whole list): {p.drone_models}
- best_case_line (fills {{{{case_line}}}}): {p.best_case_line}
- fit tier: {p.tier or "unscored"} (status={p.status or "unset"}) — sets the email's length
{contact_block}{competitor_block}
## Pain points & talking points (always produce — the primary deliverable)
- pain_points: 1-3 concrete pains THIS tier ({tier}) at {p.company} likely has, grounded in
  outreach_angle / buying_signals / case_evidence — not generic industry pains. Plain string,
  short lines separated by " | ".
- talking_points: 2-4 specific things a rep should raise on a call with this tier — concrete
  mechanisms/specs/evidence, never a bare comparative. Plain string, short lines separated by
  " | ". {tailoring_line}

{draft_section}

Reply with ONLY this JSON (no prose), keyed by company name then persona tier:
{reply_schema}

Save the answer to drafts.json."""


def build_redraft_prompt(voice_guide: str, p: Prospect, tier: str, draft: DraftSet) -> str:
    """Same brief as build_draft_prompt, plus the QA fact-check failure reason
    (draft.qa_flag) so the rewrite fixes only the flagged claim, not a fresh draft."""
    base = build_draft_prompt(voice_guide, p, tier)
    return (
        f"{base}\n\n## QA rewrite required\n"
        f"The previous draft failed fact-check: {draft.qa_flag}\n"
        f"Rewrite to remove or fix that unsupported claim — keep everything else "
        f"(tone, structure, format) as specified above."
    )


def qa_check(p: Prospect, draft: DraftSet, *, client=None, costlog: CostLog | None = None) -> str:
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    evidence = (
        f"buying_signals: {p.buying_signals}\nkey_news: {p.key_news}\nfit_reason: {p.fit_reason}"
    )
    initial = f"Subject: {draft.initial_subject}\n{draft.initial_body}"
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You fact-check a cold email against the evidence used to write it. Flag "
                    "ONLY if it references a specific stat, contract, certification, or event "
                    "that is NOT supported by the evidence. Do not flag tone, length, or "
                    'phrasing. Reply with flag="" if every claim is supported.'
                ),
            },
            {"role": "user", "content": f"Evidence:\n{evidence}\n\nEmail:\n{initial}"},
        ],
        response_format=QAResult,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="qa",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    msg = completion.choices[0].message
    if msg.parsed is None:
        raise QAError(f"no parsed result (refusal={msg.refusal!r}, finish={completion.choices[0].finish_reason})")
    return msg.parsed.flag
