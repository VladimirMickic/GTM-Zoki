"""New stage: draft cold emails via a Claude checkpoint prompt (build_draft_prompt),
then automated gpt-4.1-mini fact-check (qa_check) once merged.

Claude does the judgment (drafting, matching company/voice-guide.md's tone) —
Python only builds the prompt and, after the human round-trip, fact-checks it.
"""
from __future__ import annotations

from pydantic import BaseModel

from gtm.costlog import CostLog
from gtm.persona import classify_persona
from gtm.schema import Prospect

MODEL = "gpt-4.1-mini"
# docs/tools/openai.md — confirmed live 2026-07-20, still API-accessible though
# retired from the ChatGPT consumer UI.
PRICE_IN, PRICE_OUT = 0.40 / 1e6, 1.60 / 1e6


class QAError(Exception):
    pass


class QAResult(BaseModel):
    flag: str = ""  # empty = every claim is supported; else a short note of what isn't


def build_draft_prompt(voice_guide: str, p: Prospect) -> str:
    top_title = p.contact_title.split(";")[0].strip() if p.contact_title else ""
    persona = classify_persona(top_title)
    contact_block = ""
    if persona != "unknown":
        contact_block = (
            f"\n## This contact (tailor the pitch to their seniority)\n"
            f"- top contact title: {top_title}\n"
            f"- persona tier: {persona}\n"
            f"Apply the matching rule from the voice guide's \"Persona tailoring\" section.\n"
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
{contact_block}
## Format (self-enforce — do not exceed)
- Subject line: under 40 characters.
- Body: capped at ~150 characters — one or two sentences, no more.
- Personalization variables: {{FIRST_NAME}}, {{COMPANY}}.
- No links in the body. No banned phrases (see voice guide). Close with the signature block
  from the voice guide.

Reply with ONLY this JSON (no prose), keyed by company name:
{{"{p.company}": {{"draft_initial": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}},
"draft_followup": {{"v1": {{"subject": "...", "body": "..."}}, "v2": {{"subject": "...", "body": "..."}}}}}}}}

Save the answer to drafts.json."""


def qa_check(p: Prospect, *, client=None, costlog: CostLog | None = None) -> str:
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    evidence = (
        f"buying_signals: {p.buying_signals}\nkey_news: {p.key_news}\nfit_reason: {p.fit_reason}"
    )
    initial = f"Subject: {p.draft_initial_subject}\n{p.draft_initial_body}"
    followup = f"Subject: {p.draft_followup_subject}\n{p.draft_followup_body}"
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
