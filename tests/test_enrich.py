"""S5 — enrichment: Serper-sourced raw signals + Claude synthesis prompt."""
from gtm.enrich import (
    _SignalList,
    build_signal_prompt,
    enrich,
    find_community_signals,
    find_company_linkedin,
    find_news,
)
from gtm.schema import Prospect

SERPS = {
    "linkedin": [
        {"title": "Teal Drones | LinkedIn", "link": "https://www.linkedin.com/company/teal-drones", "snippet": "sUAS maker"},
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
    return SERPS["news"]


class FakeClient:
    """Mirrors tests/test_discover.py's FakeClient shape for
    client.chat.completions.parse(...) → .choices[0].message.parsed / .usage."""

    def __init__(self, parsed):
        self._parsed = parsed
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        parsed = self._parsed

        class Msg:
            pass

        Msg.parsed = parsed

        class Choice:
            message = Msg()

        class Usage:
            prompt_tokens = 40
            completion_tokens = 15

        class Completion:
            choices = [Choice()]
            usage = Usage()

        return Completion()


def test_company_linkedin_first_company_page():
    assert find_company_linkedin("Teal Drones", search=fake_search) == "https://www.linkedin.com/company/teal-drones"


def test_company_linkedin_skips_result_for_a_different_company():
    # 2026-07-21: AeroVironment search returned Blue Halo LLC's page first (Blue
    # Halo is mentioned alongside AV in unrelated results) — must skip a /company/
    # link whose slug doesn't match the target company name.
    def search(query, num=10):
        return [
            {"title": "Blue Halo | LinkedIn", "link": "https://www.linkedin.com/company/bluehalollc", "snippet": "AV company"},
            {"title": "AeroVironment | LinkedIn", "link": "https://www.linkedin.com/company/aerovironment", "snippet": "drones"},
        ]
    assert find_company_linkedin("AeroVironment", search=search) == "https://www.linkedin.com/company/aerovironment"


def test_company_linkedin_empty_when_no_result_matches_company():
    def search(query, num=10):
        return [{"title": "Blue Halo | LinkedIn", "link": "https://www.linkedin.com/company/bluehalollc", "snippet": "AV company"}]
    assert find_company_linkedin("AeroVironment", search=search) == ""


def test_news_capped_at_five():
    news = find_news("Teal Drones", search=fake_search)
    assert len(news) == 5  # capped, feedback 2026-07-18: multiple sources
    # each item: Title — snippet (url), so the sheet shows a short description
    assert news[0] == "Teal Drones wins US Army SRR Tranche 2 — contract award (https://example.com/srr)"


def test_find_news_trims_long_snippets_and_survives_missing_snippet():
    long_snip = " ".join(f"w{i}" for i in range(40))
    results = [
        {"title": "Long", "link": "https://x.com/a", "snippet": long_snip},
        {"title": "NoSnip", "link": "https://x.com/b"},
    ]
    news = find_news("X", search=lambda q, num=10: results)
    assert "w24 …" in news[0] and "w25" not in news[0]  # trimmed to 25 words
    assert news[1] == "NoSnip (https://x.com/b)"        # no dangling " — "


def test_signal_prompt_has_evidence_and_contract():
    p = Prospect(company="Teal Drones", website="https://t.com", key_news=["Teal wins SRR (url)"], community_signals=['"cracked in transit" (reddit.com)'])
    prompt = build_signal_prompt(p)
    assert "Teal wins SRR" in prompt
    assert "buying_signals" in prompt
    assert "outreach_angle" in prompt


def test_signal_prompt_demands_lines_with_source_and_date():
    # feedback 2026-07-18: signals need "what — why it matters (source, date)" lines
    p = Prospect(company="X", website="https://x.com")
    prompt = build_signal_prompt(p)
    assert "why it matters" in prompt.lower()
    assert "source" in prompt.lower()
    assert "date" in prompt.lower()
    assert "plain english" in prompt.lower()


def test_signal_prompt_expands_outreach_angle_instruction():
    p = Prospect(company="X", website="https://x.com")
    prompt = build_signal_prompt(p)
    assert "2-3 sentences" in prompt
    assert "why it's the strongest fit" in prompt
    assert "community signal" in prompt.lower()


# ---- community signals (2026-07-27 pain-focused redesign) ----

PAIN_HIT = {"title": "Black Widow frame cracked after two flights, case was too flimsy", "link": "https://reddit.com/r/UAVmapping/abc", "snippet": "shipped in the stock soft case and it cracked in transit"}
OWN_POST_HIT = {"title": "Teal Drones (@TealDrones) / Posts / X", "link": "https://x.com/TealDrones", "snippet": "our latest launch"}
IRRELEVANT_HIT = {"title": "QS Blueprint for the Future of Energy Storage", "link": "https://reddit.com/r/energy/xyz", "snippet": "unrelated thread"}

FILTERED = _SignalList(signals=[{"quote": "shipped in the stock soft case and it cracked in transit", "source": "reddit.com"}])
EMPTY = _SignalList(signals=[])


def test_community_signals_queries_airframe_and_category_only():
    """Two queries, no brand-list query: the 2026-07-27 live smoke measured the
    rugged-case-brand pain query at 0 raw hits for every company, so it only ever
    cost a Serper credit."""
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    p = Prospect(company="Teal Drones", website="https://t.com", drone_models=["Black Widow"], us_made_ndaa=True)
    find_community_signals(p, search=spy, client=FakeClient(EMPTY))
    assert len(captured) == 2
    assert '"Black Widow"' in captured[0]
    assert "defense sUAS" in captured[1]
    assert not any("Pelican" in q or "Nanuk" in q for q in captured)


def test_relevance_prompt_demands_transport_or_protection_content():
    """The live smoke let through '"there are some snaps in the perimeter, 8 of
    them.. 2 on each side of the cap that fits on top of the battery" (RCGroups)'
    — hardware chatter with no transport/protection content at all. The prompt has
    to make that a reject, not a judgement call."""
    from gtm.enrich import _RELEVANCE_PROMPT

    assert "REJECT" in _RELEVANCE_PROMPT
    assert "transport" in _RELEVANCE_PROMPT.lower()
    for clue in ("case", "bag", "foam", "shipping", "transit"):
        assert clue in _RELEVANCE_PROMPT.lower()


def test_community_signals_infers_category_from_description_when_not_ndaa():
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    p = Prospect(company="X", website="https://x.com", description="a public safety first responder drone")
    find_community_signals(p, search=spy, client=FakeClient(EMPTY))
    assert "public safety drone" in captured[0]  # no drone_models, so index 0 is the category query


def test_community_signals_category_ignores_buying_signals():
    """buying_signals is written by cmd_signals, which runs AFTER cmd_enrich
    (gtm/run.py) — it is always [] at enrich time, so the category bucket must not
    be documented or tested as if it reads it."""
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    p = Prospect(company="X", website="https://x.com",
                 buying_signals=["won a public safety first responder contract"])
    find_community_signals(p, search=spy, client=FakeClient(EMPTY))
    assert "field-deployed drone" in captured[0]


def test_community_signals_falls_back_to_field_deployed_category():
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    p = Prospect(company="X", website="https://x.com")
    find_community_signals(p, search=spy, client=FakeClient(EMPTY))
    assert "field-deployed drone" in captured[0]  # no drone_models, so index 0 is the category query


def test_community_signals_excludes_own_handle_posts_before_llm_call():
    seen_by_llm = {}

    class SpyClient(FakeClient):
        def parse(self, **kwargs):
            seen_by_llm["text"] = kwargs["messages"][1]["content"]
            return super().parse(**kwargs)

    def search(q, num=10):
        return [OWN_POST_HIT, PAIN_HIT]

    p = Prospect(company="Teal Drones", website="https://t.com")
    sigs = find_community_signals(p, search=search, client=SpyClient(FILTERED))
    assert "TealDrones" not in seen_by_llm["text"]
    assert "cracked in transit" in seen_by_llm["text"]
    assert sigs == ['"shipped in the stock soft case and it cracked in transit" (reddit.com)']


def test_community_signals_skips_llm_call_when_nothing_survives_own_post_filter():
    calls = []

    class SpyClient(FakeClient):
        def parse(self, **kwargs):
            calls.append(1)
            return super().parse(**kwargs)

    def search(q, num=10):
        return [OWN_POST_HIT]

    p = Prospect(company="Teal Drones", website="https://t.com")
    assert find_community_signals(p, search=search, client=SpyClient(EMPTY)) == []
    assert calls == []  # no LLM call spent when there's nothing to filter


def test_community_signals_dedupes_links_across_the_three_queries():
    seen_by_llm = {}

    class SpyClient(FakeClient):
        def parse(self, **kwargs):
            seen_by_llm["text"] = kwargs["messages"][1]["content"]
            return super().parse(**kwargs)

    def search(q, num=10):
        return [PAIN_HIT]  # same hit returned by both queries

    p = Prospect(company="X", website="https://x.com", drone_models=["Black Widow"])
    find_community_signals(p, search=search, client=SpyClient(FILTERED))
    assert seen_by_llm["text"].count("reddit.com/r/UAVmapping/abc") == 1


def test_community_signals_rewrites_llm_output_as_quote_and_source():
    p = Prospect(company="X", website="https://x.com")
    sigs = find_community_signals(p, search=lambda q, num=10: [PAIN_HIT], client=FakeClient(FILTERED))
    assert sigs == ['"shipped in the stock soft case and it cracked in transit" (reddit.com)']


def test_community_signals_caps_at_three():
    many = _SignalList(signals=[{"quote": f"pain {i}", "source": "reddit.com"} for i in range(5)])
    p = Prospect(company="X", website="https://x.com")
    sigs = find_community_signals(p, search=lambda q, num=10: [PAIN_HIT], client=FakeClient(many))
    assert len(sigs) == 3


def test_community_signals_empty_when_no_serp_results():
    p = Prospect(company="X", website="https://x.com")
    assert find_community_signals(p, search=lambda q, num=10: [], client=FakeClient(EMPTY)) == []


def test_community_signals_logs_openai_cost():
    from gtm.costlog import CostLog

    class FakeCostLog(CostLog):
        def __init__(self):
            self.records = []

        def record(self, **kwargs):
            self.records.append(kwargs)

    cl = FakeCostLog()
    p = Prospect(company="X", website="https://x.com")
    find_community_signals(p, search=lambda q, num=10: [PAIN_HIT], client=FakeClient(FILTERED), costlog=cl)
    assert len(cl.records) == 1
    assert cl.records[0]["stage"] == "community_signals"
    assert cl.records[0]["model"] == "gpt-4o-mini"


def test_enrich_fills_prospect_fields():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")
    enrich(p, search=lambda q, num=10: SERPS["news"] if "linkedin" not in q else SERPS["linkedin"], client=FakeClient(FILTERED))
    assert p.linkedin.endswith("/company/teal-drones")
    assert len(p.community_signals) == 1
    assert len(p.key_news) == 5


def test_empty_serps_leave_fields_blank():
    p = Prospect(company="Ghost", website="https://ghost.com")
    enrich(p, search=lambda q, num=10: [], client=FakeClient(EMPTY))
    assert p.linkedin == ""
    assert p.community_signals == []
    assert p.key_news == []


def test_news_queries_carry_drone_disambiguator():
    # discover-3 2026-07-18: "Paladin" news returned lenders, awards, r/Fantasy
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    find_news("Paladin", search=spy)
    assert "drone" in captured[0].lower()
