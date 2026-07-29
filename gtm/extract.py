"""S2 — extract structured drone fields from scraped markdown via gpt-4o-mini.

One extraction step for every scraper (scraper-agnostic): markdown in, fields out.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from gtm.costlog import CostLog

MODEL = "gpt-4o-mini"
MAX_MARKDOWN_CHARS = 24_000
# gpt-4o-mini pricing per 1M tokens (docs/tools/openai.md)
PRICE_IN, PRICE_OUT = 0.15 / 1e6, 0.60 / 1e6

SYSTEM_PROMPT = """You extract facts about a drone manufacturer from website markdown.
Only state what the text supports — leave fields empty/null when unsure.
- company_name: the company's proper name as written in the text (e.g. "Teal Drones").
- company_description: 1-2 sentences, what they make and for whom.
- drone_models: product names of the drones themselves (not payloads/accessories).
- drone_dimensions: physical L x W x H dimensions only, verbatim with units, noting
  folded/unfolded when stated (e.g. "13.7 x 9.8 x 3.5 in folded"). Empty if not published.
- drone_weights: airframe weights only, verbatim with units (e.g. "2.75 lbs (1.25 kg)").
- NEVER put performance specs (speed, range, max altitude, flight time) in either field.
- case_evidence: what the drone ships, packs, docks or is stored in — and who built it.
  Answer these, in one or two sentences, using only what the text says: does the system
  ship in a hard case, a soft bag or backpack? Is there a dock, drone-in-a-box, base or
  ground station the aircraft lives in? Is that housing named as a third-party product
  (Pelican, Nanuk, SKB...) or built by the manufacturer itself ("our own", "custom-molded",
  "proprietary")? Quote the phrasing they use. This field is about the CONTAINER only —
  payload capacity, flight time, range and portability claims are never case evidence;
  leave the field empty rather than filling it with a payload or spec sentence.
- us_made_ndaa: true only if US-made / NDAA-compliant / Blue UAS is stated; false if
  clearly foreign-made; null if not mentioned. This is a plain fact about where they
  build, NOT a quality judgment — a foreign manufacturer is an equally good prospect.
- compliance_evidence: any OTHER procurement/certification credential the text states,
  verbatim-ish, comma-separated. Examples: a NATO stock number, a national ministry-of-
  defence or police framework agreement, an EU/allied defense program, an aviation-
  authority type certification (EASA, CAA, Transport Canada), a BVLOS or equivalent
  operating waiver, a named awarded government contract. Do NOT restate NDAA/Blue UAS
  here (that is us_made_ndaa's job) and do not put marketing adjectives here
  ("military-grade", "professional") — only named programs, certs, or awards.
- hq_city: the company's headquarters city, only if explicitly stated (e.g. an "About" or
  "Contact" page address). Empty if not stated.
- hq_country: the company's headquarters country, only if explicitly stated or unambiguously
  implied by a full address. Empty if not stated."""


class ExtractError(Exception):
    pass


class DroneExtraction(BaseModel):
    company_name: str = ""
    company_description: str = ""
    drone_models: list[str] = []
    drone_dimensions: list[str] = []
    drone_weights: list[str] = []
    case_evidence: str = ""
    us_made_ndaa: Optional[bool] = None
    compliance_evidence: str = ""
    hq_city: str = ""
    hq_country: str = ""


def extract(markdown: str, *, client=None, costlog: CostLog | None = None) -> DroneExtraction:
    if client is None:
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        client = OpenAI()

    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": markdown[:MAX_MARKDOWN_CHARS]},
        ],
        response_format=DroneExtraction,
    )
    if costlog is not None:
        u = completion.usage
        costlog.record(
            stage="extract",
            model=MODEL,
            tokens_in=u.prompt_tokens,
            tokens_out=u.completion_tokens,
            cost_usd=u.prompt_tokens * PRICE_IN + u.completion_tokens * PRICE_OUT,
        )
    msg = completion.choices[0].message
    if msg.parsed is None:
        raise ExtractError(f"no parsed result (refusal={msg.refusal!r}, finish={completion.choices[0].finish_reason})")
    return msg.parsed
