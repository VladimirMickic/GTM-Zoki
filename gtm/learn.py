"""Learn stage — read data/feedback.jsonl, split what may drive an ICP/denylist
edit proposal from what's just session history.

Only Feedback.origin == "user" entries are eligible: those are feedback a person
actually gave. Everything else (the default) is Claude's own dev-log/smoke-test
note from a past session — real information worth keeping, but not the user's
judgment call, so it must never drive a company/ICP.md or company/denylist.md
edit on its own (2026-07-30, user: "Only if user provides feedback you record it").
"""
from __future__ import annotations

from pathlib import Path

from gtm.schema import Feedback


def load_feedback(path: str | Path, *, limit: int = 50) -> list[Feedback]:
    """Last `limit` entries (bounded read, credit rule), parsed and validated.
    A line that fails to parse is skipped rather than crashing the whole read —
    matches the log-and-skip contract the rest of the pipeline uses."""
    path = Path(path)
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-limit:]
    entries = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entries.append(Feedback.model_validate_json(line))
        except ValueError:
            continue
    return entries


def record_feedback(
    path: str | Path, *, date: str, run: str, company: str, feedback: str, origin: str = "user"
) -> None:
    """Append one entry. Default origin="user" — this is the entrypoint for
    recording what a user actually said; a session/smoke-test write-up should
    pass origin="session" explicitly."""
    entry = Feedback(date=date, run=run, company=company, feedback=feedback, origin=origin)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(entry.model_dump_json() + "\n")


def eligible_for_proposal(entries: list[Feedback]) -> list[Feedback]:
    """Entries a user actually gave — the only ones allowed to drive a proposed
    ICP.md/denylist.md edit."""
    return [e for e in entries if e.origin == "user"]
