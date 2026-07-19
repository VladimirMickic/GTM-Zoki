"""Task 6.1: gtm/github_state.py — GitHub Issues adapter, mocked requests only.

No real network calls, no real GITHUB_TOKEN needed. Mirrors tests/test_email_providers.py's
monkeypatch-the-requests-call style.
"""
from pathlib import Path

import requests

import gtm.github_state as gh


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


# ---------- open_run_issue ----------


def test_open_run_issue_creates_and_writes_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json, timeout))
        return FakeResponse(201, {"number": 42, "html_url": "https://x"})

    monkeypatch.setattr(gh.requests, "post", fake_post)

    issue = gh.open_run_issue("teal-demo", tmp_path)

    assert issue == 42
    assert (tmp_path / ".github_issue").read_text().strip() == "42"
    assert len(calls) == 1
    url, headers, body, timeout = calls[0]
    assert url == "https://api.github.com/repos/VladimirMickic/GTM-Zoki/issues"
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert body["title"] == "GTM run: teal-demo"
    assert set(body["labels"]) == {"run:teal-demo", "stage:input", "status:running"}


def test_open_run_issue_idempotent_reads_sidecar_no_duplicate_create(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    (tmp_path / ".github_issue").write_text("99")

    def fail_post(*a, **k):
        raise AssertionError("should not call requests.post when sidecar exists")

    monkeypatch.setattr(gh.requests, "post", fail_post)

    issue = gh.open_run_issue("teal-demo", tmp_path)

    assert issue == 99


def test_open_run_issue_logs_and_skips_on_network_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")

    def raise_conn_error(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(gh.requests, "post", raise_conn_error)
    error_log = tmp_path / "errors.log"

    issue = gh.open_run_issue("teal-demo", tmp_path, error_log=error_log)

    assert issue is None
    assert not (tmp_path / ".github_issue").exists()
    assert error_log.exists()
    assert "boom" in error_log.read_text()


def test_open_run_issue_logs_and_skips_on_non_201(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr(gh.requests, "post", lambda *a, **k: FakeResponse(422, text="bad request"))
    error_log = tmp_path / "errors.log"

    issue = gh.open_run_issue("teal-demo", tmp_path, error_log=error_log)

    assert issue is None
    assert not (tmp_path / ".github_issue").exists()
    assert error_log.exists()


def test_open_run_issue_missing_token_logs_and_skips(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def fail_post(*a, **k):
        raise AssertionError("should not call requests.post without a token")

    monkeypatch.setattr(gh.requests, "post", fail_post)
    error_log = tmp_path / "errors.log"

    issue = gh.open_run_issue("teal-demo", tmp_path, error_log=error_log)

    assert issue is None
    assert error_log.exists()


# ---------- set_stage_labels ----------


def test_set_stage_labels_puts_full_three_label_set(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    calls = []

    def fake_put(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json, timeout))
        return FakeResponse(200, [{"name": n} for n in json["labels"]])

    monkeypatch.setattr(gh.requests, "put", fake_put)

    result = gh.set_stage_labels(42, "teal-demo", "fit", "running")

    assert result == ["run:teal-demo", "stage:fit", "status:running"]
    assert len(calls) == 1
    url, headers, body, timeout = calls[0]
    assert url == "https://api.github.com/repos/VladimirMickic/GTM-Zoki/issues/42/labels"
    assert headers["Authorization"] == "Bearer tok"
    assert body == {"labels": ["run:teal-demo", "stage:fit", "status:running"]}


def test_set_stage_labels_logs_and_skips_on_403(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr(gh.requests, "put", lambda *a, **k: FakeResponse(403, text="rate limited"))
    error_log = tmp_path / "errors.log"

    result = gh.set_stage_labels(42, "teal-demo", "fit", "running", error_log=error_log)

    assert result is None
    assert error_log.exists()
    assert "403" in error_log.read_text()


def test_set_stage_labels_logs_and_skips_on_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")

    def raise_timeout(*a, **k):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(gh.requests, "put", raise_timeout)
    error_log = tmp_path / "errors.log"

    result = gh.set_stage_labels(42, "teal-demo", "fit", "running", error_log=error_log)

    assert result is None
    assert error_log.exists()
    assert "slow" in error_log.read_text()


# ---------- post_checkpoint_comment ----------


def test_post_checkpoint_comment_posts_body(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json, timeout))
        return FakeResponse(201, {"id": 1})

    monkeypatch.setattr(gh.requests, "post", fake_post)

    ok = gh.post_checkpoint_comment(
        42, "fit.json", "score prospects", "python -m gtm.run fit teal-demo fit.json"
    )

    assert ok is True
    assert len(calls) == 1
    url, headers, body, timeout = calls[0]
    assert url == "https://api.github.com/repos/VladimirMickic/GTM-Zoki/issues/42/comments"
    assert "fit.json" in body["body"]
    assert "score prospects" in body["body"]
    assert "python -m gtm.run fit teal-demo fit.json" in body["body"]


def test_post_checkpoint_comment_logs_and_skips_on_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")

    def raise_conn_error(*a, **k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(gh.requests, "post", raise_conn_error)
    error_log = tmp_path / "errors.log"

    ok = gh.post_checkpoint_comment(
        42, "fit.json", "score prospects", "resume cmd", error_log=error_log
    )

    assert ok is False
    assert error_log.exists()
    assert "down" in error_log.read_text()


def test_post_checkpoint_comment_logs_and_skips_on_non_201(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setattr(gh.requests, "post", lambda *a, **k: FakeResponse(404, text="not found"))
    error_log = tmp_path / "errors.log"

    ok = gh.post_checkpoint_comment(
        999, "fit.json", "score prospects", "resume cmd", error_log=error_log
    )

    assert ok is False
    assert error_log.exists()
