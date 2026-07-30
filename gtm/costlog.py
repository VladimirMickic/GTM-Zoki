"""Append-only per-stage cost/token log (jsonl), LeadGrow status-style."""
from __future__ import annotations

import json
import time
from pathlib import Path


def _fmt_tokens(n: int) -> str:
    """Token counts run to seven digits — a raw integer is unreadable in a one-liner."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


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

    def record_vendor(self, *, provider: str, stage: str, credits: int = 1) -> None:
        """One paid third-party call that spends a credit, not dollars — every email
        finder/verifier vendor (docs/tools/<vendor>.md). Free tiers meter per call, so
        the honest unit is calls attempted: a request that misses still burned the
        credit. Before this existed the email waterfall was the one stage whose spend
        never appeared in a run's cost line at all."""
        self.record(
            stage=stage, model=provider, tokens_in=0, tokens_out=0,
            cost_usd=0.0, provider=provider, credits=credits,
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
        """Spend bucketed by provider — openai in dollars, serper and the email
        vendors in credits, claude in tokens. Entries written before the
        provider/credits fields existed default to openai/0 credits."""
        out: dict[str, dict] = {}
        for e in self._entries():
            prov = e.get("provider", "openai")
            b = out.setdefault(
                prov, {"cost_usd": 0.0, "credits": 0, "calls": 0, "tokens_in": 0, "tokens_out": 0}
            )
            b["cost_usd"] += e.get("cost_usd", 0.0)
            b["credits"] += e.get("credits", 0)
            b["tokens_in"] += e.get("tokens_in", 0)
            b["tokens_out"] += e.get("tokens_out", 0)
            b["calls"] += 1
        return out

    def summary_line(self) -> str:
        """One-line per-run spend, e.g.
        'claude:1.2M in / 18.4k out · hunter:4 credits · openai:$0.0412 · serper:15 credits'.

        A provider is reported in whichever unit it actually bills: dollars where we
        know them, credits for metered free tiers, tokens for Claude — Claude Code
        bills a subscription, not this run, so a dollar figure there would be invented.
        """
        parts = []
        for prov, b in sorted(self.by_provider().items()):
            bits = []
            if b["cost_usd"]:
                bits.append(f"${b['cost_usd']:.4f}")
            if b["credits"]:
                bits.append(f"{b['credits']} credits")
            # Tokens only speak for a provider that bills in nothing else — otherwise
            # openai would report its dollars AND its tokens for the same spend.
            if not bits and (b["tokens_in"] or b["tokens_out"]):
                bits.append(f"{_fmt_tokens(b['tokens_in'])} in / {_fmt_tokens(b['tokens_out'])} out")
            parts.append(f"{prov}:{' '.join(bits) or '—'}")
        return " · ".join(parts) if parts else "no spend recorded"
