"""Per-run brief: markdown file with YAML frontmatter, the single source of truth for a run."""
from __future__ import annotations

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
