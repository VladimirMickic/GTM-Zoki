"""Append-only per-stage cost/token log (jsonl), LeadGrow status-style."""
from __future__ import annotations

import json
import time
from pathlib import Path


class CostLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(self, *, stage: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stage": stage,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def _entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def total(self) -> dict:
        entries = self._entries()
        return {
            "entries": len(entries),
            "tokens_in": sum(e["tokens_in"] for e in entries),
            "tokens_out": sum(e["tokens_out"] for e in entries),
            "cost_usd": sum(e["cost_usd"] for e in entries),
        }

    def by_stage(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for e in self._entries():
            s = out.setdefault(e["stage"], {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0})
            s["tokens_in"] += e["tokens_in"]
            s["tokens_out"] += e["tokens_out"]
            s["cost_usd"] += e["cost_usd"]
        return out
