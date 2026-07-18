"""S0: cost/token log — per-stage spend, LeadGrow status-style."""
from gtm.costlog import CostLog


def test_records_and_totals(tmp_path):
    log = CostLog(tmp_path / "cost.jsonl")
    log.record(stage="extract", model="gpt-4o-mini", tokens_in=1200, tokens_out=300, cost_usd=0.0011)
    log.record(stage="extract", model="gpt-4o-mini", tokens_in=800, tokens_out=200, cost_usd=0.0007)
    t = log.total()
    assert t["tokens_in"] == 2000
    assert t["tokens_out"] == 500
    assert round(t["cost_usd"], 4) == 0.0018


def test_survives_reload(tmp_path):
    path = tmp_path / "cost.jsonl"
    CostLog(path).record(stage="scrape", model="-", tokens_in=0, tokens_out=0, cost_usd=0.0)
    log2 = CostLog(path)
    log2.record(stage="fit", model="claude", tokens_in=100, tokens_out=50, cost_usd=0.001)
    assert log2.total()["entries"] == 2


def test_per_stage_breakdown(tmp_path):
    log = CostLog(tmp_path / "cost.jsonl")
    log.record(stage="extract", model="gpt-4o-mini", tokens_in=10, tokens_out=5, cost_usd=0.1)
    log.record(stage="fit", model="claude", tokens_in=20, tokens_out=5, cost_usd=0.2)
    by_stage = log.by_stage()
    assert by_stage["extract"]["cost_usd"] == 0.1
    assert by_stage["fit"]["tokens_in"] == 20
