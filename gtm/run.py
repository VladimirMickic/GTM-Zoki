"""S7b — orchestrator. Claude drives these subcommands, doing the judgment between them:

  python -m gtm.run start data/runs/<run>/brief.md   # discover/urls → scrape+extract → fit prompts
  python -m gtm.run fit <run> <fit.json>             # apply Claude's FitResults
  python -m gtm.run enrich <run>                     # passers: contacts + enrichment → signal prompts
  python -m gtm.run signals <run> <signals.json>     # apply Claude's buying_signals/outreach_angle
  python -m gtm.run segment <run>                    # bucket passers → draft prompts
  python -m gtm.run draft <run> <drafts.json>        # apply Claude's drafts → auto QA
  python -m gtm.run redraft <run> <drafts.json>      # apply fixed drafts for QA-flagged prospects → recheck (final)
  python -m gtm.run emails <run>                     # email waterfall (pattern → provider chain → AI hunt)
  python -m gtm.run output <run> [--dry-run]         # CSV (+ Sheet/HubSpot push unless --dry-run)
  python -m gtm.run learn                            # show feedback for ICP/denylist proposals
  python -m gtm.run postmortem <run>                 # mine this run's errors.log window → feedback(origin="run")
  python -m gtm.run smoke <url> [--live]             # one company, end-to-end; --live also pushes to Sheet

State = data/runs/<run>/prospects.json. Failures are logged to data/errors.log and the
company is skipped (status="error"), never the whole run.
"""
from __future__ import annotations

import json
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import gtm.github_state as github_state
from gtm.brief import freeze_brief, load_brief
from gtm.control import CheckpointPending, ExitCode, writes_enabled
from gtm.costlog import CostLog
from gtm.discover import _domain, _name_matches_domain
from gtm.draft import (
    NO_DRAFT_FLAG,
    bad_markers as draft_bad_markers,
    build_draft_prompt,
    build_redraft_prompt,
    check_batch_repetition,
    check_body_length,
    check_pain_grounding,
    check_reference_customer,
    check_spec_jargon,
    check_tier_distinctness,
    qa_check,
)
from gtm.extract import DroneExtraction, extract
from gtm.fit import FitResult, apply_fit, build_fit_prompt, check_disqualifiers, evidence_cap
from gtm.schema import DraftSet, Prospect
from gtm.scrape import scrape, scrape_deep
from gtm.segment import assign_segment
from gtm.spechunt import hunt_specs

DATA = Path("data")
ERROR_LOG = DATA / "errors.log"
COSTS = DATA / "costs.jsonl"
FEEDBACK = DATA / "feedback.jsonl"


def run_costlog(run: str) -> CostLog:
    """Per-run cost file so `cost of each run` is separable. Also arms the two
    ambient credit hooks: every serper_search (gtm.contacts) and every email
    finder/verifier call (gtm.email_providers) records its own credit into this
    file without being handed a costlog."""
    import gtm.contacts as contacts
    import gtm.email_providers as email_providers

    costlog = CostLog(run_dir(run) / "costs.jsonl")
    contacts.set_active_costlog(costlog)
    email_providers.set_active_costlog(costlog)
    return costlog


def _print_cost_summary(run: str) -> None:
    """The four spend units of a run, in one line: openai dollars, serper credits,
    email-vendor credits, Claude judgment tokens. Claude's share is charged here
    rather than at a call site — it is spent OUTSIDE this process, between stage
    commands, and only Claude Code's transcript records it (gtm/claudeusage.py)."""
    from gtm.claudeusage import record_delta

    costlog = CostLog(run_dir(run) / "costs.jsonl")
    try:
        record_delta(costlog, run_dir(run) / "claude_tokens.json")
    except OSError as e:  # transcript unreadable — never fail a stage over accounting
        _log_error(ERROR_LOG, "-", "claude token accounting", e)
    print(f"\ncost this run — {costlog.summary_line()}")
ICP = Path("company/ICP.md")
VOICE_GUIDE = Path("company/voice-guide.md")

# Task 6.2: GitHub Issues stage tracking (gtm/github_state.py, Task 6.1). One
# label vocabulary, fixed and small — matches the six cmd_* pipeline verbs and
# the lifecycle states a stage can be in. Validated once per stage transition
# (pre-flight, no network call) so a future typo here fails loud in tests
# instead of silently sending a garbage label to GitHub.
STAGE_NAMES = {"start", "fit", "enrich", "signals", "segment", "draft", "redraft", "output", "emails"}
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


def resolves(url: str, *, lookup=socket.gethostbyname) -> bool:
    """DNS-only preflight: does this host exist at all? Free, no API credit, ~ms.

    2026-07-30: run us-drone-20 spent scrapes on `pdw.aero` and `firestormlabs.io`,
    neither of which resolves — both were domains guessed from a company name. A
    guessed domain is cheap to propose and expensive to scrape, so check first.
    """
    host = _domain(url)
    if not host:
        return False
    try:
        lookup(host)
    except OSError:
        return False
    return True


def process_company(
    p: Prospect,
    *,
    scrape_fn=scrape,
    extract_fn=extract,
    hunt_fn=hunt_specs,
    error_log: Path = ERROR_LOG,
    costlog: CostLog | None = None,
    resolves_fn=resolves,
) -> Prospect:
    """Scrape + extract + deterministic disqualifiers for one company. Log & skip."""
    if not resolves_fn(p.website):
        _log_error(
            error_log, p.company, "preflight",
            ValueError(f"{p.website} does not resolve — guessed/dead domain, no scrape spent"),
        )
        p.status = "error"
        return p
    try:
        md = scrape_fn(p.website)
        ex: DroneExtraction = extract_fn(md, costlog=costlog)
    except Exception as e:
        _log_error(error_log, p.company, "scrape/extract", e)
        p.status = "error"
        return p
    if ex.company_name and not _name_matches_domain(ex.company_name, _domain(p.website)):
        # scraped page is real (a manufacturer's own domain, per discover()'s guard) but
        # extraction pulled a DIFFERENT company's name out of the page body — e.g. a
        # listicle/aggregator post about other makers, hosted on the site owner's own
        # domain. The extracted fields describe that other company, not the site's
        # owner, so none of them are trustworthy here.
        _log_error(
            error_log, p.company, "scrape/extract",
            ValueError(f"extracted company {ex.company_name!r} doesn't match {p.website} — likely an aggregator/listicle page"),
        )
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
    p.compliance_evidence = ex.compliance_evidence
    p.hq_city = ex.hq_city
    p.hq_country = ex.hq_country
    if not p.drone_dimensions or not p.case_evidence:
        try:
            found = hunt_fn(p.company, p.drone_models, costlog=costlog)
            p.drone_dimensions = p.drone_dimensions or found.drone_dimensions
            p.drone_weights = p.drone_weights or found.drone_weights
            p.case_evidence = p.case_evidence or found.case_evidence
            # Backfilled off the same two queries the hunt already paid for — no
            # extra Serper credit. The hunt never runs on its own account for this
            # field, so a site that publishes its certs keeps the scraped value.
            p.compliance_evidence = p.compliance_evidence or found.compliance_evidence
            ex.drone_dimensions, ex.drone_weights, ex.case_evidence = (
                p.drone_dimensions, p.drone_weights, p.case_evidence,
            )
            ex.compliance_evidence = p.compliance_evidence
        except Exception as e:
            _log_error(error_log, p.company, "spechunt", e)  # hunt is best-effort, never fatal
    dq = check_disqualifiers(ex)
    if dq:
        p.status = "drop"
        p.fit_score = 0
        p.fit_reason = dq
    return p


def apply_budget_scores(prospects: list[Prospect]) -> int:
    """Fold the deterministic Budget & procurement score into each passer's total and
    recompute its tier. Idempotent — a rerun of `gtm.run enrich` must not stack a
    second Budget line or double the points."""
    from gtm.budget import score_budget

    scored = 0
    for p in prospects:
        if p.status not in ("priority", "keep"):
            continue
        if "Budget & procurement" in (p.fit_reason or ""):
            continue
        points, line = score_budget(p)
        p.fit_score = min(p.fit_score + points, 100)
        p.fit_reason = f"{p.fit_reason}\n{line}".strip()
        p.status = "priority" if p.fit_score >= 70 else "keep" if p.fit_score >= 40 else "drop"
        scored += 1
    return scored


def merge_fit(prospects: list[Prospect], fits: dict[str, FitResult]) -> None:
    for p in prospects:
        if p.company in fits and p.status not in ("drop", "error"):
            apply_fit(
                p,
                fits[p.company],
                cap=evidence_cap(DroneExtraction(drone_models=p.drone_models,
                                                  drone_dimensions=p.drone_dimensions)),
            )


def merge_signals(prospects: list[Prospect], signals: dict[str, dict]) -> None:
    # Reject near-miss recency markers before anything is written to state — see
    # gtm/draft.py::bad_markers. Whole-stage abort, not log-and-skip: the file is
    # Claude's own output, so it's a fixable typo, not an unreachable third party.
    offenders = {
        company: bad
        for company, s in signals.items()
        if (bad := draft_bad_markers(s.get("buying_signals", []) or []))
    }
    if offenders:
        lines = "\n".join(f"  {c}: {b[0]}" for c, b in offenders.items())
        raise ValueError(
            "recency marker must be exactly '[stale]' or '[undated]', nothing else inside "
            f"the brackets:\n{lines}"
        )
    for p in prospects:
        s = signals.get(p.company)
        if s:
            p.buying_signals = s.get("buying_signals", [])
            p.outreach_angle = s.get("outreach_angle", "")
            p.trigger_phrase = s.get("trigger_phrase", p.trigger_phrase)
            # Default to the prospect's existing value, not []: cmd_enrich prints the
            # signal prompt and the displacement prompt as two separate blocks for the
            # same company, so an entry that only answers the signal prompt omits this
            # key entirely — that must not silently wipe ammo already merged/set.
            p.competitor_weaknesses = s.get("competitor_weaknesses", p.competitor_weaknesses)
            # cmd_enrich seeds this with gpt-4o-mini's candidates (Gate 0/1 only —
            # topical, not pain-judged); Claude re-judges pain-vs-satisfied here and
            # this overwrites the candidate list. Missing key = not yet reviewed,
            # keep the candidates rather than wiping them (see gtm/enrich.py).
            p.community_signals = s.get("community_signals", p.community_signals)


def missing_trigger_phrase(prospects: list[Prospect]) -> list[str]:
    """Passers that have buying_signals but no trigger_phrase, in run order.

    2026-07-29: 2 of 3 companies in us-drone-19 left the signals stage with an empty
    trigger_phrase and nothing anywhere said so. It is not a harmless blank —
    gtm/render.py::_trigger_event reads it verbatim, so an empty phrase leaves
    {{trigger_event}} unrendered and the ship gate in gtm/output.py blanks the whole
    contact row. Signals is the last stage where fixing it is free, so it warns here.

    A company with NO buying_signals is excluded: there is nothing to build a phrase
    from, so its empty value is honest rather than a silent miss."""
    return [
        p.company
        for p in prospects
        if p.status in ("priority", "keep") and p.buying_signals and not p.trigger_phrase
    ]


def merge_drafts(prospects: list[Prospect], raw: dict) -> None:
    for p in prospects:
        tiers = raw.get(p.company)
        if not tiers:
            continue
        for tier, d in tiers.items():
            initial = d.get("draft_initial", {})
            # setdefault + in-place attribute writes (not a fresh DraftSet) so an
            # existing tier's qa_flag survives a content-only re-merge — the
            # cmd_redraft round-trip depends on this (see Task 8's docstring note).
            draft = p.drafts_by_tier.setdefault(tier, DraftSet())
            draft.pain_points = d.get("pain_points", draft.pain_points)
            draft.talking_points = d.get("talking_points", draft.talking_points)
            draft.initial_subject = initial.get("v1", {}).get("subject", "")
            draft.initial_body = initial.get("v1", {}).get("body", "")
            draft.initial_subject_alt = initial.get("v2", {}).get("subject", "")
            draft.initial_body_alt = initial.get("v2", {}).get("body", "")
            draft.needs_research = not draft.initial_subject


# ---------------------------------------------------------------- CLI stages

def cmd_start(brief_path: str) -> None:
    from gtm.learn import LESSONS_FILE

    if LESSONS_FILE.exists():
        print(LESSONS_FILE.read_text())  # bounded to _LESSONS_MAX_LINES by write_lessons, no cost
    brief = load_brief(brief_path)
    freeze_brief(brief, run_dir(brief.run))
    # `run` (brief.run) only becomes known above, mid-body — the tracking
    # wrapper starts here, not at the top of the function.
    with _track_stage(brief.run, "start"):
        costlog = run_costlog(brief.run)
        prospects = [Prospect(company=company_from_url(u), website=u, source="brief") for u in brief.urls]
        if brief.query:
            from gtm.discover import discover

            for c in discover(
                brief.query,
                brief.max_companies,
                costlog=costlog,
                require_us=brief.require_us,
                region=brief.region,
            ):
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

        _print_cost_summary(brief.run)
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
        # Spends no API credit itself, but the Claude scoring it applies is the
        # single most expensive judgment in the pipeline — CLAUDE.md wants every
        # stage's reply to close with the run total, so it has to print one.
        _print_cost_summary(run)


def cmd_enrich(run: str) -> None:
    from gtm.contacts import find_contacts, top_contact_fields, top_contact_flags
    from gtm.displace import build_displacement_prompt, detect_competitor, detect_inhouse_case
    from gtm.enrich import build_signal_prompt, enrich

    with _track_stage(run, "enrich"):
        costlog = run_costlog(run)  # arms serper credit logging for enrich + contacts
        prospects = load_state(run_dir(run))
        for p in prospects:
            if p.status not in ("priority", "keep"):
                continue
            try:
                enrich(p, costlog=costlog)
                contacts = find_contacts(p.company)
                if contacts:
                    p.contact_name, p.contact_title, p.contact_linkedin = top_contact_fields(contacts)
                    p.contact_verified = top_contact_flags(contacts)
                # case_evidence only — never community_signals. competitor is asserted
                # as fact downstream ("{company} currently ships in a {competitor} case",
                # gtm/draft.py), and community_signals cannot support that: the
                # competitor-pain query (gtm/enrich.py::_COMPETITOR_QUERY) is
                # category-wide with no company name in it. Competitor pain still
                # reaches the draft as generic market pain via community_signals.
                p.competitor = detect_competitor(p.case_evidence)
                # Mutually exclusive by construction (detect_inhouse_case defers to
                # a named brand): a bought case is a competitor, a self-tooled one
                # is a manufacturing line we take over instead.
                p.inhouse_case = detect_inhouse_case(p.case_evidence)
            except Exception as e:
                _log_error(ERROR_LOG, p.company, "enrich/contacts", e)
        n_scored = apply_budget_scores(prospects)
        print(f"budget scored for {n_scored} prospect(s)")
        save_state(prospects, run_dir(run))
        print("\n=== SIGNAL PROMPTS — Claude: answer each, save {company: {...}} to signals.json ===")
        needs_signals = False
        for p in prospects:
            if p.status in ("priority", "keep"):
                needs_signals = True
                print(f"\n----- {p.company} -----")
                print(build_signal_prompt(p))
                if p.competitor:
                    print(f"\n----- {p.company} [displacement: {p.competitor}] -----")
                    print(build_displacement_prompt(p.company, p.competitor))
                elif p.inhouse_case:
                    print(f"\n----- {p.company} [displacement: {p.inhouse_case}] -----")
                    print(build_displacement_prompt(p.company, p.inhouse_case, inhouse=True))

        _print_cost_summary(run)
        if needs_signals:
            raise CheckpointPending(
                file="signals.json",
                action="answer signal prompts",
                resume=f"python -m gtm.run signals {run} signals.json",
            )


def cmd_signals(run: str, signals_json: str) -> None:
    from gtm.enrich import redate_undated_signals

    with _track_stage(run, "signals"):
        costlog = run_costlog(run)  # arms serper+openai accounting for the dating pass below
        prospects = load_state(run_dir(run))
        merge_signals(prospects, json.loads(Path(signals_json).read_text()))
        dated_total = 0
        for p in prospects:
            if p.status in ("priority", "keep") and p.buying_signals:
                dated_total += redate_undated_signals(p, costlog=costlog)
        save_state(prospects, run_dir(run))
        print("signals merged for", sum(1 for p in prospects if p.outreach_angle), "prospects")
        if dated_total:
            print(f"dated {dated_total} previously-[undated] signal(s) via follow-up search")
        blank = missing_trigger_phrase(prospects)
        if blank:
            print(
                f"warning: no trigger_phrase for {', '.join(blank)} — "
                "{{trigger_event}} cannot render, and any draft that uses it will be "
                "blanked at output. Add a short noun phrase per company to the signals "
                "JSON and re-run this stage."
            )
        _print_cost_summary(run)


def cmd_segment(run: str) -> None:
    from gtm.persona import distinct_tiers_present

    with _track_stage(run, "segment"):
        prospects = load_state(run_dir(run))
        for p in prospects:
            if p.status in ("priority", "keep"):
                p.segment = assign_segment(p)
        save_state(prospects, run_dir(run))

        voice_guide = VOICE_GUIDE.read_text()
        print("\n=== DRAFT PROMPTS — Claude: draft each, save {company: {tier: {...}}} to drafts.json ===")
        needs_draft = False
        for p in prospects:
            if p.status in ("priority", "keep"):
                needs_draft = True
                tiers = distinct_tiers_present(p.contact_title)
                for tier in tiers:
                    print(f"\n----- {p.company} [{tier}] -----")
                    print(build_draft_prompt(voice_guide, p, tier, sibling_tiers=tiers))

        _print_cost_summary(run)  # before the checkpoint raise, or it never prints
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

        costlog = run_costlog(run)
        others = [x.company for x in prospects]
        n, flagged, thin = 0, 0, 0
        for p in prospects:
            for tier, draft in p.drafts_by_tier.items():
                if not draft.initial_subject:
                    draft.qa_flag = NO_DRAFT_FLAG
                    thin += 1
                    continue
                n += 1
                try:
                    # Deterministic guards run first and short-circuit the paid
                    # qa_check: a draft naming a run-mate as our customer, or reusing
                    # another tier's skeleton, is broken regardless of whether every
                    # factual claim in it checks out.
                    flag = (
                        check_reference_customer(p, draft, others)
                        or check_tier_distinctness(p, tier, draft)
                        or check_batch_repetition(p, draft, prospects)
                        or check_pain_grounding(p, draft)
                        or check_spec_jargon(draft)
                        or check_body_length(p, draft)
                        or qa_check(p, draft, costlog=costlog)
                    )
                    draft.qa_flag = flag or "passed"
                    if flag:
                        flagged += 1
                except Exception as e:
                    _log_error(ERROR_LOG, p.company, "qa", e)
        save_state(prospects, run_dir(run))
        print(f"{n} drafted, {flagged} flagged, {thin} talking-points-only (signal too thin to draft)")
        _print_cost_summary(run)

        needs_redraft = [
            (p, tier, draft)
            for p in prospects
            for tier, draft in p.drafts_by_tier.items()
            if draft.qa_flag and draft.qa_flag not in ("passed", NO_DRAFT_FLAG)
        ]
        if needs_redraft:
            voice_guide = VOICE_GUIDE.read_text()
            print("\n=== REDRAFT PROMPTS — Claude: fix the flagged claim, save {company: {tier: {...}}} to drafts.json ===")
            for p, tier, draft in needs_redraft:
                print(f"\n----- {p.company} [{tier}] (flagged: {draft.qa_flag}) -----")
                print(build_redraft_prompt(voice_guide, p, tier, draft))
            raise CheckpointPending(
                file="drafts.json",
                action="redraft flagged emails (qa fact-check failed)",
                resume=f"python -m gtm.run redraft {run} drafts.json",
            )


def cmd_redraft(run: str, drafts_json: str) -> None:
    """Single retry after a qa_check failure (cmd_draft's checkpoint): merges the
    fixed drafts, re-checks only the previously-flagged (prospect, tier) pairs,
    and finalizes each qa_flag to "passed" or the (final) failure text — no
    further checkpoint, so this never loops more than once."""
    with _track_stage(run, "redraft"):
        prospects = load_state(run_dir(run))
        merge_drafts(prospects, json.loads(Path(drafts_json).read_text()))
        save_state(prospects, run_dir(run))

        costlog = run_costlog(run)
        others = [x.company for x in prospects]
        n, still_flagged = 0, 0
        for p in prospects:
            for tier, draft in p.drafts_by_tier.items():
                if not draft.initial_subject or draft.qa_flag in ("", "passed", NO_DRAFT_FLAG):
                    continue
                n += 1
                try:
                    flag = (
                        check_reference_customer(p, draft, others)
                        or check_tier_distinctness(p, tier, draft)
                        or check_batch_repetition(p, draft, prospects)
                        or check_pain_grounding(p, draft)
                        or check_spec_jargon(draft)
                        or check_body_length(p, draft)
                        or qa_check(p, draft, costlog=costlog)
                    )
                    draft.qa_flag = flag or "passed"
                    if flag:
                        still_flagged += 1
                except Exception as e:
                    _log_error(ERROR_LOG, p.company, "qa", e)
        save_state(prospects, run_dir(run))
        print(f"{n} redrafted, {still_flagged} still flagged after retry")
        _print_cost_summary(run)


def cmd_output(run: str, dry_run: bool = False) -> None:
    import os

    from gtm.hubspot import push_to_hubspot
    from gtm.output import (
        OUTREACH_TOKENS,
        SERVICE_ACCOUNT_FILE,
        blocked_row_tokens,
        by_fit_score,
        no_draft_summary,
        push_contacts_to_sheet,
        push_to_sheet,
        unrendered_summary,
        unverified_summary,
        write_contacts_csv,
        write_csv,
    )

    with _track_stage(run, "output"):
        prospects = load_state(run_dir(run))
        today = time.strftime("%Y-%m-%d")
        for p in prospects:
            p.date_processed = today
        save_state(prospects, run_dir(run))
        # Best fit first — same order drives the CSVs, both sheet tabs, and the
        # HubSpot push. A domain already on the Sheet still refreshes in place
        # (push_to_sheet), so this reorders new appends only, not existing rows.
        prospects = by_fit_score(prospects)
        csv_path = run_dir(run) / "prospects.csv"
        contacts_csv_path = run_dir(run) / "prospects_contacts.csv"
        n = write_csv(prospects, csv_path)
        nc = write_contacts_csv(prospects, contacts_csv_path)
        print(f"wrote {n} prospects → {csv_path}")
        print(f"wrote {nc} contacts → {contacts_csv_path}")
        unverified = unverified_summary(prospects)
        if unverified:
            print(
                f"{unverified} contact row{'s' if unverified > 1 else ''} blocked from send — "
                "nothing in the SERP ties that person to that company (see each row's "
                "qa_flag); confirm on LinkedIn before sending"
            )
        undrafted = no_draft_summary(prospects)
        if undrafted:
            print(
                f"{undrafted} contact row{'s have' if undrafted > 1 else ' has'} no email copy — "
                "their persona tier was added after the draft stage ran; re-run "
                f"`python -m gtm.run segment {run}` and redraft to cover them"
            )
        blocked = unrendered_summary(prospects)
        if blocked:
            tokens = blocked_row_tokens(prospects)
            fix = (
                " — fill company/outreach.md"
                if any(t in OUTREACH_TOKENS for t in tokens)
                else ""
            )
            print(
                f"{blocked} contact row{'s' if blocked > 1 else ''} blocked from send — no "
                f"value behind {', '.join(tokens)} (see each row's qa_flag){fix}"
            )
        if Path(SERVICE_ACCOUNT_FILE).exists() and writes_enabled(not dry_run):
            pushed = push_to_sheet(prospects)
            pushed_contacts = push_contacts_to_sheet(prospects)
            print(f"pushed {pushed.total} rows to Google Sheet ({pushed})")
            print(f"pushed {pushed_contacts.total} rows to Contacts tab ({pushed_contacts})")
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

        _print_cost_summary(run)  # final: full run spend, bucketed by provider


def emails_for_prospect(p: Prospect, *, waterfall_fn=None) -> Prospect:
    from gtm.emails import EmailResult, candidate_domains, split_contact_names, waterfall

    fn = waterfall_fn or waterfall
    # Aliases matter: a company's press/product domain often isn't the domain in
    # `website` (redcatholdings.com vs redcat.red), and the pattern tier can only
    # hit a mailbox on a domain it actually tries.
    domains = candidate_domains(p.website, p.company, p.key_news) or [_domain(p.website)]
    cells = []
    for name in split_contact_names(p.contact_name):
        try:
            r = fn(name, domains[0], domains=domains)
        except Exception as e:  # one contact's failure must not zero out the others'
            _log_error(ERROR_LOG, p.company, f"emails/{name}", e)
            r = EmailResult()
        if r.email:
            cells.append(f"{r.email} ({r.status})")
        else:
            # "-" is a genuine miss; "- (no-finder-key)" means nothing was searched.
            cells.append(f"- ({r.status})" if r.status else "-")
    p.contact_emails = "; ".join(cells)
    return p


def cmd_emails(run: str) -> None:
    with _track_stage(run, "emails"):
        run_costlog(run)  # arms serper credit logging for the email waterfall
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
        _print_cost_summary(run)


def cmd_learn() -> None:
    from gtm.learn import LESSONS_FILE, eligible_for_proposal, load_feedback, write_lessons

    entries = load_feedback(FEEDBACK, limit=50)  # bounded read (credit rule)
    if not entries:
        print("no feedback yet (data/feedback.jsonl)")
        return

    user_entries = eligible_for_proposal(entries)
    session_entries = [e for e in entries if e.origin != "user"]

    print(f"=== last {len(entries)} feedback entries ===")
    if user_entries:
        print(f"\n--- {len(user_entries)} from the user — Claude: propose ICP/denylist edits from these only ---")
        for e in user_entries:
            print(e.model_dump_json())
    else:
        print("\n--- none of these are user-sourced — no ICP/denylist edit should be proposed this run ---")
    if session_entries:
        print(f"\n--- {len(session_entries)} session/smoke-test notes — context only, not actionable ---")
        for e in session_entries:
            print(e.model_dump_json())

    path = write_lessons(entries, LESSONS_FILE)
    print(f"\nwrote {path} ({sum(1 for _ in path.read_text().splitlines())} lines)")


def cmd_postmortem(run: str) -> None:
    from gtm.postmortem import run_postmortem

    n = run_postmortem(run)
    if n == 0:
        print(f"postmortem {run}: nothing new (clean run, or already postmortemed)")
    else:
        print(f"postmortem {run}: recorded {n} failure-pattern entr{'y' if n == 1 else 'ies'} to {FEEDBACK}")
        print("run `python -m gtm.run learn` to fold these into data/lessons.md")


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
            case ["redraft", run, drafts_json]:
                cmd_redraft(run, drafts_json)
            case ["output", run]:
                cmd_output(run)
            case ["output", run, "--dry-run"]:
                cmd_output(run, dry_run=True)
            case ["learn"]:
                cmd_learn()
            case ["postmortem", run]:
                cmd_postmortem(run)
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
