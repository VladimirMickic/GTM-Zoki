"""S1 smoke harness — auto_fit via gpt-4o-mini.

Standalone judgment for fit scoring. Mirrors the extract() pattern.
"""
from gtm.extract import DroneExtraction
from gtm.fit import FitResult, build_fit_prompt

MODEL = "gpt-4o-mini"


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
