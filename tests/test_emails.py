"""S8 — email waterfall: pattern tier → Hunter.io finder → AI hunt, all verified.

Course template (slides 23-26): stack cheap→expensive, later tiers only run on
earlier misses, nothing hits the sheet unvalidated.
"""
from gtm.emails import (
    EmailResult,
    candidate_patterns,
    split_contact_names,
    verdict,
    waterfall,
)


def test_candidate_patterns_common_shapes_capped_at_three():
    assert candidate_patterns("Adam", "Bry", "skydio.com") == [
        "adam.bry@skydio.com",
        "adam@skydio.com",
        "abry@skydio.com",
    ]


def test_candidate_patterns_single_name_token():
    assert candidate_patterns("Cher", "", "x.com") == ["cher@x.com"]


def test_verdict_maps_hunter_statuses_to_our_labels():
    assert verdict("valid") == "verified"
    assert verdict("accept_all") == "risky"
    assert verdict("webmail") == "risky"
    assert verdict("unknown") == "unverified"
    assert verdict("invalid") == "reject"
    assert verdict("disposable") == "reject"


def test_waterfall_tier1_pattern_hit_short_circuits():
    calls = []

    def fake_verifier(email):
        calls.append(email)
        return {"status": "valid", "score": 98}

    def explode_finder(first, last, domain):
        raise AssertionError("finder must not run when a pattern verifies")

    r = waterfall("Adam Bry", "skydio.com", verifier=fake_verifier, finder=explode_finder)
    assert r == EmailResult(email="adam.bry@skydio.com", tier="pattern", status="verified", score=98)
    assert calls == ["adam.bry@skydio.com"]  # stopped at first hit


def test_waterfall_tier2_hunter_on_pattern_misses():
    def fake_verifier(email):
        if email == "found@brincdrones.com":
            return {"status": "accept_all", "score": 60}
        return {"status": "invalid", "score": 0}

    def fake_finder(first, last, domain):
        assert (first, last, domain) == ("Blake", "Resnick", "brincdrones.com")
        return {"email": "found@brincdrones.com", "score": 91}

    r = waterfall("Blake Resnick", "brincdrones.com", verifier=fake_verifier, finder=fake_finder)
    assert r.tier == "hunter"
    assert r.email == "found@brincdrones.com"
    assert r.status == "risky"  # accept_all is never "verified" (docs/tools/hunter.md)


def test_waterfall_tier3_ai_hunt_scans_serps_for_domain_emails():
    serp = [
        {"title": "team page", "snippet": "contact maxwell.wang@paladindrones.io for demos"},
        {"title": "junk", "snippet": "someone@gmail.com"},  # wrong domain — ignored
    ]
    r = waterfall(
        "Maxwell Wang", "paladindrones.io",
        verifier=lambda e: {"status": "unknown", "score": 40} if "maxwell" in e else {"status": "invalid", "score": 0},
        finder=lambda f, l, d: {"email": None, "score": 0},
        search=lambda q, num=10: serp,
    )
    assert r.tier == "ai"
    assert r.email == "maxwell.wang@paladindrones.io"
    assert r.status == "unverified"


def test_waterfall_total_miss_returns_empty_result():
    r = waterfall(
        "Ghost Person", "ghost.com",
        verifier=lambda e: {"status": "invalid", "score": 0},
        finder=lambda f, l, d: {"email": None, "score": 0},
        search=lambda q, num=10: [],
    )
    assert r == EmailResult()


def test_split_contact_names_parallel_join_roundtrip():
    assert split_contact_names("Blake Resnick; Manoj Mohan; Steven Butler") == [
        "Blake Resnick", "Manoj Mohan", "Steven Butler",
    ]
    assert split_contact_names("") == []


class FakeProvider:
    def __init__(self, name, verify_map=None, find_map=None):
        self.name = name; self._v = verify_map or {}; self._f = find_map or {}
    def verify(self, email): return self._v.get(email)
    def find(self, first, last, domain): return self._f.get((first, last, domain))

def test_waterfall_second_verifier_when_first_quota():
    p1 = FakeProvider("mev")  # returns None => quota/skip
    p2 = FakeProvider("hunter", verify_map={"jane.doe@x.com": {"status": "valid", "score": 90}})
    r = waterfall("Jane Doe", "x.com", providers=[p1, p2])
    assert r.email == "jane.doe@x.com" and r.tier == "pattern" and r.status == "verified"

def test_waterfall_find_chain_when_patterns_miss():
    p1 = FakeProvider("mev")
    p2 = FakeProvider("hunter",
                      find_map={("jane", "doe", "x.com"): {"email": "j.d@x.com", "score": 80}},
                      verify_map={"j.d@x.com": {"status": "valid", "score": 80}})
    r = waterfall("Jane Doe", "x.com", providers=[p1, p2])
    assert r.email == "j.d@x.com" and r.tier == "hunter"
