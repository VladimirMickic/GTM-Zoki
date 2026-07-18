"""S5 — enrichment: Serper-sourced raw signals + Claude synthesis prompt."""
from gtm.enrich import build_signal_prompt, enrich, find_company_linkedin, find_news, find_reddit_signal
from gtm.schema import Prospect

SERPS = {
    "linkedin": [
        {"title": "Teal Drones | LinkedIn", "link": "https://www.linkedin.com/company/teal-drones", "snippet": "sUAS maker"},
    ],
    "reddit": [
        {"title": "Teal 2 field review : r/UAVmapping", "link": "https://reddit.com/r/UAVmapping/abc", "snippet": "impressed with thermal"},
    ],
    "news": [
        {"title": "Teal Drones wins US Army SRR Tranche 2", "link": "https://example.com/srr", "snippet": "contract award"},
        {"title": "Teal launches Black Widow", "link": "https://example.com/bw", "snippet": "new drone"},
        {"title": "Old post", "link": "https://example.com/old", "snippet": "misc"},
        {"title": "Fourth item", "link": "https://example.com/4", "snippet": "misc"},
        {"title": "Fifth item", "link": "https://example.com/5", "snippet": "misc"},
        {"title": "Sixth item", "link": "https://example.com/6", "snippet": "misc"},
    ],
}


def fake_search(query, num=10):
    if "site:linkedin.com/company" in query:
        return SERPS["linkedin"]
    if "site:reddit.com" in query:
        return SERPS["reddit"]
    return SERPS["news"]


def test_company_linkedin_first_company_page():
    assert find_company_linkedin("Teal Drones", search=fake_search) == "https://www.linkedin.com/company/teal-drones"


def test_reddit_signal_is_title_plus_link():
    sig = find_reddit_signal("Teal Drones", search=fake_search)
    assert "Teal 2 field review" in sig
    assert "reddit.com" in sig


def test_news_capped_at_five():
    news = find_news("Teal Drones", search=fake_search)
    assert len(news) == 5  # capped, feedback 2026-07-18: multiple sources
    # each item: Title — snippet (url), so the sheet shows a short description
    assert news[0] == "Teal Drones wins US Army SRR Tranche 2 — contract award (https://example.com/srr)"


def test_enrich_fills_prospect_fields():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")
    enrich(p, search=fake_search)
    assert p.linkedin.endswith("/company/teal-drones")
    assert p.reddit_signal
    assert len(p.key_news) == 5


def test_empty_serps_leave_fields_blank():
    p = Prospect(company="Ghost", website="https://ghost.com")
    enrich(p, search=lambda q, num=10: [])
    assert p.linkedin == ""
    assert p.reddit_signal == ""
    assert p.key_news == []


def test_signal_prompt_has_evidence_and_contract():
    p = Prospect(company="Teal Drones", website="https://t.com", key_news=["Teal wins SRR (url)"], reddit_signal="review — url")
    prompt = build_signal_prompt(p)
    assert "Teal wins SRR" in prompt
    assert "buying_signals" in prompt
    assert "outreach_angle" in prompt


def test_find_news_trims_long_snippets_and_survives_missing_snippet():
    long_snip = " ".join(f"w{i}" for i in range(40))
    results = [
        {"title": "Long", "link": "https://x.com/a", "snippet": long_snip},
        {"title": "NoSnip", "link": "https://x.com/b"},
    ]
    news = find_news("X", search=lambda q, num=10: results)
    assert "w24 …" in news[0] and "w25" not in news[0]  # trimmed to 25 words
    assert news[1] == "NoSnip (https://x.com/b)"        # no dangling " — "


def test_signal_prompt_demands_lines_with_source_and_date():
    # feedback 2026-07-18: signals need "what — why it matters (source, date)" lines
    p = Prospect(company="X", website="https://x.com")
    prompt = build_signal_prompt(p)
    assert "why it matters" in prompt.lower()
    assert "source" in prompt.lower()
    assert "date" in prompt.lower()
    assert "plain english" in prompt.lower()


def test_news_and_reddit_queries_carry_drone_disambiguator():
    # discover-3 2026-07-18: "Paladin" news returned lenders, awards, r/Fantasy
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    find_news("Paladin", search=spy)
    find_reddit_signal("Paladin", search=spy)
    assert all("drone" in q.lower() for q in captured), captured
