"""Learn stage — data/feedback.jsonl split into user-sourced (may drive an
ICP/denylist edit proposal) vs Claude's own session/smoke-test notes (context
only). 2026-07-30, user: "Only if user provides feedback you record it"."""
import json

from gtm.learn import eligible_for_proposal, load_feedback, record_feedback
from gtm.schema import Feedback


def test_load_feedback_missing_file_returns_empty(tmp_path):
    assert load_feedback(tmp_path / "nope.jsonl") == []


def test_load_feedback_parses_entries(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text(
        json.dumps({"date": "2026-07-30", "run": "r1", "company": "X", "feedback": "f1"}) + "\n"
    )
    entries = load_feedback(path)
    assert len(entries) == 1
    assert entries[0].company == "X"


def test_load_feedback_defaults_missing_origin_to_session(tmp_path):
    """Every entry recorded before `origin` existed (checked 2026-07-30: all 20
    were Claude's own live-smoke write-ups) must parse as non-user, not crash
    and not silently count as user feedback."""
    path = tmp_path / "feedback.jsonl"
    path.write_text(
        json.dumps({"date": "2026-07-18", "run": "teal-demo", "company": "Teal Drones",
                     "feedback": "old entry, no origin field"}) + "\n"
    )
    entries = load_feedback(path)
    assert entries[0].origin == "session"
    assert eligible_for_proposal(entries) == []


def test_load_feedback_skips_a_torn_line_rather_than_crashing(tmp_path):
    path = tmp_path / "feedback.jsonl"
    good = json.dumps({"date": "2026-07-30", "run": "r1", "company": "X", "feedback": "f1"})
    path.write_text(good + "\n" + "{not json\n")
    entries = load_feedback(path)
    assert len(entries) == 1


def test_load_feedback_is_bounded_to_the_limit(tmp_path):
    path = tmp_path / "feedback.jsonl"
    lines = [
        json.dumps({"date": "2026-07-30", "run": "r1", "company": f"C{i}", "feedback": "f"})
        for i in range(60)
    ]
    path.write_text("\n".join(lines) + "\n")
    entries = load_feedback(path, limit=50)
    assert len(entries) == 50
    assert entries[-1].company == "C59"  # the tail, not the head, is what's bounded-in


def test_record_feedback_defaults_to_user_origin(tmp_path):
    path = tmp_path / "feedback.jsonl"
    record_feedback(path, date="2026-07-30", run="r1", company="X", feedback="said by the user")
    entries = load_feedback(path)
    assert entries[0].origin == "user"
    assert eligible_for_proposal(entries) == entries


def test_record_feedback_can_record_a_session_note_explicitly(tmp_path):
    path = tmp_path / "feedback.jsonl"
    record_feedback(
        path, date="2026-07-30", run="r1", company="-", feedback="live smoke note",
        origin="session",
    )
    entries = load_feedback(path)
    assert entries[0].origin == "session"
    assert eligible_for_proposal(entries) == []


def test_record_feedback_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "feedback.jsonl"
    record_feedback(path, date="2026-07-30", run="r1", company="X", feedback="f")
    assert path.exists()


def test_record_feedback_appends_without_truncating(tmp_path):
    path = tmp_path / "feedback.jsonl"
    record_feedback(path, date="2026-07-30", run="r1", company="A", feedback="first")
    record_feedback(path, date="2026-07-30", run="r1", company="B", feedback="second")
    entries = load_feedback(path)
    assert [e.company for e in entries] == ["A", "B"]


def test_eligible_for_proposal_filters_out_session_entries():
    entries = [
        Feedback(date="d", run="r", company="A", feedback="f1", origin="user"),
        Feedback(date="d", run="r", company="B", feedback="f2", origin="session"),
        Feedback(date="d", run="r", company="C", feedback="f3", origin="user"),
    ]
    assert [e.company for e in eligible_for_proposal(entries)] == ["A", "C"]
