"""Claude-side token accounting, read from Claude Code's own session transcript.

Every other provider in this pipeline is called BY the pipeline, so gtm/costlog.py
can charge it at the call site. Claude is the opposite: it orchestrates from outside
the process, and the judgment tokens it spends between two stage commands (scoring
fit, writing signals, drafting copy) are invisible to every `python -m gtm.run`
invocation. Claude Code does record them — ~/.claude/projects/<slug>/*.jsonl, one
`message.usage` block per API response — so that transcript is the only honest source.

Accounting model: the transcript is a monotonically increasing counter (old session
files never change, new ones only append), so each stage command records the DELTA
since the previous stage command. That delta is exactly the judgment window between
the two. Two consequences worth knowing before trusting the number:

  * tokens spent after a run's LAST stage command — including the reply reporting
    the run — land in whatever run runs a stage next, or nowhere;
  * the delta is wall-clock, not topic-scoped. Time spent in the same session on
    something else (debugging, a code review) is charged to the next stage command
    that happens to run. Treat the figure as "Claude tokens burned in this session
    since the previous stage", which is what it literally is.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"


def transcript_dir(project_dir: str | Path | None = None) -> Path:
    """Claude Code's transcript directory for `project_dir` (default: cwd).

    The slug is the absolute path with every non-alphanumeric character replaced by
    a dash, so "/Users/x/GTM Helper" becomes "-Users-x-GTM-Helper".
    """
    path = Path(project_dir) if project_dir is not None else Path(os.getcwd())
    return TRANSCRIPT_ROOT / re.sub(r"[^A-Za-z0-9]", "-", str(path.resolve()))


def cumulative_tokens(directory: str | Path | None = None) -> tuple[int, int]:
    """(tokens_in, tokens_out) across every session transcript in `directory`.

    Input counts cache reads and cache writes as well as fresh input — they are all
    billed input. Deduped by `message.id`: one API response is written to the
    transcript once per content block, each copy repeating the same usage object
    (session 4663ce38: 395 usage lines, 157 actual responses), so a naive sum
    overstates by ~2.5x.
    """
    directory = Path(directory) if directory is not None else transcript_dir()
    if not directory.is_dir():
        return 0, 0
    seen: set[str] = set()
    tokens_in = tokens_out = 0
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(errors="replace") as f:
            for line in f:
                if '"usage"' not in line:  # cheap pre-filter, most lines are not responses
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue  # a partially-flushed final line while a session is live
                message = entry.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                key = message.get("id") or entry.get("uuid") or ""
                if key and key in seen:
                    continue
                seen.add(key)
                tokens_in += (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                )
                tokens_out += usage.get("output_tokens", 0)
    return tokens_in, tokens_out


def record_delta(costlog, position_file: str | Path, *, directory=None, stage: str = "judgment") -> tuple[int, int]:
    """Charge `costlog` for the Claude tokens spent since the last call, and remember
    where we got to. Returns the delta.

    The first call on a run only sets the baseline — there is no earlier mark to
    measure from, and charging a run for the whole transcript's history would be
    nonsense.
    """
    position_file = Path(position_file)
    tokens_in, tokens_out = cumulative_tokens(directory)
    previous = None
    if position_file.exists():
        try:
            previous = json.loads(position_file.read_text())
        except ValueError:
            previous = None
    position_file.parent.mkdir(parents=True, exist_ok=True)
    position_file.write_text(json.dumps({"tokens_in": tokens_in, "tokens_out": tokens_out}))
    if previous is None:
        return 0, 0
    delta_in = max(0, tokens_in - previous.get("tokens_in", 0))
    delta_out = max(0, tokens_out - previous.get("tokens_out", 0))
    if delta_in or delta_out:
        costlog.record(
            stage=stage,
            model="claude",
            provider="claude",
            tokens_in=delta_in,
            tokens_out=delta_out,
            cost_usd=0.0,  # tokens only: Claude Code bills the subscription, not this run
        )
    return delta_in, delta_out
