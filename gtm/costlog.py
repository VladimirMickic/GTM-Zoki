"""Append-only per-stage cost/token log (jsonl), LeadGrow status-style."""
from __future__ import annotations

import json
import time
from pathlib import Path


class CostLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(
        self,
        *,
        stage: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        provider: str = "openai",
        credits: int = 0,
    ) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stage": stage,
            "model": model,
            "provider": provider,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "credits": credits,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def record_serper(self, *, stage: str = "serper", credits: int = 1) -> None:
        """Serper spends credits, not dollars (1 per search on the free tier)."""
        self.record(
            stage=stage, model="serper", tokens_in=0, tokens_out=0,
            cost_usd=0.0, provider="serper", credits=credits,
        )

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

    def by_provider(self) -> dict[str, dict]:
        """Spend bucketed by provider — openai in dollars, serper in credits.
        Entries written before the provider/credits fields existed default to
        openai/0 credits."""
        out: dict[str, dict] = {}
        for e in self._entries():
            prov = e.get("provider", "openai")
            b = out.setdefault(prov, {"cost_usd": 0.0, "credits": 0, "calls": 0})
            b["cost_usd"] += e.get("cost_usd", 0.0)
            b["credits"] += e.get("credits", 0)
            b["calls"] += 1
        return out

    def summary_line(self) -> str:
        """One-line per-run spend, e.g. 'openai:$0.0412 · serper:15 credits'."""
        parts = []
        for prov, b in sorted(self.by_provider().items()):
            bits = []
            if b["cost_usd"]:
                bits.append(f"${b['cost_usd']:.4f}")
            if b["credits"]:
                bits.append(f"{b['credits']} credits")
            parts.append(f"{prov}:{' '.join(bits) or '—'}")
        return " · ".join(parts) if parts else "no spend recorded"
