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

    return f"""Draft a 2-email cold sequence (initial + follow-up), 2 versions each, for
{p.company}. Follow company/voice-guide.md exactly — its tone, banned phrases, signature,
and format rules below are non-negotiable:

## Voice guide
{voice_guide}

## This prospect
- outreach_angle (the hook — use this, don't invent a new one): {p.outreach_angle}
- segment (which angle category to lean into): {p.segment}
- buying_signals: {p.buying_signals}
- key_news: {p.key_news}
- fit_reason: {p.fit_reason}
{contact_block}{competitor_block}
## Structure (self-enforce — from the voice guide's "Email structure")
1. Open with a real, specific fact about {p.company} (drawn from outreach_angle /
   buying_signals / key_news) — never a generic greeting or banned opener.
2. Value prop: a use case + social proof (category-level only — AeroVault has no named
   customers to cite) + the pain it removes.
3. Close with ONE closed-ended (yes/no) ask or a low-pressure negative-CTA — never stack asks.
{tailoring_line}

## Format (self-enforce — do not exceed)
- Subject line: under 40 characters, TRIGGER-FIRST — lead with the prospect's own
  event or pain (from outreach_angle / buying_signals / key_news), never with our
  product-line names (AV-Field, AV-Micro, AV-Ops, AV-Convoy) — the prospect has never
  heard them. Good: "Switchblade 400 field kit?". Bad: "AV-Field case for X?".
- Body: capped at ~150 characters — one or two sentences, no more.
- Personalization variables: {{FIRST_NAME}}, {{COMPANY}}.
- No links in the body. No banned phrases (see voice guide). Close with the signature block
  from the voice guide.

Reply with ONLY this JSON (no prose), keyed by company name then persona tier:
{{"{p.company}": {{"{tier}": {{"draft_initial": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}},
"draft_followup": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}}}}}}}}

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
    followup = f"Subject: {draft.followup_subject}\n{draft.followup_body}"
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You fact-check a cold email sequence (initial + follow-up) against the "
                    "evidence used to write them. Flag ONLY if either email references a "
                    "specific stat, contract, certification, or event that is NOT supported by "
                    "the evidence. Do not flag tone, length, or phrasing. If you flag something, "
                    'say which email ("initial" or "follow-up") it came from. Reply with '
                    'flag="" if every claim in both emails is supported.'
                ),
            },
            {"role": "user", "content": f"Evidence:\n{evidence}\n\nInitial Email:\n{initial}\n\nFollow-up Email:\n{followup}"},
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
