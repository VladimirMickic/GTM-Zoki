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
