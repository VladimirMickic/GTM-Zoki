"""Learn stage — data/feedback.jsonl split into user-sourced (may drive an
ICP/denylist edit proposal) vs Claude's own session/smoke-test notes (context
only). 2026-07-30, user: "Only if user provides feedback you record it"."""
import json

from gtm.learn import build_lessons, eligible_for_proposal, load_feedback, record_feedback, write_lessons
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


# 2026-07-30: bugs caught by eye mid-session (a near-miss "[undated]" marker, two dead
# guessed domains) lived only in scratch handoff docs and vanished at session end.
# build_lessons/write_lessons give `gtm.run start` a small, printed reminder of
# origin="user"/"run" facts — never an ICP/denylist edit, that stays user-only.


def test_build_lessons_includes_user_and_run_entries():
    entries = [
        Feedback(date="2026-07-30", run="r1", company="X", feedback="user said this", origin="user"),
        Feedback(date="2026-07-30", run="r1", company="-", feedback="2x [preflight] dead domain", origin="run"),
    ]
    text = build_lessons(entries)
    assert "user said this" in text
    assert "[preflight] dead domain" in text


def test_build_lessons_excludes_session_entries():
    entries = [Feedback(date="2026-07-30", run="r1", company="-", feedback="long dev-log note", origin="session")]
    text = build_lessons(entries)
    assert "long dev-log note" not in text
    assert "(none yet)" in text


def test_build_lessons_caps_at_twenty_lines_most_recent_first():
    entries = [
        Feedback(date="2026-07-01", run="r1", company="-", feedback=f"lesson {i}", origin="user")
        for i in range(30)
    ]
    text = build_lessons(entries)
    body_lines = [l for l in text.splitlines() if l.startswith("- ")]
    assert len(body_lines) == 20
    assert "lesson 29" in body_lines[0]   # most recent first
    assert "lesson 10" in body_lines[-1]  # oldest of the kept 20


def test_build_lessons_truncates_a_long_feedback_line():
    long_text = "x " * 200
    entries = [Feedback(date="2026-07-30", run="r1", company="-", feedback=long_text, origin="run")]
    line = [l for l in build_lessons(entries).splitlines() if l.startswith("- ")][0]
    assert len(line) <= 200


def test_write_lessons_writes_the_file_and_returns_its_path(tmp_path):
    path = tmp_path / "lessons.md"
    entries = [Feedback(date="2026-07-30", run="r1", company="X", feedback="a lesson", origin="user")]
    returned = write_lessons(entries, path)
    assert returned == path
    assert "a lesson" in path.read_text()
