"""S4 — contacts: LinkedIn SERP parsing + ranking (no email, per plan)."""
import gtm.contacts as contacts
from gtm.contacts import Contact, build_contact_query, find_contacts, parse_linkedin_result
from gtm.costlog import CostLog


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"organic": [{"title": "x", "link": "y"}]}


def test_serper_search_records_one_credit(tmp_path, monkeypatch):
    # every serper call routes through serper_search — logging 1 credit here
    # captures all serper spend (discover/enrich/contacts/spechunt/emails).
    monkeypatch.setattr(contacts.requests, "post", lambda *a, **k: _FakeResp())
    monkeypatch.setenv("SERPER_API_KEY", "test")
    log = CostLog(tmp_path / "cost.jsonl")
    contacts.serper_search("q", costlog=log)
    assert log.by_provider()["serper"]["credits"] == 1


def test_serper_search_uses_ambient_costlog(tmp_path, monkeypatch):
    monkeypatch.setattr(contacts.requests, "post", lambda *a, **k: _FakeResp())
    monkeypatch.setenv("SERPER_API_KEY", "test")
    log = CostLog(tmp_path / "cost.jsonl")
    contacts.set_active_costlog(log)
    try:
        contacts.serper_search("q")  # no explicit costlog — ambient picks it up
    finally:
        contacts.set_active_costlog(None)
    assert log.by_provider()["serper"]["credits"] == 1

FIXTURE_RESULTS = [
    {"title": "George Matus - Founder & CTO - Teal Drones | LinkedIn", "link": "https://www.linkedin.com/in/georgematus"},
    {"title": "Jane Smith – VP of Operations – Teal Drones | LinkedIn", "link": "https://www.linkedin.com/in/janesmith"},
    {"title": "Teal Drones | LinkedIn", "link": "https://www.linkedin.com/company/teal-drones"},
    {"title": "Bob Intern - Marketing Intern - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/bobintern"},
]


def test_parse_hyphen_and_endash_variants():
    c = parse_linkedin_result(FIXTURE_RESULTS[0]["title"], FIXTURE_RESULTS[0]["link"])
    assert c == Contact(name="George Matus", title="Founder & CTO", linkedin="https://www.linkedin.com/in/georgematus")
    c2 = parse_linkedin_result(FIXTURE_RESULTS[1]["title"], FIXTURE_RESULTS[1]["link"])
    assert c2.name == "Jane Smith"
    assert c2.title == "VP of Operations"


def test_company_pages_skipped():
    assert parse_linkedin_result(FIXTURE_RESULTS[2]["title"], FIXTURE_RESULTS[2]["link"]) is None


def test_query_targets_linkedin_profiles():
    q = build_contact_query("Teal Drones")
    assert "site:linkedin.com/in" in q
    assert '"Teal Drones"' in q


def test_find_contacts_ranks_decision_makers_first():
    contacts = find_contacts("Teal Drones", search=lambda q, num=10: FIXTURE_RESULTS)
    assert contacts[0].name == "George Matus"  # founder outranks intern
    assert all(c.linkedin.startswith("http") for c in contacts)
    assert contacts[-1].title == "Marketing Intern"


def test_find_contacts_empty_serp():
    assert find_contacts("Ghost Co", search=lambda q, num=10: []) == []


def test_rank_uses_word_boundaries_not_substrings():
    # "Production Manager" must not match the "product" keyword (substring of "production")
    serp = [
        {"title": "Dave Derry - Production Manager - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/dd"},
        {"title": "Charles Hirsch - Senior Product Manager - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/ch"},
    ]
    contacts = find_contacts("Teal Drones", search=lambda q, num=10: serp)
    assert contacts[0].name == "Charles Hirsch"  # "product" (65) beats bare "manager" (40)


def test_company_suffix_stripped_from_title():
    serp = [
        {"title": "Dave Derry - Production Manager at Teal Drones | LinkedIn", "link": "https://linkedin.com/in/dd"},
        {"title": "Charles Hirsch - Senior Product Manager @ Teal Drones | LinkedIn", "link": "https://linkedin.com/in/ch"},
    ]
    contacts = find_contacts("Teal Drones", search=lambda q, num=10: serp)
    titles = {c.name: c.title for c in contacts}
    assert titles["Dave Derry"] == "Production Manager"
    assert titles["Charles Hirsch"] == "Senior Product Manager"


def test_top_contact_fields_joins_top_three_in_rank_order():
    from gtm.contacts import Contact, top_contact_fields

    contacts = [  # already rank-sorted, as find_contacts returns
        Contact(name="Bob Lee", title="CEO", linkedin="https://li.com/in/bob"),
        Contact(name="Jane Smith", title="VP Operations", linkedin="https://li.com/in/jane"),
        Contact(name="Dave Derry", title="Production Manager", linkedin="https://li.com/in/dave"),
        Contact(name="Ann Extra", title="Engineer", linkedin="https://li.com/in/ann"),
    ]
    names, titles, links = top_contact_fields(contacts)
    assert names == "Bob Lee; Jane Smith; Dave Derry"          # 4th dropped
    assert titles == "CEO; VP Operations; Production Manager"  # parallel order
    assert links == "https://li.com/in/bob; https://li.com/in/jane; https://li.com/in/dave"


def test_top_contact_fields_handles_fewer_than_three_and_empty():
    from gtm.contacts import Contact, top_contact_fields

    one = [Contact(name="Solo Person", title="Founder", linkedin="https://li.com/in/solo")]
    assert top_contact_fields(one) == ("Solo Person", "Founder", "https://li.com/in/solo")
    assert top_contact_fields([]) == ("", "", "")


def test_contact_query_disambiguates_generic_company_names():
    # discover-3 2026-07-18: "Paladin" matched people SURNAMED Paladin
    q = build_contact_query("Paladin")
    assert 'site:linkedin.com/in "Paladin"' in q
    assert "drone" in q.lower()
