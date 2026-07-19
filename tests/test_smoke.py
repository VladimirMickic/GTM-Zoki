from gtm.extract import DroneExtraction
from gtm.fit import FitResult
from gtm.schema import Prospect
from gtm.smoke import auto_fit, auto_signals

class _FakeParse:
    def __init__(self, payload): self._p = payload
    class _Msg:
        def __init__(self, parsed): self.parsed = parsed; self.refusal = None
    def __call__(self, **kw):
        class C:
            class ch:
                message = None
                finish_reason = "stop"
            usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
            choices = [ch]
        C.choices[0].message = _FakeParse._Msg(self._p)
        return C

def test_auto_fit_parses_gpt_result():
    fake = FitResult(fit_score=72, fit_reason="x 12/15 — ok", best_case_line="AV-Field")
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"parse": _FakeParse(fake)})()})()})()
    r = auto_fit("ICP", "Teal", DroneExtraction(company_description="d"), client=client)
    assert r.fit_score == 72 and r.best_case_line == "AV-Field"

def test_auto_signals_parses():
    from gtm.smoke import SignalOut
    fake = SignalOut(buying_signals=["Launch of new variant — market expansion signal (news, 2026)"], outreach_angle="New drone launch is a perfect time to pitch protective cases.")
    client = type("Cl", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"parse": _FakeParse(fake)})()})()})()
    p = Prospect(company="Teal Drones", website="https://tealdrones.com")
    r = auto_signals(p, client=client)
    assert r["buying_signals"] == ["Launch of new variant — market expansion signal (news, 2026)"]
    assert r["outreach_angle"] == "New drone launch is a perfect time to pitch protective cases."

from gtm.run import company_from_url
from gtm.smoke import run_smoke

def test_cli_smoke_dispatches_to_run_smoke(monkeypatch):
    import gtm.run as run_mod

    calls = []
    monkeypatch.setattr("gtm.smoke.run_smoke", lambda url, **kw: calls.append((url, kw.get("live", False))))
    monkeypatch.setattr("sys.argv", ["gtm.run", "smoke", "https://tealdrones.com"])
    run_mod.main()
    assert calls == [("https://tealdrones.com", False)]

def test_cli_smoke_live_flag_dispatches_to_run_smoke(monkeypatch):
    import gtm.run as run_mod

    calls = []
    monkeypatch.setattr("gtm.smoke.run_smoke", lambda url, **kw: calls.append((url, kw.get("live", False))))
    monkeypatch.setattr("sys.argv", ["gtm.run", "smoke", "https://tealdrones.com", "--live"])
    run_mod.main()
    assert calls == [("https://tealdrones.com", True)]

def test_run_smoke_skips_sink_when_not_live(monkeypatch, tmp_path):
    calls = {"push": 0}
    monkeypatch.setattr("gtm.smoke.push_to_sheet", lambda *a, **k: calls.__setitem__("push", calls["push"] + 1))
    # stub every live stage with a fast fake
    monkeypatch.setattr("gtm.smoke.process_company", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.enrich", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.find_contacts", lambda c: [])
    monkeypatch.setattr("gtm.smoke.emails_for_prospect", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.auto_fit", lambda *a, **k: __import__("gtm.fit", fromlist=["FitResult"]).FitResult(fit_score=80, fit_reason="r", best_case_line="AV-Field"))
    monkeypatch.setattr("gtm.smoke.auto_signals", lambda p, **k: {"buying_signals": [], "outreach_angle": "a"})
    monkeypatch.setattr("gtm.smoke.run_dir", lambda run: tmp_path)
    p = run_smoke("https://tealdrones.com", live=False)
    assert p.status == "priority" and calls["push"] == 0  # sink NOT called


def test_run_smoke_freezes_a_brief_lock(monkeypatch, tmp_path):
    from gtm.brief import load_frozen

    monkeypatch.setattr("gtm.smoke.process_company", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.enrich", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.find_contacts", lambda c: [])
    monkeypatch.setattr("gtm.smoke.emails_for_prospect", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.auto_fit", lambda *a, **k: __import__("gtm.fit", fromlist=["FitResult"]).FitResult(fit_score=80, fit_reason="r", best_case_line="AV-Field"))
    monkeypatch.setattr("gtm.smoke.auto_signals", lambda p, **k: {"buying_signals": [], "outreach_angle": "a"})
    monkeypatch.setattr("gtm.smoke.run_dir", lambda run: tmp_path)

    run_smoke("https://tealdrones.com", live=False, run="smoke-test")

    frozen = load_frozen(tmp_path)
    assert frozen.urls == ["https://tealdrones.com"]
    assert frozen.run == "smoke-test"


def test_run_smoke_reruns_same_run_name_with_different_url(monkeypatch, tmp_path):
    """Regression: smoke's run dir is a shared scratch slot reused across ad-hoc
    invocations (like prospects.json already is), not a persistent run to
    tamper-protect. A second smoke call against the same run name but a
    different URL must overwrite the lock, not raise ValueError."""
    monkeypatch.setattr("gtm.smoke.push_to_sheet", lambda *a, **k: None)
    monkeypatch.setattr("gtm.smoke.process_company", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.enrich", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.find_contacts", lambda c: [])
    monkeypatch.setattr("gtm.smoke.emails_for_prospect", lambda p, **k: p)
    monkeypatch.setattr("gtm.smoke.auto_fit", lambda *a, **k: __import__("gtm.fit", fromlist=["FitResult"]).FitResult(fit_score=80, fit_reason="r", best_case_line="AV-Field"))
    monkeypatch.setattr("gtm.smoke.auto_signals", lambda p, **k: {"buying_signals": [], "outreach_angle": "a"})
    monkeypatch.setattr("gtm.smoke.run_dir", lambda run: tmp_path)

    run_smoke("https://tealdrones.com", live=False, run="smoke")
    # Must not raise even though the URL (and therefore the frozen brief
    # content) differs from the first call's lock.
    p2 = run_smoke("https://otherdrones.com", live=False, run="smoke")

    from gtm.brief import load_frozen
    frozen = load_frozen(tmp_path)
    assert frozen.urls == ["https://otherdrones.com"]
    assert p2.company == company_from_url("https://otherdrones.com")
