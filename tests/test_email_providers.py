from gtm.email_providers import HunterProvider

def test_hunter_verify_normalizes(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"data": {"status": "valid", "score": 97}}
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    assert HunterProvider().verify("a@b.com") == {"status": "valid", "score": 97}

def test_hunter_verify_none_on_quota(monkeypatch):
    class R:
        status_code = 429
        def raise_for_status(self): raise AssertionError("should not raise")
        def json(self): return {}
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("HUNTER_API_KEY", "x")
    assert HunterProvider().verify("a@b.com") is None
