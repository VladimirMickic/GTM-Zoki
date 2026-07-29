"""S8 — email waterfall: pattern tier → Hunter.io finder → AI hunt, all verified.

Course template (slides 23-26): stack cheap→expensive, later tiers only run on
earlier misses, nothing hits the sheet unvalidated.
"""
import pytest

import gtm.emails as emails_mod
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
        # Only the real address verifies; the catch-all probe does not, so the
        # domain rejects unknown local parts and a pattern hit means something.
        return {"status": "valid", "score": 98} if email == "adam.bry@skydio.com" else {"status": "invalid"}

    def explode_finder(first, last, domain):
        raise AssertionError("finder must not run when a pattern verifies")

    r = waterfall("Adam Bry", "skydio.com", verifier=fake_verifier, finder=explode_finder)
    assert r == EmailResult(email="adam.bry@skydio.com", tier="pattern", status="verified", score=98)
    assert calls[-1] == "adam.bry@skydio.com"  # stopped at first hit after the probe


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


class RaisingProvider:
    """Live failure mode: a provider call times out / errors instead of returning None."""
    def __init__(self, name, exc=None):
        self.name = name; self._exc = exc or TimeoutError("provider timed out")
    def verify(self, email): raise self._exc
    def find(self, first, last, domain): raise self._exc

@pytest.fixture
def error_log(tmp_path, monkeypatch):
    """Keep provider failures out of the real data/errors.log the user reads."""
    log = tmp_path / "errors.log"
    monkeypatch.setattr(emails_mod, "ERROR_LOG", log)
    return log

def test_verify_chain_falls_through_when_provider_raises(error_log):
    # a raising provider must behave like one that returned None: defer, don't kill the chain
    flaky = RaisingProvider("getprospect")
    good = FakeProvider("hunter", verify_map={"jane.doe@x.com": {"status": "valid", "score": 90}})
    r = waterfall("Jane Doe", "x.com", providers=[flaky, good])
    assert r.email == "jane.doe@x.com" and r.tier == "pattern" and r.status == "verified"
    assert "provider timed out" in error_log.read_text()  # deferred, but not silently

def test_find_chain_falls_through_when_provider_raises(error_log):
    flaky = RaisingProvider("getprospect")
    good = FakeProvider("hunter",
                        find_map={("jane", "doe", "x.com"): {"email": "j.d@x.com", "score": 80}},
                        verify_map={"j.d@x.com": {"status": "valid", "score": 80}})
    r = waterfall("Jane Doe", "x.com", providers=[flaky, good])
    assert r.email == "j.d@x.com" and r.tier == "hunter"

def test_waterfall_every_provider_raising_returns_empty_not_exception(error_log):
    flaky = RaisingProvider("getprospect")
    r = waterfall("Jane Doe", "x.com", providers=[flaky, RaisingProvider("hunter")],
                  search=lambda q, num=10: [])
    assert r == EmailResult()


@pytest.fixture(autouse=True)
def _clear_catch_all_cache():
    emails_mod._CATCH_ALL_CACHE.clear()
    yield
    emails_mod._CATCH_ALL_CACHE.clear()


# --- 2026-07-28: run test-batch-1 email defects ---
# 1. "Michael Lees, MSIS, PMP" -> whitespace split -> "PMP" as surname -> mpmp@easyaerial.com
# 2. that address came back "verified" on an accept-all domain, with no catch-all probe
# 3. Red Cat got 0/3: no domain aliases (redcat.red), and the finder chain silently
#    no-opped because no finder API key is configured


def test_parse_person_name_strips_credential_suffixes():
    from gtm.emails import parse_person_name

    assert parse_person_name("Michael Lees, MSIS, PMP") == ("Michael", "Lees")


def test_parse_person_name_strips_parentheticals_and_pronouns():
    from gtm.emails import parse_person_name

    assert parse_person_name("Jane Doe (she/her) 🚀") == ("Jane", "Doe")


def test_parse_person_name_keeps_generational_suffix_out_of_the_surname():
    from gtm.emails import parse_person_name

    assert parse_person_name("John Smith Jr.") == ("John", "Smith")
    assert parse_person_name("John Smith III") == ("John", "Smith")


def test_parse_person_name_keeps_a_multi_word_surname():
    from gtm.emails import parse_person_name

    assert parse_person_name("Ana van der Berg") == ("Ana", "Berg")


def test_parse_person_name_single_token():
    from gtm.emails import parse_person_name

    assert parse_person_name("Cher") == ("Cher", "")


def test_waterfall_never_produces_an_email_from_a_credential_suffix():
    # The exact live bug: mpmp@easyaerial.com
    seen = []

    def fake_verifier(email):
        seen.append(email)
        return {"status": "invalid"}

    waterfall("Michael Lees, MSIS, PMP", "easyaerial.com", verifier=fake_verifier,
              finder=lambda f, l, d: {}, search=lambda q, num=10: [])
    assert "mpmp@easyaerial.com" not in seen
    assert "michael.lees@easyaerial.com" in seen


def test_is_catch_all_probes_a_nonexistent_local_part_and_caches():
    from gtm.emails import is_catch_all

    calls = []

    def fake_verifier(email):
        calls.append(email)
        return {"status": "valid"}

    assert is_catch_all("easyaerial.com", fake_verifier) is True
    assert is_catch_all("easyaerial.com", fake_verifier) is True  # cached
    assert len(calls) == 1
    assert calls[0].endswith("@easyaerial.com")


def test_is_catch_all_false_when_the_probe_is_rejected():
    from gtm.emails import is_catch_all

    assert is_catch_all("skydio.com", lambda e: {"status": "invalid"}) is False


def test_catch_all_domain_demotes_a_pattern_hit_to_risky_and_tries_the_finder_first():
    order = []

    def fake_verifier(email):
        return {"status": "valid", "score": 99}  # accept-all: says yes to everything

    def fake_finder(first, last, domain):
        order.append("finder")
        return {}

    r = waterfall("Michael Lees", "easyaerial.com", verifier=fake_verifier,
                  finder=fake_finder, search=lambda q, num=10: [])
    assert order == ["finder"]  # finder ran before the pattern fallback
    assert r.tier == "pattern"
    assert r.status == "risky"  # never "verified" — the probe proved verification is meaningless
    assert r.email == "michael.lees@easyaerial.com"


def test_candidate_domains_pulls_a_press_alias_out_of_key_news():
    from gtm.emails import candidate_domains

    news = [
        "Red Cat unveils Black Widow — coverage (https://www.defensenews.com/x)",
        "Red Cat press release — (https://news.redcat.red/pr/12)",
    ]
    domains = candidate_domains("https://redcatholdings.com", "Red Cat Holdings", news)
    assert domains[0] == "redcatholdings.com"
    assert "redcat.red" in domains
    assert "defensenews.com" not in domains  # a publisher is not the prospect's domain


def test_candidate_domains_dedupes_and_caps():
    from gtm.emails import MAX_DOMAINS, candidate_domains

    news = [f"Skydio item (https://skydio{i}.com/x)" for i in range(6)]
    domains = candidate_domains("https://skydio.com", "Skydio", news)
    assert domains[0] == "skydio.com"
    assert len(domains) <= MAX_DOMAINS
    assert len(set(domains)) == len(domains)


def test_waterfall_walks_alias_domains_in_the_pattern_tier():
    def fake_verifier(email):
        return {"status": "valid"} if email == "jane.doe@redcat.red" else {"status": "invalid"}

    r = waterfall("Jane Doe", "redcatholdings.com", domains=["redcatholdings.com", "redcat.red"],
                  verifier=fake_verifier, finder=lambda f, l, d: {}, search=lambda q, num=10: [])
    assert r.email == "jane.doe@redcat.red"
    assert r.status == "verified"


def test_total_miss_reports_no_finder_key_when_no_finder_is_configured(monkeypatch):
    import gtm.email_providers as providers_mod

    for var in providers_mod.FINDER_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(emails_mod, "_verify_chain", lambda providers, email: {"status": "invalid"})

    r = waterfall("Jane Doe", "x.com", search=lambda q, num=10: [])
    assert r.email == ""
    assert r.status == "no-finder-key"  # a config gap, not a genuine miss


def test_total_miss_stays_a_plain_miss_when_a_finder_key_exists(monkeypatch):
    import gtm.email_providers as providers_mod

    monkeypatch.setenv(providers_mod.FINDER_KEY_VARS[0], "test-key")
    monkeypatch.setattr(emails_mod, "_verify_chain", lambda providers, email: {"status": "invalid"})
    monkeypatch.setattr(emails_mod, "_find_chain", lambda providers, f, l, d: {})

    r = waterfall("Jane Doe", "x.com", search=lambda q, num=10: [])
    assert r == EmailResult()
