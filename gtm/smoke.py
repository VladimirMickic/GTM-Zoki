"""S1 smoke harness — auto_fit via gpt-4o-mini.

Standalone judgment for fit scoring. Mirrors the extract() pattern.
"""
from pydantic import BaseModel

from gtm.extract import DroneExtraction
from gtm.fit import FitResult, build_fit_prompt
from gtm.schema import Prospect

MODEL = "gpt-4o-mini"


class SignalOut(BaseModel):
    buying_signals: list[str]
    outreach_angle: str


def auto_fit(icp: str, company: str, ex: DroneExtraction, *, client=None) -> FitResult:
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    prompt = build_fit_prompt(icp, company, ex)
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=FitResult,
    )
    msg = completion.choices[0].message
    if msg.parsed is None:
        raise RuntimeError(f"no parsed result (refusal={msg.refusal!r}, finish={completion.choices[0].finish_reason})")
    return msg.parsed


def auto_signals(p: Prospect, *, client=None) -> dict:
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    from gtm.enrich import build_signal_prompt

    prompt = build_signal_prompt(p)
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=SignalOut,
    )
    msg = completion.choices[0].message
    if msg.parsed is None:
        raise RuntimeError(f"no parsed result (refusal={msg.refusal!r}, finish={completion.choices[0].finish_reason})")
    return msg.parsed.model_dump()
