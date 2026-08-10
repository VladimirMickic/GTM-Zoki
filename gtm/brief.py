"""Per-run brief: markdown file with YAML frontmatter, the single source of truth for a run."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, model_validator

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)

# `run` names a directory under data/runs that every stage writes into, so it is a
# filename, not free text. 2026-08-10, Strix run gtm-helper_eea7 (CWE-23): nothing checked
# it, so `run: ../../../tmp/pwn` in a brief made freeze_brief, save_state and the output
# CSVs all write outside data/runs. Allowlist beats blocklist here — the set of names a
# run legitimately wants (us-drone-20, teal-demo, hyl_v2.1) is small and boring.
_SAFE_RUN_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def safe_run_name(run: str) -> str:
    """The run name, or ValueError. Rejects separators, traversal, leading dots and
    anything else that would not stay a single directory under data/runs."""
    name = str(run)
    if ".." in name or not _SAFE_RUN_NAME.match(name):
        raise ValueError(
            f"unsafe run name {run!r} — use letters, digits, '.', '-' or '_' only, "
            "starting with a letter or digit"
        )
    return name


class Brief(BaseModel):
    run: str
    urls: list[str] = []
    query: Optional[str] = None
    scraper: str = "crawl4ai"
    max_companies: int = 10
    # 2026-07-28: geography stopped being an ICP constraint (company/ICP.md). US-only
    # is now an explicit per-run opt-in — set `require_us: true` in the brief's
    # frontmatter when the run genuinely needs NDAA/Blue-UAS-eligible manufacturers.
    # It filters *input*, before scoring; the fit rubric itself never sees it.
    require_us: bool = False
    # 2026-07-30: a missing region used to stop the run and cost a question ("no region
    # field to fall back on"). Now it falls back here. `us` is the default because every
    # run to date has been US; set `region: uk` / `region: ""` (worldwide) to change it.
    # Shapes the discover query only — `urls:` runs and the fit rubric never see it.
    region: str = "us"
    # 2026-08-03: `known_domains()` (gtm/run.py) bans every domain any earlier run
    # marked priority/keep, permanently and repo-wide. After ~30 demo runs that starves
    # discovery, and the workaround being reached for was moving old run directories out
    # of data/runs — which does un-ban them, but also erases the demo record and re-arms
    # duplicate rows against the live Sheet and HubSpot with no warning. This flag is the
    # narrow version: one run may re-admit already-pushed domains, every run directory
    # stays exactly where it is, and each re-admission prints which earlier run pushed it.
    # Default False, so no existing brief changes behaviour.
    allow_known: bool = False

    @model_validator(mode="after")
    def _safe_run(self) -> "Brief":
        # Validated at load time as well as in run_dir(): the brief is where an unsafe
        # value gets in, and failing here means no stage ever sees it.
        safe_run_name(self.run)
        return self

    @model_validator(mode="after")
    def _needs_input(self) -> "Brief":
        if not self.urls and not self.query:
            raise ValueError("brief needs urls or query")
        return self


def load_brief(path: str | Path) -> Brief:
    text = Path(path).read_text()
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError(f"{path}: no YAML frontmatter found")
    data = yaml.safe_load(m.group(1)) or {}
    return Brief(**{k: v for k, v in data.items() if v is not None})


def freeze_brief(brief: Brief, rdir: str | Path) -> Path:
    """Write brief.lock.json inside rdir, freezing the brief for this run.

    Idempotent: calling again with an identical brief is a no-op. Calling with
    a brief whose content differs from the existing lock raises ValueError.
    """
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)
    lock_path = rdir / "brief.lock.json"
    dump = brief.model_dump()
    if lock_path.exists():
        existing = json.loads(lock_path.read_text())
        if existing == dump:
            return lock_path
        raise ValueError("brief already frozen")
    lock_path.write_text(json.dumps(dump))
    return lock_path


def load_frozen(rdir: str | Path) -> Brief:
    """Reconstruct the Brief frozen for this run from brief.lock.json."""
    text = (Path(rdir) / "brief.lock.json").read_text()
    return Brief(**json.loads(text))
