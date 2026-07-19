"""Per-run brief: markdown file with YAML frontmatter, the single source of truth for a run."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, model_validator

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


class Brief(BaseModel):
    run: str
    urls: list[str] = []
    query: Optional[str] = None
    scraper: str = "crawl4ai"
    max_companies: int = 10

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
