"""Claude judgment tokens, read out of Claude Code's own session transcript."""
import json

from gtm.claudeusage import cumulative_tokens, record_delta, transcript_dir
from gtm.costlog import CostLog


def _write_transcript(directory, name, messages):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jsonl"
    with path.open("w") as f:
        for m in messages:
            f.write(json.dumps(m) + "\n")
    return path


def _response(msg_id, tin=0, cache_write=0, cache_read=0, tout=0):
    return {
        "type": "assistant",
        "uuid": f"u-{msg_id}",
        "message": {
            "id": msg_id,
            "model": "claude-opus-5",
            "usage": {
                "input_tokens": tin,
                "cache_creation_input_tokens": cache_write,
                "cache_read_input_tokens": cache_read,
                "output_tokens": tout,
            },
        },
    }


def test_transcript_dir_slugs_the_project_path(tmp_path):
    d = transcript_dir("/Users/x/GTM Helper")
    assert d.name == "-Users-x-GTM-Helper"


def test_cumulative_tokens_counts_cache_reads_and_writes_as_input(tmp_path):
    _write_transcript(tmp_path, "s1", [_response("m1", tin=2, cache_write=100, cache_read=50, tout=7)])
    assert cumulative_tokens(tmp_path) == (152, 7)


def test_cumulative_tokens_dedupes_one_response_written_as_several_lines(tmp_path):
    # Claude Code writes one API response once per content block, each copy
    # repeating the same usage object — session 4663ce38 had 395 usage lines for
    # 157 real responses, so a naive sum overstates ~2.5x.
    repeated = _response("m1", tin=10, tout=4)
    _write_transcript(tmp_path, "s1", [repeated, dict(repeated), dict(repeated)])
    assert cumulative_tokens(tmp_path) == (10, 4)


def test_cumulative_tokens_sums_across_session_files(tmp_path):
    _write_transcript(tmp_path, "s1", [_response("m1", tin=10, tout=1)])
    _write_transcript(tmp_path, "s2", [_response("m2", tin=5, tout=2)])
    assert cumulative_tokens(tmp_path) == (15, 3)


def test_cumulative_tokens_skips_non_response_lines_and_torn_json(tmp_path):
    path = _write_transcript(tmp_path, "s1", [{"type": "user", "message": {"content": "hi"}}])
    with path.open("a") as f:
        f.write('{"message": {"usage": {"output_tok\n')  # a live session mid-flush
    assert cumulative_tokens(tmp_path) == (0, 0)


def test_missing_transcript_dir_is_not_an_error(tmp_path):
    assert cumulative_tokens(tmp_path / "nope") == (0, 0)


def test_first_call_only_sets_the_baseline(tmp_path):
    _write_transcript(tmp_path / "t", "s1", [_response("m1", tin=100, tout=10)])
    log = CostLog(tmp_path / "cost.jsonl")
    assert record_delta(log, tmp_path / "pos.json", directory=tmp_path / "t") == (0, 0)
    assert log._entries() == []


def test_second_call_charges_only_what_was_spent_since(tmp_path):
    transcripts = tmp_path / "t"
    _write_transcript(transcripts, "s1", [_response("m1", tin=100, tout=10)])
    log, pos = CostLog(tmp_path / "cost.jsonl"), tmp_path / "pos.json"
    record_delta(log, pos, directory=transcripts)

    _write_transcript(transcripts, "s2", [_response("m2", tin=40, tout=6)])
    assert record_delta(log, pos, directory=transcripts) == (40, 6)
    entry = log._entries()[0]
    assert entry["provider"] == "claude"
    assert (entry["tokens_in"], entry["tokens_out"]) == (40, 6)
    assert entry["cost_usd"] == 0.0
    assert "claude:40 in / 6 out" in log.summary_line()


def test_no_new_tokens_records_nothing(tmp_path):
    transcripts = tmp_path / "t"
    _write_transcript(transcripts, "s1", [_response("m1", tin=100, tout=10)])
    log, pos = CostLog(tmp_path / "cost.jsonl"), tmp_path / "pos.json"
    record_delta(log, pos, directory=transcripts)
    assert record_delta(log, pos, directory=transcripts) == (0, 0)
    assert log._entries() == []


def test_a_corrupt_position_file_falls_back_to_a_fresh_baseline(tmp_path):
    transcripts = tmp_path / "t"
    _write_transcript(transcripts, "s1", [_response("m1", tin=100, tout=10)])
    pos = tmp_path / "pos.json"
    pos.write_text("{not json")
    log = CostLog(tmp_path / "cost.jsonl")
    assert record_delta(log, pos, directory=transcripts) == (0, 0)
    assert json.loads(pos.read_text())["tokens_in"] == 100
