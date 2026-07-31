"""Postmortem — mine a run's own slice of data/errors.log (recovered via its
costs.jsonl time window, since errors.log has no run field of its own) and record
factual failure patterns as Feedback(origin="run"). Never an LLM call, never an
ICP/denylist edit — see gtm/learn.py for why only origin="user" may drive those.
2026-07-30: built after a live run caught two dead guessed domains (pdw.aero,
firestormlabs.io) and a near-miss "[undated]" marker that only a scratch handoff doc
remembered past session end."""
import json
from datetime import datetime

import gtm.postmortem as postmortem
from gtm.learn import load_feedback
from gtm.postmortem import (
    already_recorded,
    classify,
    errors_in_window,
    parse_errors,
    run_postmortem,
)


def test_parse_errors_reads_every_module_s_log_format(tmp_path):
    log = tmp_path / "errors.log"
    log.write_text(
        "2026-07-30T17:29:58 Edgeautonomy [scrape/extract] extracted company 'Redwire' doesn't match\n"
        "2026-07-30T17:53:56 emails [GetProspectProvider/verify] timeout\n"
        "not a valid line, skipped\n"
    )
    parsed = parse_errors(log)
    assert len(parsed) == 2
    assert parsed[0] == {
        "ts": "2026-07-30T17:29:58", "company": "Edgeautonomy", "stage": "scrape/extract",
        "message": "extracted company 'Redwire' doesn't match",
    }
    assert parsed[1]["company"] == "emails"
    assert parsed[1]["stage"] == "GetProspectProvider/verify"


def test_parse_errors_missing_file_returns_empty(tmp_path):
    assert parse_errors(tmp_path / "nope.log") == []


def test_errors_in_window_keeps_only_entries_inside_the_buffered_window():
    errors = [
        {"ts": "2026-07-30T10:00:00", "company": "A", "stage": "s", "message": "too early"},
        {"ts": "2026-07-30T17:33:00", "company": "B", "stage": "s", "message": "in buffer"},
        {"ts": "2026-07-30T17:15:00", "company": "C", "stage": "s", "message": "inside window"},
        {"ts": "2026-07-30T20:00:00", "company": "D", "stage": "s", "message": "too late"},
    ]
    window = (datetime(2026, 7, 30, 17, 0, 0), datetime(2026, 7, 30, 17, 30, 0))
    kept = errors_in_window(errors, window)
    assert [e["company"] for e in kept] == ["B", "C"]  # original order preserved


def test_classify_groups_by_stage_and_counts():
    errors = [
        {"ts": "t1", "company": "A", "stage": "preflight", "message": "dead domain"},
        {"ts": "t2", "company": "B", "stage": "preflight", "message": "dead domain"},
        {"ts": "t3", "company": "emails", "stage": "GetProspectProvider/verify", "message": "timeout"},
    ]
    lines = classify(errors)
    assert len(lines) == 2
    assert lines[0].startswith("1x [GetProspectProvider/verify]")  # sorted by stage name
    assert lines[1].startswith("2x [preflight] dead domain — hit: A, B")


def test_classify_caps_the_companies_listed_and_notes_the_rest():
    errors = [
        {"ts": f"t{i}", "company": f"C{i}", "stage": "preflight", "message": "dead domain"}
        for i in range(5)
    ]
    line = classify(errors)[0]
    assert "hit: C0, C1, C2 (+2 more)" in line


def test_classify_truncates_a_long_example_message():
    long_msg = "x " * 200
    line = classify([{"ts": "t", "company": "A", "stage": "s", "message": long_msg}])[0]
    assert len(line) < len(long_msg)
    assert "..." in line
    assert line.endswith("hit: A")


def test_already_recorded_is_false_for_a_fresh_run(tmp_path):
    assert already_recorded("r1", feedback_path=tmp_path / "feedback.jsonl") is False


def test_already_recorded_is_true_once_a_run_origin_entry_exists(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text(json.dumps({"date": "2026-07-30", "run": "r1", "company": "-", "feedback": "f", "origin": "run"}) + "\n")
    assert already_recorded("r1", feedback_path=path) is True


def test_already_recorded_ignores_other_runs_and_other_origins(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text(
        json.dumps({"date": "2026-07-30", "run": "r2", "company": "-", "feedback": "f", "origin": "run"}) + "\n"
        + json.dumps({"date": "2026-07-30", "run": "r1", "company": "X", "feedback": "f", "origin": "user"}) + "\n"
    )
    assert already_recorded("r1", feedback_path=path) is False


def _write_cost_ts(path, *timestamps):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for ts in timestamps:
            f.write(json.dumps({
                "ts": ts, "stage": "extract", "model": "m", "provider": "openai",
                "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0, "credits": 0,
            }) + "\n")


def test_run_postmortem_records_one_entry_per_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(postmortem, "run_dir", lambda run: tmp_path / "runs" / run)
    _write_cost_ts(tmp_path / "runs" / "r1" / "costs.jsonl", "2026-07-30T17:00:00", "2026-07-30T17:30:00")
    error_log = tmp_path / "errors.log"
    error_log.write_text(
        "2026-07-30T16:59:00 PDW [preflight] pdw.aero does not resolve\n"      # inside 5-min buffer
        "2026-07-30T17:10:00 Firestorm [preflight] firestormlabs.io does not resolve\n"
        "2026-07-30T09:00:00 Unrelated [preflight] from a different run entirely\n"  # outside window
    )
    feedback_path = tmp_path / "feedback.jsonl"

    n = run_postmortem("r1", feedback_path=feedback_path, error_log=error_log)

    assert n == 1  # one distinct stage: "preflight"
    entries = load_feedback(feedback_path)
    assert len(entries) == 1
    assert entries[0].origin == "run"
    assert entries[0].run == "r1"
    assert "PDW" in entries[0].feedback and "Firestorm" in entries[0].feedback
    assert "Unrelated" not in entries[0].feedback


def test_run_postmortem_is_a_no_op_on_a_clean_run(tmp_path, monkeypatch):
    monkeypatch.setattr(postmortem, "run_dir", lambda run: tmp_path / "runs" / run)
    _write_cost_ts(tmp_path / "runs" / "r1" / "costs.jsonl", "2026-07-30T17:00:00")
    n = run_postmortem("r1", feedback_path=tmp_path / "feedback.jsonl", error_log=tmp_path / "errors.log")
    assert n == 0


def test_run_postmortem_is_a_no_op_when_the_run_never_recorded_a_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(postmortem, "run_dir", lambda run: tmp_path / "runs" / run)
    n = run_postmortem("r1", feedback_path=tmp_path / "feedback.jsonl", error_log=tmp_path / "errors.log")
    assert n == 0


def test_run_postmortem_does_not_duplicate_on_a_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr(postmortem, "run_dir", lambda run: tmp_path / "runs" / run)
    _write_cost_ts(tmp_path / "runs" / "r1" / "costs.jsonl", "2026-07-30T17:00:00")
    error_log = tmp_path / "errors.log"
    error_log.write_text("2026-07-30T17:00:01 A [preflight] dead domain\n")
    feedback_path = tmp_path / "feedback.jsonl"

    first = run_postmortem("r1", feedback_path=feedback_path, error_log=error_log)
    second = run_postmortem("r1", feedback_path=feedback_path, error_log=error_log)

    assert first == 1
    assert second == 0
    assert len(load_feedback(feedback_path)) == 1
