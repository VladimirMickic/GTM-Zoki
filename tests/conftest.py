import gtm.emails as emails_mod
import gtm.github_state as github_state_mod
import gtm.hubspot as hubspot_mod
import gtm.run as run_mod
import pytest

# error_log: Path = ERROR_LOG defaults are keyword-only, so Python stores them in
# the function's __kwdefaults__ dict — the SAME dict object regardless of whether
# a caller does `module.fn(...)` or `from module import fn` (test_run.py does the
# latter for process_company, which a module-attribute monkeypatch never reaches).
# Mutating __kwdefaults__ in place, via monkeypatch.setitem, hits every caller and
# auto-restores after the test.
_DEFAULT_ERROR_LOG_FNS = [
    (github_state_mod.open_run_issue, "error_log"),
    (github_state_mod.set_stage_labels, "error_log"),
    (github_state_mod.post_checkpoint_comment, "error_log"),
    (run_mod.process_company, "error_log"),
    (hubspot_mod.push_to_hubspot, "error_log"),
]


@pytest.fixture(autouse=True)
def _isolate_error_log(tmp_path, monkeypatch):
    """No test should ever append to the real data/errors.log — that file is for
    real pipeline runs, not test noise."""
    log = tmp_path / "errors.log"
    for mod in (emails_mod, github_state_mod, hubspot_mod, run_mod):
        monkeypatch.setattr(mod, "ERROR_LOG", log)
    for fn, param in _DEFAULT_ERROR_LOG_FNS:
        monkeypatch.setitem(fn.__kwdefaults__, param, log)
