"""Postmortem stage — after a run finishes, mine `data/errors.log` for failures that
belong to THAT run and record them as bounded, factual `Feedback(origin="run")` entries.

This is deliberately narrower than the two deleted skills (`cold-email`,
`prospect-research`) that drifted from the code they mirrored: it never edits code,
never proposes an ICP/denylist change (only `Feedback.origin == "user"` may do that,
see `gtm/learn.py`), and it never calls an LLM — pure log parsing, zero credit cost.
It exists so a bug caught by eye mid-session (2026-07-30: a near-miss "[undated]"
marker, two dead guessed domains) is remembered next session instead of living only in
a scratch handoff doc.

`data/errors.log` has no run field of its own (every stage's `_log_error` writes
`TIMESTAMP <company-or-module> [<stage>] <message>`), so a run's own slice of that
shared file is recovered from its own `costs.jsonl` timestamps — the one file that IS
already scoped to a single run.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from gtm.learn import record_feedback
from gtm.run import ERROR_LOG, FEEDBACK, run_dir

_ERROR_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}) (?P<company>.+?) \[(?P<stage>[^\]]+)\] (?P<message>.*)$"
)
_TS_FMT = "%Y-%m-%dT%H:%M:%S"
# Errors can land just before the run's first billed call (a DNS preflight or scrape
# failure happens before anything reaches costs.jsonl) or just after its last one (a
# best-effort spechunt failure logged after the extract's cost was already recorded).
_WINDOW_BUFFER = timedelta(minutes=5)

_EXAMPLE_MAX_CHARS = 160
_MAX_COMPANIES_LISTED = 3


def _run_window(run: str) -> tuple[datetime, datetime] | None:
    """(start, end) from that run's own costs.jsonl — None if the run never recorded
    a billed call (e.g. every company failed before extraction). Reads the jsonl
    directly rather than through CostLog, which has no public accessor for entries."""
    path = run_dir(run) / "costs.jsonl"
    if not path.exists():
        return None
    stamps = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            ts = json.loads(line).get("ts")
        except ValueError:
            continue
        if ts:
            stamps.append(datetime.strptime(ts, _TS_FMT))
    stamps.sort()
    return (stamps[0], stamps[-1]) if stamps else None


def parse_errors(error_log: str | Path = ERROR_LOG) -> list[dict]:
    """Every parseable line in errors.log. A line that doesn't match the format is
    skipped, matching the log-and-skip contract the rest of the pipeline uses."""
    path = Path(error_log)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        m = _ERROR_LINE_RE.match(line)
        if m:
            out.append(m.groupdict())
    return out


def errors_in_window(
    errors: list[dict], window: tuple[datetime, datetime], *, buffer: timedelta = _WINDOW_BUFFER
) -> list[dict]:
    start, end = window
    start, end = start - buffer, end + buffer
    return [e for e in errors if start <= datetime.strptime(e["ts"], _TS_FMT) <= end]


def classify(errors: list[dict]) -> list[str]:
    """One feedback line per distinct failure stage — a count, an example message,
    and up to 3 companies it hit. Grouping by `stage` (the bracketed tag every
    `_log_error` call already carries: "preflight", "scrape/extract",
    "GetProspectProvider/verify", ...) needs no new taxonomy."""
    by_stage: dict[str, list[dict]] = {}
    for e in errors:
        by_stage.setdefault(e["stage"], []).append(e)

    lines = []
    for stage, group in sorted(by_stage.items()):
        companies = sorted({e["company"] for e in group})
        shown = companies[:_MAX_COMPANIES_LISTED]
        more = f" (+{len(companies) - _MAX_COMPANIES_LISTED} more)" if len(companies) > _MAX_COMPANIES_LISTED else ""
        example = group[0]["message"].strip()
        if len(example) > _EXAMPLE_MAX_CHARS:
            example = example[:_EXAMPLE_MAX_CHARS].rsplit(" ", 1)[0] + "..."
        n = len(group)
        lines.append(f"{n}x [{stage}] {example} — hit: {', '.join(shown)}{more}")
    return lines


def already_recorded(run: str, *, feedback_path: str | Path = FEEDBACK) -> bool:
    """A run should only be postmortemed once — rerunning `postmortem` on the same
    run must not pile up duplicate entries."""
    path = Path(feedback_path)
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("origin") == "run" and d.get("run") == run:
            return True
    return False


def run_postmortem(run: str, *, feedback_path: str | Path = FEEDBACK, error_log: str | Path = ERROR_LOG) -> int:
    """Mine this run's own errors and append one Feedback(origin="run") entry per
    distinct failure stage. Returns how many entries were written; 0 means either a
    clean run or one already postmortemed."""
    if already_recorded(run, feedback_path=feedback_path):
        return 0
    window = _run_window(run)
    if window is None:
        return 0
    errors = errors_in_window(parse_errors(error_log), window)
    lines = classify(errors)
    today = datetime.now().strftime("%Y-%m-%d")
    for line in lines:
        record_feedback(feedback_path, date=today, run=run, company="-", feedback=line, origin="run")
    return len(lines)
