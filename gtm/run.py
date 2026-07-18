"""S7b — orchestrator. Claude drives these subcommands, doing the judgment between them:

  python -m gtm.run start data/runs/<run>/brief.md   # discover/urls → scrape+extract → fit prompts
  python -m gtm.run fit <run> <fit.json>             # apply Claude's FitResults
  python -m gtm.run enrich <run>                     # passers: contacts + enrichment → signal prompts
  python -m gtm.run signals <run> <signals.json>     # apply Claude's buying_signals/outreach_angle
  python -m gtm.run output <run>                     # CSV (+ Sheet push if creds present)
  python -m gtm.run learn                            # show feedback for ICP/denylist proposals

State = data/runs/<run>/prospects.json. Failures are logged to data/errors.log and the
company is skipped (status="error"), never the whole run.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from gtm.brief import load_brief
from gtm.costlog import CostLog
from gtm.extract import DroneExtraction, extract
from gtm.fit import FitResult, apply_fit, build_fit_prompt, check_disqualifiers
from gtm.schema import Prospect
from gtm.scrape import scrape, scrape_deep

DATA = Path("data")
ERROR_LOG = DATA / "errors.log"
COSTS = DATA / "costs.jsonl"
FEEDBACK = DATA / "feedback.jsonl"
ICP = Path("company/ICP.md")


def company_from_url(url: str) -> str:
    host = urlparse(url).netloc.removeprefix("www.")
    return host.split(".")[0].capitalize()


def run_dir(run: str) -> Path:
    return DATA / "runs" / run


def save_state(prospects: list[Prospect], rdir: str | Path) -> None:
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "prospects.json").write_text(json.dumps([p.model_dump() for p in prospects], indent=2))


def load_state(rdir: str | Path) -> list[Prospect]:
    return [Prospect(**d) for d in json.loads((Path(rdir) / "prospects.json").read_text())]


def _log_error(error_log: Path, company: str, stage: str, err: Exception) -> None:
    error_log.parent.mkdir(parents=True, exist_ok=True)
    with error_log.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {company} [{stage}] {err}\n")


def process_company(
    p: Prospect,
    *,
    scrape_fn=scrape,
    extract_fn=extract,
    error_log: Path = ERROR_LOG,
    costlog: CostLog | None = None,
) -> Prospect:
    """Scrape + extract + deterministic disqualifiers for one company. Log & skip."""
    try:
        md = scrape_fn(p.website)
        ex: DroneExtraction = extract_fn(md, costlog=costlog)
    except Exception as e:
        _log_error(error_log, p.company, "scrape/extract", e)
        p.status = "error"
        return p
    if ex.company_name:
        p.company = ex.company_name
    p.description = ex.company_description
    p.drone_models = ex.drone_models
    p.drone_dimensions = ex.drone_dimensions
    p.drone_weights = ex.drone_weights
    p.us_made_ndaa = ex.us_made_ndaa
    dq = check_disqualifiers(ex)
    if dq:
        p.status = "drop"
        p.fit_score = 0
        p.fit_reason = dq
    return p


def merge_fit(prospects: list[Prospect], fits: dict[str, FitResult]) -> None:
    for p in prospects:
        if p.company in fits and p.status not in ("drop", "error"):
            apply_fit(p, fits[p.company])


def merge_signals(prospects: list[Prospect], signals: dict[str, dict]) -> None:
    for p in prospects:
        s = signals.get(p.company)
        if s:
            p.buying_signals = s.get("buying_signals", [])
            p.outreach_angle = s.get("outreach_angle", "")


# ---------------------------------------------------------------- CLI stages

def cmd_start(brief_path: str) -> None:
    brief = load_brief(brief_path)
    costlog = CostLog(COSTS)
    prospects = [Prospect(company=company_from_url(u), website=u, source="brief") for u in brief.urls]
    if brief.query:
        from gtm.discover import discover

        for c in discover(brief.query, brief.max_companies, costlog=costlog):
            prospects.append(Prospect(company=c.company, website=c.website, source=f"serper:{brief.query}"))
    prospects = prospects[: brief.max_companies]

    ex_by_company: dict[str, DroneExtraction] = {}
    for p in prospects:
        process_company(p, scrape_fn=lambda u: scrape_deep(u, preferred=brief.scraper), costlog=costlog)
        if p.status == "":
            ex_by_company[p.company] = DroneExtraction(
                company_description=p.description,
                drone_models=p.drone_models,
                drone_dimensions=p.drone_dimensions,
                drone_weights=p.drone_weights,
                us_made_ndaa=p.us_made_ndaa,
            )
        print(f"[{p.status or 'scraped'}] {p.company} — models={p.drone_models}")

    save_state(prospects, run_dir(brief.run))
    icp = ICP.read_text()
    print("\n=== FIT PROMPTS — Claude: score each, save {company: FitResult} to fit.json ===")
    for company, ex in ex_by_company.items():
        print(f"\n----- {company} -----")
        print(build_fit_prompt(icp, company, ex))


def cmd_fit(run: str, fit_json: str) -> None:
    prospects = load_state(run_dir(run))
    raw = json.loads(Path(fit_json).read_text())
    merge_fit(prospects, {k: FitResult(**v) for k, v in raw.items()})
    save_state(prospects, run_dir(run))
    for p in prospects:
        print(f"[{p.status}] {p.company} score={p.fit_score}")


def cmd_enrich(run: str) -> None:
    from gtm.contacts import find_contacts, top_contact_fields
    from gtm.enrich import build_signal_prompt, enrich

    prospects = load_state(run_dir(run))
    for p in prospects:
        if p.status not in ("priority", "keep"):
            continue
        try:
            enrich(p)
            contacts = find_contacts(p.company)
            if contacts:
                p.contact_name, p.contact_title, p.contact_linkedin = top_contact_fields(contacts)
        except Exception as e:
            _log_error(ERROR_LOG, p.company, "enrich/contacts", e)
    save_state(prospects, run_dir(run))
    print("\n=== SIGNAL PROMPTS — Claude: answer each, save {company: {...}} to signals.json ===")
    for p in prospects:
        if p.status in ("priority", "keep"):
            print(f"\n----- {p.company} -----")
            print(build_signal_prompt(p))


def cmd_signals(run: str, signals_json: str) -> None:
    prospects = load_state(run_dir(run))
    merge_signals(prospects, json.loads(Path(signals_json).read_text()))
    save_state(prospects, run_dir(run))
    print("signals merged for", sum(1 for p in prospects if p.outreach_angle), "prospects")


def cmd_output(run: str) -> None:
    from gtm.output import SERVICE_ACCOUNT_FILE, push_to_sheet, write_csv

    prospects = load_state(run_dir(run))
    today = time.strftime("%Y-%m-%d")
    for p in prospects:
        p.date_processed = today
    save_state(prospects, run_dir(run))
    csv_path = run_dir(run) / "prospects.csv"
    n = write_csv(prospects, csv_path)
    print(f"wrote {n} prospects → {csv_path}")
    if Path(SERVICE_ACCOUNT_FILE).exists():
        pushed = push_to_sheet(prospects)
        print(f"pushed {pushed} rows to Google Sheet")
    else:
        print("no credentials/service_account.json — skipped Sheet push (CSV is ready)")


def cmd_learn() -> None:
    if not FEEDBACK.exists():
        print("no feedback yet (data/feedback.jsonl)")
        return
    lines = FEEDBACK.read_text().splitlines()[-50:]  # bounded read (credit rule)
    print(f"=== last {len(lines)} feedback entries — Claude: propose ICP/denylist edits ===")
    for line in lines:
        print(line)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    args = sys.argv[1:]
    match args:
        case ["start", brief_path]:
            cmd_start(brief_path)
        case ["fit", run, fit_json]:
            cmd_fit(run, fit_json)
        case ["enrich", run]:
            cmd_enrich(run)
        case ["signals", run, signals_json]:
            cmd_signals(run, signals_json)
        case ["output", run]:
            cmd_output(run)
        case ["learn"]:
            cmd_learn()
        case _:
            print(__doc__)
            sys.exit(1)


if __name__ == "__main__":
    main()
