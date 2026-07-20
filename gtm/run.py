"""S7b — orchestrator. Claude drives these subcommands, doing the judgment between them:

  python -m gtm.run start data/runs/<run>/brief.md   # discover/urls → scrape+extract → fit prompts
  python -m gtm.run fit <run> <fit.json>             # apply Claude's FitResults
  python -m gtm.run enrich <run>                     # passers: contacts + enrichment → signal prompts
  python -m gtm.run signals <run> <signals.json>     # apply Claude's buying_signals/outreach_angle
  python -m gtm.run segment <run>                    # bucket passers → draft prompts
  python -m gtm.run draft <run> <drafts.json>        # apply Claude's drafts → auto QA
  python -m gtm.run output <run>                     # CSV (+ Sheet push if creds present)
  python -m gtm.run learn                            # show feedback for ICP/denylist proposals
  python -m gtm.run smoke <url> [--live]             # one company, end-to-end; --live also pushes to Sheet

State = data/runs/<run>/prospects.json. Failures are logged to data/errors.log and the
company is skipped (status="error"), never the whole run.
"""
from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import gtm.github_state as github_state
from gtm.brief import freeze_brief, load_brief
from gtm.control import CheckpointPending, ExitCode, writes_enabled
from gtm.costlog import CostLog
from gtm.draft import build_draft_prompt, qa_check
from gtm.extract import DroneExtraction, extract
from gtm.fit import FitResult, apply_fit, build_fit_prompt, check_disqualifiers
from gtm.schema import Prospect
from gtm.scrape import scrape, scrape_deep
from gtm.segment import assign_segment
from gtm.spechunt import hunt_specs

DATA = Path("data")
ERROR_LOG = DATA / "errors.log"
COSTS = DATA / "costs.jsonl"
FEEDBACK = DATA / "feedback.jsonl"
ICP = Path("company/ICP.md")
VOICE_GUIDE = Path("company/voice-guide.md")

# Task 6.2: GitHub Issues stage tracking (gtm/github_state.py, Task 6.1). One
# label vocabulary, fixed and small — matches the six cmd_* pipeline verbs and
# the lifecycle states a stage can be in. Validated once per stage transition
# (pre-flight, no network call) so a future typo here fails loud in tests
# instead of silently sending a garbage label to GitHub.
STAGE_NAMES = {"start", "fit", "enrich", "signals", "segment", "draft", "output", "emails"}
STATUS_NAMES = {"running", "complete", "checkpoint", "failed"}


def _domain(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def known_domains(runs_root: str | Path = DATA / "runs", exclude_run: str = "") -> set[str]:
    """Domains already pushed to the sheet by earlier runs (status priority/keep)."""
    known = set()
    for state in Path(runs_root).glob("*/prospects.json"):
        if state.parent.name == exclude_run:
            continue
        for p in load_state(state.parent):
            if p.status in ("priority", "keep"):
                known.add(_domain(p.website))
    return known


def filter_known(
    prospects: list[Prospect], known: set[str]
) -> tuple[list[Prospect], list[Prospect]]:
    kept = [p for p in prospects if _domain(p.website) not in known]
    skipped = [p for p in prospects if _domain(p.website) in known]
    return kept, skipped


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


def _validate_stage_status(stage: str, status: str) -> None:
    """Pre-flight guard for the label vocabulary — no network call, just a
    membership check. Raises ValueError on an unknown stage/status name."""
    if stage not in STAGE_NAMES:
        raise ValueError(f"unknown pipeline stage {stage!r} — must be one of {sorted(STAGE_NAMES)}")
    if status not in STATUS_NAMES:
        raise ValueError(f"unknown stage status {status!r} — must be one of {sorted(STATUS_NAMES)}")


@contextmanager
def _track_stage(run: str, stage: str):
    """Wraps one cmd_*'s body: opens/reuses the run's GitHub tracking issue,
    labels it status:running on entry, and on exit labels it status:complete
    (clean return), status:checkpoint + posts the resume comment (CheckpointPending,
    then re-raised so callers/exit-code handling see it unchanged), or
    status:failed (any other exception, then re-raised unchanged).

    Every gtm.github_state call is already safe to call unconditionally — it
    never raises; with no GITHUB_TOKEN configured (the common case for this repo
    today) it logs to data/errors.log and returns None/False, which we treat as
    "no issue to label" rather than an error. See gtm/github_state.py's module
    docstring for the log-and-skip contract this relies on.
    """
    _validate_stage_status(stage, "running")
    issue = github_state.open_run_issue(run, run_dir(run), stage=stage, status="running")
    if issue is not None:
        github_state.set_stage_labels(issue, run, stage, "running")
    try:
        yield
    except CheckpointPending as cp:
        if issue is not None:
            github_state.set_stage_labels(issue, run, stage, "checkpoint")
            github_state.post_checkpoint_comment(issue, cp.file, cp.action, cp.resume)
        raise
    except Exception:
        if issue is not None:
            github_state.set_stage_labels(issue, run, stage, "failed")
        raise
    else:
        if issue is not None:
            github_state.set_stage_labels(issue, run, stage, "complete")


def process_company(
    p: Prospect,
    *,
    scrape_fn=scrape,
    extract_fn=extract,
    hunt_fn=hunt_specs,
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
    p.case_evidence = ex.case_evidence
    p.us_made_ndaa = ex.us_made_ndaa
    if not p.drone_dimensions or not p.case_evidence:
        try:
            found = hunt_fn(p.company, p.drone_models, costlog=costlog)
            p.drone_dimensions = p.drone_dimensions or found.drone_dimensions
            p.drone_weights = p.drone_weights or found.drone_weights
            p.case_evidence = p.case_evidence or found.case_evidence
            ex.drone_dimensions, ex.drone_weights, ex.case_evidence = (
                p.drone_dimensions, p.drone_weights, p.case_evidence,
            )
        except Exception as e:
            _log_error(error_log, p.company, "spechunt", e)  # hunt is best-effort, never fatal
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


def merge_drafts(prospects: list[Prospect], raw: dict) -> None:
    for p in prospects:
        d = raw.get(p.company)
        if not d:
            continue
        initial, followup = d.get("draft_initial", {}), d.get("draft_followup", {})
        p.draft_initial_subject = initial.get("v1", {}).get("subject", "")
        p.draft_initial_body = initial.get("v1", {}).get("body", "")
        p.draft_initial_subject_alt = initial.get("v2", {}).get("subject", "")
        p.draft_initial_body_alt = initial.get("v2", {}).get("body", "")
        p.draft_followup_subject = followup.get("v1", {}).get("subject", "")
        p.draft_followup_body = followup.get("v1", {}).get("body", "")
        p.draft_followup_subject_alt = followup.get("v2", {}).get("subject", "")
        p.draft_followup_body_alt = followup.get("v2", {}).get("body", "")


# ---------------------------------------------------------------- CLI stages

def cmd_start(brief_path: str) -> None:
    brief = load_brief(brief_path)
    freeze_brief(brief, run_dir(brief.run))
    # `run` (brief.run) only becomes known above, mid-body — the tracking
    # wrapper starts here, not at the top of the function.
    with _track_stage(brief.run, "start"):
        costlog = CostLog(COSTS)
        prospects = [Prospect(company=company_from_url(u), website=u, source="brief") for u in brief.urls]
        if brief.query:
            from gtm.discover import discover

            for c in discover(brief.query, brief.max_companies, costlog=costlog):
                prospects.append(Prospect(company=c.company, website=c.website, source=f"serper:{brief.query}"))
        prospects = prospects[: brief.max_companies]
        prospects, skipped = filter_known(prospects, known_domains(exclude_run=brief.run))
        for p in skipped:
            print(f"[dup] {p.company} — already pushed by an earlier run, skipping")

        ex_by_company: dict[str, DroneExtraction] = {}
        for p in prospects:
            process_company(p, scrape_fn=lambda u: scrape_deep(u, preferred=brief.scraper), costlog=costlog)
            if p.status == "":
                ex_by_company[p.company] = DroneExtraction(
                    company_description=p.description,
                    drone_models=p.drone_models,
                    drone_dimensions=p.drone_dimensions,
                    drone_weights=p.drone_weights,
                    case_evidence=p.case_evidence,
                    us_made_ndaa=p.us_made_ndaa,
                )
            print(f"[{p.status or 'scraped'}] {p.company} — models={p.drone_models}")

        save_state(prospects, run_dir(brief.run))
        icp = ICP.read_text()
        print("\n=== FIT PROMPTS — Claude: score each, save {company: FitResult} to fit.json ===")
        for company, ex in ex_by_company.items():
            print(f"\n----- {company} -----")
            print(build_fit_prompt(icp, company, ex))

        if ex_by_company:
            raise CheckpointPending(
                file="fit.json",
                action="score prospects",
                resume=f"python -m gtm.run fit {brief.run} fit.json",
            )


def cmd_fit(run: str, fit_json: str) -> None:
    with _track_stage(run, "fit"):
        prospects = load_state(run_dir(run))
        raw = json.loads(Path(fit_json).read_text())
        merge_fit(prospects, {k: FitResult(**v) for k, v in raw.items()})
        save_state(prospects, run_dir(run))
        for p in prospects:
            print(f"[{p.status}] {p.company} score={p.fit_score}")


def cmd_enrich(run: str) -> None:
    from gtm.contacts import find_contacts, top_contact_fields
    from gtm.enrich import build_signal_prompt, enrich

    with _track_stage(run, "enrich"):
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
        needs_signals = False
        for p in prospects:
            if p.status in ("priority", "keep"):
                needs_signals = True
                print(f"\n----- {p.company} -----")
                print(build_signal_prompt(p))

        if needs_signals:
            raise CheckpointPending(
                file="signals.json",
                action="answer signal prompts",
                resume=f"python -m gtm.run signals {run} signals.json",
            )


def cmd_signals(run: str, signals_json: str) -> None:
    with _track_stage(run, "signals"):
        prospects = load_state(run_dir(run))
        merge_signals(prospects, json.loads(Path(signals_json).read_text()))
        save_state(prospects, run_dir(run))
        print("signals merged for", sum(1 for p in prospects if p.outreach_angle), "prospects")


def cmd_segment(run: str) -> None:
    with _track_stage(run, "segment"):
        prospects = load_state(run_dir(run))
        for p in prospects:
            if p.status in ("priority", "keep"):
                p.segment = assign_segment(p)
        save_state(prospects, run_dir(run))

        voice_guide = VOICE_GUIDE.read_text()
        print("\n=== DRAFT PROMPTS — Claude: draft each, save {company: {...}} to drafts.json ===")
        needs_draft = False
        for p in prospects:
            if p.status in ("priority", "keep"):
                needs_draft = True
                print(f"\n----- {p.company} -----")
                print(build_draft_prompt(voice_guide, p))

        if needs_draft:
            raise CheckpointPending(
                file="drafts.json",
                action="draft emails",
                resume=f"python -m gtm.run draft {run} drafts.json",
            )


def cmd_draft(run: str, drafts_json: str) -> None:
    with _track_stage(run, "draft"):
        prospects = load_state(run_dir(run))
        merge_drafts(prospects, json.loads(Path(drafts_json).read_text()))
        save_state(prospects, run_dir(run))

        n, flagged = 0, 0
        for p in prospects:
            if not p.draft_initial_subject:
                continue
            n += 1
            try:
                p.qa_flag = qa_check(p)
                if p.qa_flag:
                    flagged += 1
            except Exception as e:
                _log_error(ERROR_LOG, p.company, "qa", e)
        save_state(prospects, run_dir(run))
        print(f"{n} drafted, {flagged} flagged")


def cmd_output(run: str, dry_run: bool = False) -> None:
    import os

    from gtm.hubspot import push_to_hubspot
    from gtm.output import SERVICE_ACCOUNT_FILE, push_to_sheet, write_csv

    with _track_stage(run, "output"):
        prospects = load_state(run_dir(run))
        today = time.strftime("%Y-%m-%d")
        for p in prospects:
            p.date_processed = today
        save_state(prospects, run_dir(run))
        csv_path = run_dir(run) / "prospects.csv"
        n = write_csv(prospects, csv_path)
        print(f"wrote {n} prospects → {csv_path}")
        if Path(SERVICE_ACCOUNT_FILE).exists() and writes_enabled(not dry_run):
            pushed = push_to_sheet(prospects)
            print(f"pushed {pushed} rows to Google Sheet")
        elif dry_run:
            print("--dry-run — skipped Sheet push (CSV is ready)")
        else:
            print("no credentials/service_account.json — skipped Sheet push (CSV is ready)")

        if os.environ.get("HUBSPOT_SERVICE_KEY") and writes_enabled(not dry_run):
            to_hubspot = [p for p in prospects if p.status in ("priority", "keep")]
            pushed = push_to_hubspot(to_hubspot)
            print(f"pushed {pushed} companies to HubSpot")
        elif dry_run:
            print("--dry-run — skipped HubSpot push (CSV is ready)")
        else:
            print("no HUBSPOT_SERVICE_KEY — skipped HubSpot push (CSV is ready)")


def emails_for_prospect(p: Prospect, *, waterfall_fn=None) -> Prospect:
    from gtm.emails import split_contact_names, waterfall

    fn = waterfall_fn or waterfall
    domain = _domain(p.website)
    cells = []
    for name in split_contact_names(p.contact_name):
        r = fn(name, domain)
        cells.append(f"{r.email} ({r.status})" if r.email else "-")
    p.contact_emails = "; ".join(cells)
    return p


def cmd_emails(run: str) -> None:
    with _track_stage(run, "emails"):
        prospects = load_state(run_dir(run))
        for p in prospects:
            if p.status not in ("priority", "keep") or not p.contact_name:
                continue
            try:
                emails_for_prospect(p)
                print(f"[{p.company}] {p.contact_emails}")
            except Exception as e:
                _log_error(ERROR_LOG, p.company, "emails", e)
        save_state(prospects, run_dir(run))


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
    try:
        match args:
            case ["start", brief_path]:
                cmd_start(brief_path)
            case ["fit", run, fit_json]:
                cmd_fit(run, fit_json)
            case ["enrich", run]:
                cmd_enrich(run)
            case ["emails", run]:
                cmd_emails(run)
            case ["signals", run, signals_json]:
                cmd_signals(run, signals_json)
            case ["segment", run]:
                cmd_segment(run)
            case ["draft", run, drafts_json]:
                cmd_draft(run, drafts_json)
            case ["output", run]:
                cmd_output(run)
            case ["output", run, "--dry-run"]:
                cmd_output(run, dry_run=True)
            case ["learn"]:
                cmd_learn()
            case ["smoke", url]:
                from gtm.smoke import run_smoke

                run_smoke(url)
            case ["smoke", url, "--live"]:
                from gtm.smoke import run_smoke

                run_smoke(url, live=True)
            case _:
                print(__doc__)
                sys.exit(1)
    except CheckpointPending as cp:
        print(f"\nCheckpoint: {cp.action} — edit {cp.file} then resume:\n  {cp.resume}")
        sys.exit(int(ExitCode.CHECKPOINT))


if __name__ == "__main__":
    main()
