from gtm.email_providers import AbstractProvider, HunterProvider, MyEmailVerifierProvider

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

def test_myemailverifier_verify_normalizes(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "Address": "a@b.com",
                "Status": "Valid",
                "catch_all": "false",
                "error_code": 0,
            }
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("MYEMAILVERIFIER_API_KEY", "x")
    provider = MyEmailVerifierProvider()
    assert provider.verify("a@b.com") == {"status": "valid", "score": 100}
    assert provider.find("a", "b", "b.com") is None

def test_myemailverifier_verify_none_on_quota(monkeypatch):
    class R:
        status_code = 429
        def raise_for_status(self): raise AssertionError("should not raise")
        def json(self): return {}
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("MYEMAILVERIFIER_API_KEY", "x")
    assert MyEmailVerifierProvider().verify("a@b.com") is None

def test_abstract_verify_normalizes(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "deliverability": "DELIVERABLE",
                "is_catchall_email": {"value": False, "text": "FALSE"},
                "quality_score": 0.87,
            }
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("ABSTRACT_API_KEY", "x")
    provider = AbstractProvider()
    assert provider.verify("a@b.com") == {"status": "valid", "score": 87}
    assert provider.find("a", "b", "b.com") is None

def test_abstract_verify_none_on_quota(monkeypatch):
    class R:
        status_code = 429
        def raise_for_status(self): raise AssertionError("should not raise")
        def json(self): return {}
    monkeypatch.setattr("gtm.email_providers.requests.get", lambda *a, **k: R())
    monkeypatch.setenv("ABSTRACT_API_KEY", "x")
    assert AbstractProvider().verify("a@b.com") is None
