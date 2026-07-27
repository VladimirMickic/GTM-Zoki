"""New stage: draft cold emails via a Claude checkpoint prompt (build_draft_prompt),
then automated gpt-4.1-mini fact-check (qa_check) once merged.

Claude does the judgment (drafting, matching company/voice-guide.md's tone) —
Python only builds the prompt and, after the human round-trip, fact-checks it.
One call per (prospect, persona tier present) pair — a CFO and a director at
the same company never get the same email.
"""
from __future__ import annotations

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


def is_thin_signal(p: Prospect) -> bool:
    """A tier's prospect lacks enough concrete ammo (a named competitor
    weakness, direct case evidence, or an evidence-backed buying signal) to
    write an email that isn't generic filler. Any one missing is enough —
    strict, per 2026-07-25 decision: fewer risky generic drafts over fewer
    talking-points-only fallbacks."""
    return not p.competitor_weaknesses or not p.case_evidence or not p.buying_signals


def build_draft_prompt(voice_guide: str, p: Prospect, tier: str) -> str:
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

    thin = is_thin_signal(p)

    if thin:
        draft_section = f"""## Email draft — SKIP
Signal is too thin to draft a specific, non-generic email right now (at least one of
competitor_weaknesses / case_evidence / buying_signals is empty for {p.company}). Do NOT
draft an email — a generic "true but empty" email is worse than none. Set "draft_initial"
to {{}} in the reply JSON; pain_points/talking_points below are the deliverable for this tier."""
        reply_schema = f'{{"{p.company}": {{"{tier}": {{"pain_points": "...", "talking_points": "...", "draft_initial": {{}}}}}}}}'
    else:
        draft_section = f"""## Email draft (self-enforce — from the voice guide's "Email structure")
Draft ONE email (no follow-up), 2 versions.
1. Open with a real, specific fact about {p.company} (drawn from outreach_angle /
   buying_signals / key_news) — never a generic greeting or banned opener.
2. Value prop: a use case + social proof (category-level only — AeroVault has no named
   customers to cite) + the pain it removes.
3. Close with ONE closed-ended (yes/no) ask or a low-pressure negative-CTA — never stack asks.

### Format (self-enforce — do not exceed)
- Subject line: under 40 characters, TRIGGER-FIRST — lead with the prospect's own
  event or pain (from outreach_angle / buying_signals / key_news), never with our
  product-line names (AV-Field, AV-Micro, AV-Ops, AV-Convoy) — the prospect has never
  heard them. Good: "Switchblade 400 field kit?". Bad: "AV-Field case for X?".
- Body: capped at ~150 characters — one or two sentences, no more.
- Personalization variables: {{FIRST_NAME}}, {{COMPANY}}.
- No links in the body. No banned phrases (see voice guide). Close with the signature block
  from the voice guide."""
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
- buying_signals: {p.buying_signals}
- key_news: {p.key_news}
- fit_reason: {p.fit_reason}
- competitor / competitor_weaknesses: {p.competitor} / {p.competitor_weaknesses}
- case_evidence: {p.case_evidence}
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
