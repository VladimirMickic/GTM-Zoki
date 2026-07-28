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


def test_parse_strips_serper_snippet_truncation_and_trailing_company():
    """Real us-drone-6 output: title shipped to the sheet as
    "Head of Mission Success @ Neros ..." — Serper truncates long SERP titles with an
    ellipsis, which broke the $-anchored "at|@ <company>" strip, so BOTH the company
    and the literal "..." survived into the contact_title cell."""
    c = parse_linkedin_result(
        "Clayton Calk - Head of Mission Success @ Neros ... | LinkedIn",
        "https://www.linkedin.com/in/claytoncalk",
        "Neros",
    )
    assert c.title == "Head of Mission Success"
    # unicode ellipsis is the other form Serper emits
    c2 = parse_linkedin_result(
        "Jane Doe - Director of Supply Chain at Skyfront…",
        "https://www.linkedin.com/in/janedoe",
        "Skyfront",
    )
    assert c2.title == "Director of Supply Chain"


def test_parse_strips_a_company_name_the_serp_itself_truncated():
    """Serper cut "@ Neros Technologies" down to "@ Neros ..." — once the ellipsis is
    gone what's left is a PREFIX of our company name, which an exact-match strip misses.
    This is the actual us-drone-6 row: company is "Neros Technologies", SERP said "Neros"."""
    c = parse_linkedin_result(
        "Clayton Calk - Head of Mission Success @ Neros ... | LinkedIn",
        "https://www.linkedin.com/in/claytoncalk",
        "Neros Technologies",
    )
    assert c.title == "Head of Mission Success"


def test_parse_keeps_a_trailing_at_clause_for_a_different_employer():
    """"at <not our company>" is real information (they work elsewhere) — never strip it."""
    c = parse_linkedin_result(
        "Pat Lee - Supply Chain Manager at Anduril",
        "https://www.linkedin.com/in/patlee",
        "Neros Technologies",
    )
    assert c.title == "Supply Chain Manager at Anduril"


def test_parse_keeps_a_title_that_merely_mentions_another_company():
    """Only a TRAILING "at <our company>" is the SERP's own suffix — a company name
    anywhere else is part of the real title and must survive."""
    c = parse_linkedin_result(
        "Sam Reed - Neros Program Lead for Archer",
        "https://www.linkedin.com/in/samreed",
        "Neros",
    )
    assert c.title == "Neros Program Lead for Archer"


def test_company_pages_skipped():
    assert parse_linkedin_result(FIXTURE_RESULTS[2]["title"], FIXTURE_RESULTS[2]["link"]) is None


def test_query_targets_linkedin_profiles():
    q = build_contact_query("Teal Drones")
    assert "site:linkedin.com/in" in q
    assert '"Teal Drones"' in q


def test_find_contacts_ranks_decision_makers_first():
    contacts = find_contacts("Teal Drones", search=lambda q, num=10: FIXTURE_RESULTS)
    assert contacts[0].name == "George Matus"  # founder outranks the rest
    assert all(c.linkedin.startswith("http") for c in contacts)
    assert all("Intern" not in c.title for c in contacts)  # intern now excluded


def test_query_biases_toward_buyer_titles():
    q = build_contact_query("Teal Drones").lower()
    assert " or " in q  # OR-group of buyer terms
    assert "procurement" in q
    assert "operations" in q


def test_find_contacts_excludes_engineers_and_students():
    # us-drone-3: AeroVironment surfaced Chief Engineer + a Penn State student.
    serp = [
        {"title": "Ed Eng - Chief Engineer - AeroVironment | LinkedIn", "link": "https://linkedin.com/in/ee"},
        {"title": "Stu Dent - AeroVironment Penn State University - | LinkedIn", "link": "https://linkedin.com/in/sd"},
        {"title": "Val Vee - VP of Operations - AeroVironment | LinkedIn", "link": "https://linkedin.com/in/vv"},
    ]
    contacts = find_contacts("AeroVironment", search=lambda q, num=10: serp)
    assert [c.name for c in contacts] == ["Val Vee"]  # engineer + student dropped


def test_procurement_titles_rank_as_buyers():
    serp = [
        {"title": "Pat Purch - Procurement Manager - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/pp"},
        {"title": "Sam Sales - Sales Rep - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/ss"},
    ]
    contacts = find_contacts("Teal Drones", search=lambda q, num=10: serp)
    assert contacts[0].name == "Pat Purch"  # procurement (72) outranks sales (50)


def test_find_contacts_drops_unrecognized_zero_rank_titles():
    serp = [
        {"title": "Vera Voss - VP of Operations - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/vera"},
        {"title": "Ned Null - Barista - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/ned"},
    ]
    contacts = find_contacts("Teal Drones", search=lambda q, num=10: serp)
    assert [c.name for c in contacts] == ["Vera Voss"]  # rank-0 "Barista" dropped


def test_find_contacts_falls_back_to_broad_query_when_buyer_query_empty():
    calls = []

    def fake(q, num=10):
        calls.append(q)
        if " OR " in q:  # buyer-biased query surfaces nobody
            return []
        return [{"title": "Amy Ace - Founder - Ghost Co | LinkedIn", "link": "https://linkedin.com/in/amy"}]

    contacts = find_contacts("Ghost Co", search=fake)
    assert len(calls) == 2  # tried buyer query, then widened to broad
    assert contacts[0].name == "Amy Ace"


def test_find_contacts_empty_serp():
    assert find_contacts("Ghost Co", search=lambda q, num=10: []) == []


def test_find_contacts_excludes_ceo_titles():
    # user: not targeting CEO for outreach — must never surface as a contact.
    serp = [
        {"title": "Alice Ames - CEO - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/alice"},
        {"title": "Jane Smith – VP of Operations – Teal Drones | LinkedIn", "link": "https://linkedin.com/in/jane"},
    ]
    contacts = find_contacts("Teal Drones", search=lambda q, num=10: serp)
    assert all(c.name != "Alice Ames" for c in contacts)
    assert contacts[0].name == "Jane Smith"


def test_find_contacts_returns_empty_when_only_ceo_found():
    serp = [{"title": "Bob Lee - CEO - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/bob"}]
    assert find_contacts("Teal Drones", search=lambda q, num=10: serp) == []


def test_founder_ceo_survives_the_ceo_exclusion():
    """cold-0727 (Arcsky, 2026-07-27): the SERP found both co-founders — "Co-CEO |
    Co-Founder" and "Co-CEO/Co-Founder", each ranking 100, the top band — and the
    CEO exclusion dropped both, leaving the company with zero contacts and a drafted
    email with nobody to send it to. At a founder-led company the founder IS the CEO;
    ICP.md ranks Founder #1 and excludes CEO, and those two rules collide. CEO is
    only disqualifying when no founder term is present."""
    serp = [
        {"title": "Wilson Lau - Co-CEO | Co-Founder at Arcsky | LinkedIn", "link": "https://linkedin.com/in/wl"},
        {"title": "Justin Squire - Co-CEO/Co-Founder at Arcsky | LinkedIn", "link": "https://linkedin.com/in/js"},
    ]
    names = [c.name for c in find_contacts("Arcsky", search=lambda q, num=10: serp)]
    assert names == ["Wilson Lau", "Justin Squire"]


def test_non_founder_ceo_is_still_excluded():
    """The founder carve-out above must not reopen the door to a plain CEO at a
    company big enough to have one who didn't found it."""
    serp = [
        {"title": "Alice Ames - CEO - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/alice"},
        {"title": "Nina Ng - Chief Executive Officer - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/nn"},
    ]
    assert find_contacts("Teal Drones", search=lambda q, num=10: serp) == []


def test_spelled_out_chief_executive_officer_is_excluded():
    """Same cold run surfaced the mirror-image leak: "ceo" is word-boundary matched,
    so "Chief Executive Officer" slipped through the exclusion entirely and ranked 90
    on "chief" — the filter was over-broad on founders and leaky on the one title it
    exists to block."""
    serp = [{"title": "Nina Ng - Chief Executive Officer - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/nn"}]
    assert find_contacts("Teal Drones", search=lambda q, num=10: serp) == []


def test_founder_carve_out_does_not_rescue_other_excluded_titles():
    """The carve-out is scoped to the founder/CEO collision only — a founding
    engineer is still an engineer, and engineers are excluded for their own reason."""
    serp = [{"title": "Ed Ellis - Founding Engineer - Teal Drones | LinkedIn", "link": "https://linkedin.com/in/ee"}]
    assert find_contacts("Teal Drones", search=lambda q, num=10: serp) == []


def test_find_contacts_drops_a_different_current_employer():
    """Live cold-0727 follow-up (2026-07-27): find_contacts("Skyfront") returned
    "Daniel Williams - Co-Founder at oltrashoes" and "Joseph Segura-Conn - Director
    of Sales at Doodle Labs" — real people whose LinkedIn profile happens to mention
    "Skyfront" and "drone" somewhere, but who do not work at Skyfront. Their titles
    say so explicitly: a trailing "at <company>" clause that survives
    _strip_trailing_employer only when the employer does NOT match the target
    (test_parse_keeps_a_trailing_at_clause_for_a_different_employer already locks
    that the *parser* must not touch it — this is a separate, later filter that
    drops the contact from find_contacts' results once that mismatch is visible)."""
    serp = [
        {"title": "Daniel Williams - Co-Founder at oltrashoes - Skyfront | LinkedIn", "link": "https://linkedin.com/in/dw"},
        {"title": "Val Vee - VP of Operations - Skyfront | LinkedIn", "link": "https://linkedin.com/in/vv"},
    ]
    names = [c.name for c in find_contacts("Skyfront", search=lambda q, num=10: serp)]
    assert names == ["Val Vee"]


def test_find_contacts_keeps_a_title_that_only_mentions_another_company():
    """A different-employer clause must be a TRAILING "at/@ <company>", not any
    mention — "Neros Program Lead for Archer" names no other employer at all."""
    serp = [{"title": "Sam Reed - Neros Program Lead for Archer - Neros | LinkedIn", "link": "https://linkedin.com/in/sr"}]
    names = [c.name for c in find_contacts("Neros", search=lambda q, num=10: serp)]
    assert names == ["Sam Reed"]


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
