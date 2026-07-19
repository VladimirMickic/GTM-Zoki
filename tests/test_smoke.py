from gtm.extract import DroneExtraction
from gtm.fit import FitResult
from gtm.smoke import auto_fit

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
