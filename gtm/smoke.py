"""S1 smoke harness — auto_fit via gpt-4o-mini.

Standalone judgment for fit scoring. Mirrors the extract() pattern.
"""
from pydantic import BaseModel

from gtm.brief import Brief, freeze_brief
from gtm.contacts import find_contacts, top_contact_fields
from gtm.control import writes_enabled
from gtm.enrich import enrich
from gtm.extract import DroneExtraction
from gtm.fit import FitResult, apply_fit, build_fit_prompt
from gtm.output import push_to_sheet, write_csv
from gtm.run import ICP, company_from_url, emails_for_prospect, process_company, run_dir, save_state
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


def run_smoke(url: str, *, live: bool = False, run: str = "smoke") -> Prospect:
    """One company, end-to-end, unattended. Sink (Sheet push) gated on --live."""
    rdir = run_dir(run)
    lock_path = rdir / "brief.lock.json"
    if lock_path.exists():
        lock_path.unlink()
    freeze_brief(Brief(run=run, urls=[url]), rdir)
    p = Prospect(company=company_from_url(url), website=url, source="smoke")

    print(f"[smoke] scrape+extract — {p.company}")
    p = process_company(p)

    if p.status not in ("drop", "error"):
        print(f"[smoke] fit — {p.company}")
        ex = DroneExtraction(
            company_description=p.description,
            drone_models=p.drone_models,
            drone_dimensions=p.drone_dimensions,
            drone_weights=p.drone_weights,
            case_evidence=p.case_evidence,
            us_made_ndaa=p.us_made_ndaa,
        )
        apply_fit(p, auto_fit(ICP.read_text(), p.company, ex))

    if p.status in ("priority", "keep"):
        print(f"[smoke] enrich — {p.company}")
        enrich(p)
        contacts = find_contacts(p.company)
        if contacts:
            p.contact_name, p.contact_title, p.contact_linkedin = top_contact_fields(contacts)

        print(f"[smoke] emails — {p.company}")
        emails_for_prospect(p)

        print(f"[smoke] signals — {p.company}")
        s = auto_signals(p)
        p.buying_signals = s["buying_signals"]
        p.outreach_angle = s["outreach_angle"]

    print(f"[smoke] save — {p.company}")
    save_state([p], run_dir(run))
    write_csv([p], run_dir(run) / "prospects.csv")

    if writes_enabled(live):
        print(f"[smoke] push to sheet — {p.company}")
        push_to_sheet([p])

    return p
