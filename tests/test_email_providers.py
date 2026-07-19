from gtm.email_providers import (
    AbstractProvider,
    HunterProvider,
    MyEmailVerifierProvider,
    ProspeoProvider,
)

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

def test_prospeo_find_normalizes(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "error": False,
                "free_enrichment": False,
                "person": {
                    "email": {
                        "status": "VERIFIED",
                        "revealed": True,
                        "email": "j@x.com",
                        "verification_method": "smtp",
                    }
                },
            }
    monkeypatch.setattr("gtm.email_providers.requests.post", lambda *a, **k: R())
    monkeypatch.setenv("PROSPEO_API_KEY", "x")
    assert ProspeoProvider().find("Jane", "Doe", "x.com") == {"email": "j@x.com", "score": 100}

def test_prospeo_find_none_on_miss(monkeypatch):
    class R:
        status_code = 400
        def raise_for_status(self): raise AssertionError("should not raise")
        def json(self): return {"error": True, "error_code": "NO_MATCH"}
    monkeypatch.setattr("gtm.email_providers.requests.post", lambda *a, **k: R())
    monkeypatch.setenv("PROSPEO_API_KEY", "x")
    assert ProspeoProvider().find("Jane", "Doe", "x.com") is None

def test_prospeo_find_none_on_quota(monkeypatch):
    class R:
        status_code = 429
        def raise_for_status(self): raise AssertionError("should not raise")
        def json(self): return {"error": True, "error_code": "INSUFFICIENT_CREDITS"}
    monkeypatch.setattr("gtm.email_providers.requests.post", lambda *a, **k: R())
    monkeypatch.setenv("PROSPEO_API_KEY", "x")
    assert ProspeoProvider().find("Jane", "Doe", "x.com") is None

def test_prospeo_verify_always_none(monkeypatch):
    monkeypatch.setenv("PROSPEO_API_KEY", "x")
    assert ProspeoProvider().verify("a@b.com") is None
