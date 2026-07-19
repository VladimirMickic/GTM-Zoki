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

from gtm.smoke import run_smoke

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
