"""GitHub Issues adapter — one Issue per pipeline run tracks lifecycle via labels,
checkpoints posted as comments (Slice 6, Task 6.1). Built from the live doc research
in docs/tools/github-issues.md — read that first for endpoint shapes/gotchas.

Repo is hardcoded (only one repo is ever in play for this project). Auth token is
read from `os.environ["GITHUB_TOKEN"]` at call time, never at import time, matching
gtm/email_providers.py's pattern for reading provider keys.

Cross-cutting "log & skip" convention: every public function here catches all
`requests` failures (network errors, non-2xx responses) plus a missing token,
writes one line to `error_log`, and returns None/False instead of raising. A
GitHub-state-update failure must never take down a scrape/fit/enrich run.
"""
from __future__ import annotations

import time
from os import environ
from pathlib import Path

import requests

REPO_OWNER = "VladimirMickic"
REPO_NAME = "GTM-Zoki"
API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"

ERROR_LOG = Path("data") / "errors.log"

ISSUE_SIDECAR_NAME = ".github_issue"

_TIMEOUT = 20


def _log_error(error_log: Path, context: str, err: Exception | str) -> None:
    error_log.parent.mkdir(parents=True, exist_ok=True)
    with error_log.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} github_state [{context}] {err}\n")


def _headers() -> dict[str, str] | None:
    """None means "no token configured" — caller logs & skips, never raises."""
    token = environ.get("GITHUB_TOKEN")
    if not token:
        return None
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }


def open_run_issue(
    run: str,
    run_dir: Path,
    *,
    stage: str = "input",
    status: str = "running",
    error_log: Path = ERROR_LOG,
) -> int | None:
    """One Issue per run. Idempotent via a `.github_issue` sidecar in run_dir: if
    it already exists, read the stored issue number and return it — never call
    the create-issue API again (issue creation is not idempotent server-side).

    Returns the issue number, or None if creation failed / no token / sidecar
    was unreadable (logged to error_log in every failure case).
    """
    run_dir = Path(run_dir)
    sidecar = run_dir / ISSUE_SIDECAR_NAME
    if sidecar.exists():
        try:
            return int(sidecar.read_text().strip())
        except ValueError as e:
            _log_error(error_log, "open_run_issue:sidecar", e)
            return None

    headers = _headers()
    if headers is None:
        _log_error(error_log, "open_run_issue", "GITHUB_TOKEN not set")
        return None

    url = f"{API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    body = {
        "title": f"GTM run: {run}",
        "body": f"Run `{run}` started.",
        "labels": [f"run:{run}", f"stage:{stage}", f"status:{status}"],
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=_TIMEOUT)
    except requests.RequestException as e:
        _log_error(error_log, "open_run_issue", e)
        return None
    if resp.status_code != 201:
        _log_error(error_log, "open_run_issue", f"HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        issue_number = resp.json()["number"]
    except (ValueError, KeyError) as e:
        _log_error(error_log, "open_run_issue", e)
        return None

    run_dir.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(str(issue_number))
    return issue_number


def set_stage_labels(
    issue: int,
    run: str,
    stage: str,
    status: str,
    *,
    error_log: Path = ERROR_LOG,
) -> list[str] | None:
    """PUT-replaces the issue's entire label set with the 3 dimension labels
    (run/stage/status) in one call. PUT replaces all labels — it is not additive
    — so every call sends the complete 3-label set, never a delta, per
    docs/tools/github-issues.md.

    Note: the brief's signature was `(issue, stage, status)`; `run` is added here
    because the PUT is full-replace, so every call must know the run label too
    (there's no server-side merge to preserve it otherwise). See task report for
    the alternative considered (reading `run` back from the sidecar) and why this
    was preferred.

    Returns the label list sent, or None on failure (logged to error_log).
    """
    headers = _headers()
    if headers is None:
        _log_error(error_log, "set_stage_labels", "GITHUB_TOKEN not set")
        return None

    labels = [f"run:{run}", f"stage:{stage}", f"status:{status}"]
    url = f"{API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue}/labels"
    try:
        resp = requests.put(url, headers=headers, json={"labels": labels}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        _log_error(error_log, "set_stage_labels", e)
        return None
    if resp.status_code != 200:
        _log_error(error_log, "set_stage_labels", f"HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    return labels


def post_checkpoint_comment(
    issue: int,
    file: str,
    action: str,
    resume: str,
    *,
    error_log: Path = ERROR_LOG,
) -> bool:
    """Posts one checkpoint-pending comment. `file`/`action`/`resume` mirror
    gtm.control.CheckpointPending's fields — the intended caller (Task 6.2) is
    the CheckpointPending handler in gtm/run.py.

    Returns True on a 201, False on any failure (logged to error_log).
    """
    headers = _headers()
    if headers is None:
        _log_error(error_log, "post_checkpoint_comment", "GITHUB_TOKEN not set")
        return False

    body = f"Checkpoint: {action} pending (`{file}`). Resume: `{resume}`"
    url = f"{API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue}/comments"
    try:
        resp = requests.post(url, headers=headers, json={"body": body}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        _log_error(error_log, "post_checkpoint_comment", e)
        return False
    if resp.status_code != 201:
        _log_error(
            error_log, "post_checkpoint_comment", f"HTTP {resp.status_code}: {resp.text[:200]}"
        )
        return False
    return True
