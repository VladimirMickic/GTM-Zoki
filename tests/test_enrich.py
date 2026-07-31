"""S5 — enrichment: Serper-sourced raw signals + Claude synthesis prompt."""
from gtm.enrich import (
    _Headcount,
    _SignalDate,
    _SignalList,
    build_signal_prompt,
    date_undated_signal,
    enrich,
    find_community_signals,
    find_company_linkedin,
    find_headcount,
    find_news,
    redate_undated_signals,
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


def test_find_news_keeps_full_snippet_and_survives_missing_snippet():
    long_snip = " ".join(f"w{i}" for i in range(40))
    results = [
        {"title": "Long", "link": "https://x.com/a", "snippet": long_snip},
        {"title": "NoSnip", "link": "https://x.com/b"},
    ]
    news = find_news("X", search=lambda q, num=10: results)
    assert "w39" in news[0]                             # full snippet kept, not trimmed
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


def test_signal_prompt_asks_claude_to_rejudge_community_signal_candidates():
    # 2026-07-28: gpt-4o-mini's pain-vs-satisfied call (Gate 2) leaked false
    # positives live even after prompt/structural hardening — the candidates
    # it emits are shown to Claude as unconfirmed, not fact, and Claude's
    # verdict (not gpt-4o-mini's) is what the signals.json reply must return.
    p = Prospect(company="X", website="https://x.com",
                 community_signals=['"unfiltered candidate quote" (reddit.com)'])
    prompt = build_signal_prompt(p)
    assert "candidate" in prompt.lower()
    assert "satisfied" in prompt.lower()  # re-state the reject criterion, not just show the list
    assert '"community_signals": ["..."]' in prompt


# ---- community signals (2026-07-27 pain-focused redesign) ----

PAIN_HIT = {"title": "Black Widow frame cracked after two flights, case was too flimsy", "link": "https://reddit.com/r/UAVmapping/abc", "snippet": "shipped in the stock soft case and it cracked in transit"}
OWN_POST_HIT = {"title": "Teal Drones (@TealDrones) / Posts / X", "link": "https://x.com/TealDrones", "snippet": "our latest launch"}
IRRELEVANT_HIT = {"title": "QS Blueprint for the Future of Energy Storage", "link": "https://reddit.com/r/energy/xyz", "snippet": "unrelated thread"}

FILTERED = _SignalList(signals=[{"quote": "shipped in the stock soft case and it cracked in transit", "source": "reddit.com", "problem": "airframe cracked in transit in the stock soft case"}])
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
    assert "drone case foam" in captured[1]
    assert not any("Pelican" in q or "Nanuk" in q for q in captured)


def test_infer_category_prefers_use_case_over_the_ndaa_flag():
    """Live cold run 2026-07-27 (Arcsky): us_made_ndaa short-circuited ahead of the
    description keywords, so a surveying/mapping company was queried as "defense
    sUAS" — which returned 12/12 defense-POLICY results (Pentagon demos, AFSC career
    threads, IDF posts) and zero transport pain. Arcsky's real operator community is
    r/UAVmapping and r/Surveying. NDAA compliance is a procurement attribute, not a
    use case, and nearly every US maker in the ICP has it — so it must never
    outrank an explicit use-case keyword."""
    from gtm.enrich import _infer_category

    p = Prospect(
        company="Arcsky",
        website="https://arcskytech.com",
        us_made_ndaa=True,
        description=(
            "American-made, NDAA-compliant industrial drones engineered for surveying, "
            "mapping, and infrastructure inspection."
        ),
    )
    assert _infer_category(p) == "survey and mapping drone"


def test_infer_category_also_scans_case_evidence():
    """description doesn't always carry the use case — case_evidence (the scrape's
    own read of what they ship in / who they sell to) often does. Widened
    2026-07-28: description-only matching routed any company whose niche only
    showed up in case_evidence to the generic "field-deployed drone" fallback,
    which is the exact coarseness the GTM-engineer review flagged."""
    from gtm.enrich import _infer_category

    p = Prospect(
        company="X",
        website="https://x.com",
        description="American-made unmanned aircraft.",
        case_evidence="Ships to powerline patrol crews in a soft duffel bag.",
    )
    assert _infer_category(p) == "utility inspection drone"


def test_infer_category_also_scans_drone_models():
    """A model line can name the use case ("Guardian Public Safety UAV") when the
    marketing description doesn't."""
    from gtm.enrich import _infer_category

    p = Prospect(
        company="X",
        website="https://x.com",
        description="American-made unmanned aircraft.",
        drone_models=["Guardian Public Safety UAV"],
    )
    assert _infer_category(p) == "public safety drone"


def test_infer_category_buckets_agriculture():
    """Agriculture had no bucket until 2026-07-29, so every ag-drone maker fell to
    the fallback. Live run us-drone-13 (Hylio): description said "AgDrones ...
    agricultural operators ... crop treatments" and still queried the fallback.
    Measured the same day, 10 raw hits each: "agricultural spray drone" returned
    10/10 genuine ag-operator threads (r/farming, r/Agriculture, r/diydrones),
    while the then-fallback "field-deployed drone" returned r/ftlgame, r/WarCollege,
    r/amateurradio and r/LancerRPG — "deploy" collides across whole genres."""
    from gtm.enrich import _infer_category

    p = Prospect(
        company="Hylio",
        website="https://hyl.io",
        description="Hylio manufactures AgDrones for agricultural operators, "
        "planning and reporting crop treatments.",
    )
    assert _infer_category(p) == "agricultural spray drone"


def test_infer_category_falls_back_to_gear_level_not_mission_level():
    """No use-case keyword → the gear-level fallback, never a mission phrase.
    Measured 2026-07-27: "defense sUAS" returned 10/10 defense-policy results and
    "defense drone" returned 4/10 FTL: Faster Than Light (the game has a "Defense
    Drone" item) — both 0 pain. The gear-level phrase measured 8/10 pain vocabulary.

    The fallback was "field-deployed drone" until 2026-07-29 despite this test's
    name, because the gear-level phrase was benched on 2026-07-27 for leaking
    satisfied DIY chatter past the relevance filter. Re-measured 2026-07-29:
    "field-deployed drone" scored 0/10 on-topic (r/ftlgame, r/WarCollege,
    r/amateurradio, r/LancerRPG — "deployed" is the collision), while the
    gear-level phrase scored 10/10 transport-case content. The bench reason also
    expired: find_community_signals became candidates-NOT-a-verdict on 2026-07-28,
    one day after the bench, so Claude re-judges every candidate in
    build_signal_prompt. A leaked satisfied quote now costs prompt tokens; a
    fallback that reaches r/LancerRPG costs the entire pain block."""
    from gtm.enrich import _infer_category

    p = Prospect(
        company="Neros",
        website="https://n.com",
        us_made_ndaa=True,
        description="American-made NDAA-compliant unmanned aircraft.",
    )
    assert _infer_category(p) == "drone case foam"


def test_infer_category_ignores_the_ndaa_flag_entirely():
    """NDAA compliance must not steer the query at all — same description, both
    flag values, same category."""
    from gtm.enrich import _infer_category

    kw = dict(company="X", website="https://x.com", description="drones for surveying")
    assert _infer_category(Prospect(**kw, us_made_ndaa=True)) == _infer_category(
        Prospect(**kw, us_made_ndaa=False)
    ) == "survey and mapping drone"


def test_every_category_phrase_says_drone():
    """Same load-bearing-"drone" rule the model query already follows: "defense sUAS"
    was the only category phrase missing the word, and "sUAS" is procurement jargon
    no operator types on Reddit. Every phrase must name the aircraft."""
    from gtm.enrich import _CATEGORY_KEYWORDS, _DEFAULT_CATEGORY

    phrases = [c for c, _ in _CATEGORY_KEYWORDS] + [_DEFAULT_CATEGORY]
    for phrase in phrases:
        assert "drone" in phrase, f"{phrase!r} must name the aircraft"


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


def test_relevance_filter_drops_signals_that_name_no_problem():
    """Structural Gate 2, not another prompt example. Live 2026-07-27: better
    queries surfaced more candidates and the yes/no gate leaked 5 of 6 — "I laser
    cut a custom foam insert for my drone", "It's only $30", "The foam is pick and
    pull". All topically perfect, all describing setups that WORK. The model must
    now name the harm in a `problem` field; anything it cannot fill is not pain."""
    from gtm.enrich import _SignalList, _relevance_filter

    parsed = _SignalList(signals=[
        {"quote": "I laser cut a custom foam insert for my drone.", "source": "reddit.com",
         "problem": ""},
        {"quote": "Foam quickly deteriorates allowing my frame to move and crack in transit.",
         "source": "reddit.com", "problem": "foam degrades and the airframe cracks in transit"},
    ])
    out = _relevance_filter([{"title": "t", "snippet": "s", "link": "l"}], client=FakeClient(parsed))
    assert len(out) == 1
    assert "Foam quickly deteriorates" in out[0]


def test_relevance_filter_drops_signals_whose_problem_is_filler():
    """The escape hatch to close: a model told to fill `problem` will write "none"
    or "n/a" rather than leave it blank."""
    from gtm.enrich import _SignalList, _relevance_filter

    for filler in ("none", "N/A", "no problem", "-", "nothing"):
        parsed = _SignalList(signals=[
            {"quote": "Nice case, works great.", "source": "reddit.com", "problem": filler},
        ])
        out = _relevance_filter([{"title": "t", "snippet": "s", "link": "l"}], client=FakeClient(parsed))
        assert out == [], f"{filler!r} should not count as a problem"


def test_relevance_prompt_rejects_a_working_setup_and_non_physical_case():
    """Live re-run after the category fix (2026-07-27, Arcsky) leaked one quote:
    '"Our drones are stored in a plastic case with a BMS." (diydrones.com)'. It names
    a drone and a case, so Gates 0/1 pass — but nothing goes wrong, and a pain block
    citing it is exactly the "true but empty" filler the pipeline exists to avoid.
    The same run's SERP also carried "NC Drone Mapping Case", a *court* case."""
    from gtm.enrich import _RELEVANCE_PROMPT

    lowered = _RELEVANCE_PROMPT.lower()
    assert "plastic case with a bms" in lowered  # the leaked quote, as a named reject
    assert "legal case" in lowered and "use case" in lowered


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
    assert "drone case foam" in captured[0]


def test_community_signals_falls_back_to_gear_level_category():
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    p = Prospect(company="X", website="https://x.com")
    find_community_signals(p, search=spy, client=FakeClient(EMPTY))
    assert "drone case foam" in captured[0]  # no drone_models, so index 0 is the category query


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
    many = _SignalList(signals=[{"quote": f"pain {i}", "source": "reddit.com", "problem": f"harm {i}"} for i in range(5)])
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


def _enrich_search(query, num=10):
    # headcount query returns no hits here — this fixture's shared FakeClient is
    # parsed as _SignalList, not _Headcount; see test_enrich_fills_headcount_from_llm_band
    # below for a headcount-specific client/search pairing.
    if "employees" in query:
        return []
    if "site:linkedin.com/company" in query:
        return SERPS["linkedin"]
    return SERPS["news"]


def test_enrich_fills_prospect_fields():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")
    enrich(p, search=_enrich_search, client=FakeClient(FILTERED))
    assert p.linkedin.endswith("/company/teal-drones")
    assert len(p.community_signals) == 1
    assert len(p.key_news) == 5
    assert p.headcount == ""  # FakeClient(FILTERED) has no .band — see headcount tests below for that path


def test_empty_serps_leave_fields_blank():
    p = Prospect(company="Ghost", website="https://ghost.com")
    enrich(p, search=lambda q, num=10: [], client=FakeClient(EMPTY))
    assert p.linkedin == ""
    assert p.community_signals == []
    assert p.key_news == []
    assert p.headcount == ""


# ---- headcount (2026-07-27) ----

HEADCOUNT_SERPS = [
    {"title": "Teal Drones | LinkedIn", "link": "https://www.linkedin.com/company/teal-drones",
     "snippet": "Teal Drones | 51-200 followers on LinkedIn."},
]
HEADCOUNT_HIT = _Headcount(band="51-200")
HEADCOUNT_UNKNOWN = _Headcount(band="")


def test_headcount_query_targets_company_size_sources():
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    find_headcount("Teal Drones", search=spy, client=FakeClient(HEADCOUNT_UNKNOWN))
    assert len(captured) == 1
    assert '"Teal Drones"' in captured[0]
    assert "employees" in captured[0]
    assert "site:linkedin.com/company" in captured[0]


def test_headcount_prompt_forbids_inventing_a_range_from_a_number():
    """Live check on Teal Drones (2026-07-27) surfaced a real hallucination: a
    PitchBook snippet said "51 total employees" (exact count) and the LLM invented
    "1-50" — a range that appears nowhere in the source."""
    from gtm.enrich import _HEADCOUNT_PROMPT

    assert "exactly" in _HEADCOUNT_PROMPT.lower()
    assert "51-200" in _HEADCOUNT_PROMPT and "51 total employees" in _HEADCOUNT_PROMPT


def test_headcount_prompt_forbids_using_the_model_s_own_prior_knowledge():
    """Live check on Teal Drones (2026-07-27), after the range-vs-number fix above:
    no snippet in two fresh SERP pulls contained "51-200" anywhere, yet the LLM
    still returned "51-200" — it answered from training-data knowledge of Teal's
    real LinkedIn page, not from the provided text. Distinct root cause from the
    range/number bug above (grounding, not format), so it gets its own guard."""
    from gtm.enrich import _HEADCOUNT_PROMPT

    assert "only the" in _HEADCOUNT_PROMPT.lower()
    assert "training" in _HEADCOUNT_PROMPT.lower()


def test_headcount_prompt_prefers_linkedin_and_rejects_unresolvable_conflicts():
    """Live check on Neros Technologies (2026-07-27) surfaced a second real bug:
    craft.co said "5 employees", LinkedIn's own jobs page said "171 employees" —
    the LLM picked craft.co's smaller, less authoritative number."""
    from gtm.enrich import _HEADCOUNT_PROMPT

    assert "linkedin.com" in _HEADCOUNT_PROMPT.lower()
    assert "disagree" in _HEADCOUNT_PROMPT.lower()


def test_headcount_returns_llm_parsed_band():
    band = find_headcount("Teal Drones", search=lambda q, num=10: HEADCOUNT_SERPS, client=FakeClient(HEADCOUNT_HIT))
    assert band == "51-200"


def test_headcount_empty_when_no_serp_results():
    assert find_headcount("Ghost", search=lambda q, num=10: [], client=FakeClient(HEADCOUNT_HIT)) == ""


def test_headcount_empty_when_llm_finds_no_band():
    band = find_headcount("Teal Drones", search=lambda q, num=10: HEADCOUNT_SERPS, client=FakeClient(HEADCOUNT_UNKNOWN))
    assert band == ""


def test_headcount_logs_openai_cost():
    from gtm.costlog import CostLog

    class FakeCostLog(CostLog):
        def __init__(self):
            self.records = []

        def record(self, **kwargs):
            self.records.append(kwargs)

    cl = FakeCostLog()
    find_headcount("Teal Drones", search=lambda q, num=10: HEADCOUNT_SERPS, client=FakeClient(HEADCOUNT_HIT), costlog=cl)
    assert len(cl.records) == 1
    assert cl.records[0]["stage"] == "headcount"
    assert cl.records[0]["model"] == "gpt-4o-mini"


def test_enrich_fills_headcount_from_llm_band():
    # community-signal/news queries return no hits here so the shared FakeClient
    # (parsed as _Headcount, not _SignalList) is never asked to parse a signal list.
    def search(q, num=10):
        return HEADCOUNT_SERPS if "employees" in q else []

    p = Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")
    enrich(p, search=search, client=FakeClient(HEADCOUNT_HIT))
    assert p.headcount == "51-200"
    assert p.community_signals == []


# ---- cold-run bugs (cold-0727, Arcsky, 2026-07-27) ----


def test_airframe_query_pins_the_model_name_to_drones():
    """Cold live run on Arcsky surfaced a cross-category collision: the bare model
    token "X55" returned 10/10 junk — a PowKiddy handheld game console, a 7.5x55
    Swiss rifle cartridge, and a TP-Link X55 router — and zero drone results. A
    short alphanumeric model name is meaningless without a category word."""
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    p = Prospect(company="Arcsky", website="https://arcskytech.com", drone_models=["X55"])
    find_community_signals(p, search=spy, client=FakeClient(EMPTY))
    assert '"X55"' in captured[0]
    assert "drone" in captured[0].lower()


def test_relevance_prompt_rejects_pain_about_non_drone_hardware():
    """Same cold run: the filter KEPT "Ordered an X55 from the AliExpress store only
    to discover it had been damaged in transit" — a real person, real transport
    damage, so both existing gates passed. The hardware was a games console. No gate
    checked that the damaged thing was a drone; distinct root cause from the
    Perimeter-8 sentence-meaning collision, so it gets its own gate and guard."""
    from gtm.enrich import _RELEVANCE_PROMPT

    low = _RELEVANCE_PROMPT.lower()
    assert "console" in low  # names the actual collision class
    assert "aircraft" in low or "uav" in low


def test_headcount_prompt_rejects_a_similarly_named_different_company():
    """Cold live run on Arcsky (arcskytech.com, drone maker, Austin TX) returned
    "11-50" — which belonged to ARC at arcsky.com, an AIRLINE ("Industry: Airlines
    and Aviation"). Grounding was fine and LinkedIn preference was fine; the result
    was simply a different company. The disambiguating text ("Website:
    http://www.arcsky.com") was right there in the snippet, so the model had the
    evidence and lacked the rule."""
    from gtm.enrich import _HEADCOUNT_PROMPT

    low = _HEADCOUNT_PROMPT.lower()
    assert "same company" in low or "different company" in low
    assert "website" in low or "domain" in low


def test_headcount_gives_the_model_the_company_domain_to_match_on():
    """The rule above is unusable without the domain: "Arcsky" alone cannot
    distinguish arcskytech.com from arcsky.com."""
    seen = {}

    class SpyClient(FakeClient):
        def parse(self, **kwargs):
            seen["text"] = kwargs["messages"][1]["content"]
            return super().parse(**kwargs)

    find_headcount(
        "Arcsky",
        website="https://www.arcskytech.com/",
        search=lambda q, num=10: HEADCOUNT_SERPS,
        client=SpyClient(HEADCOUNT_UNKNOWN),
    )
    assert "arcskytech.com" in seen["text"]


def test_enrich_passes_the_website_through_to_headcount():
    seen = {}

    class SpyClient(FakeClient):
        def parse(self, **kwargs):
            seen["text"] = kwargs["messages"][1]["content"]
            return super().parse(**kwargs)

    def search(q, num=10):
        return HEADCOUNT_SERPS if "employees" in q else []

    p = Prospect(company="Arcsky", website="https://www.arcskytech.com/", status="priority")
    enrich(p, search=search, client=SpyClient(HEADCOUNT_UNKNOWN))
    assert "arcskytech.com" in seen["text"]


def test_news_queries_carry_drone_disambiguator():
    # discover-3 2026-07-18: "Paladin" news returned lenders, awards, r/Fantasy
    captured = []

    def spy(q, num=10):
        captured.append(q)
        return []

    find_news("Paladin", search=spy)
    assert "drone" in captured[0].lower()


# --- 2026-07-28: signal quality gate (run test-batch-1) ---
# 4 of 9 buying signals were noise: an IDIQ ceiling on a shared multi-award vehicle
# read as the prospect's own budget, an unawarded SBIR proposal, an equity-analyst
# price note, and a directory listing. All were 1-2 years old, and one draft opened
# "congrats" about a 2025 event in a July 2026 email.


def test_find_news_drops_the_prospects_own_domain():
    results = [
        {"title": "Easy Aerial | Autonomous Drone Systems", "link": "https://easyaerial.com/", "snippet": "our homepage"},
        {"title": "Easy Aerial wins Air Force contract", "link": "https://defensenews.com/x", "snippet": "award"},
    ]
    news = find_news("Easy Aerial", website="https://www.easyaerial.com", search=lambda q, num=10: results)
    assert len(news) == 1
    assert "defensenews.com" in news[0]


def test_find_news_drops_own_subdomains_too():
    results = [
        {"title": "Press release", "link": "https://news.easyaerial.com/pr/1", "snippet": "we announce"},
        {"title": "Third party", "link": "https://suasnews.com/x", "snippet": "coverage"},
    ]
    news = find_news("Easy Aerial", website="https://easyaerial.com", search=lambda q, num=10: results)
    assert len(news) == 1
    assert "suasnews.com" in news[0]


def test_find_news_without_a_website_keeps_everything():
    results = [{"title": "T", "link": "https://easyaerial.com/", "snippet": "s"}]
    assert len(find_news("Easy Aerial", search=lambda q, num=10: results)) == 1


def test_signal_prompt_states_todays_date_and_the_recency_cutoff():
    from datetime import date

    from gtm.enrich import RECENCY_MONTHS

    p = Prospect(company="Red Cat", website="https://redcatholdings.com", key_news=["FANG cleared Blue UAS (url, 2025-03-01)"])
    prompt = build_signal_prompt(p, today=date(2026, 7, 28))
    assert "2026-07-28" in prompt
    assert str(RECENCY_MONTHS) in prompt
    assert "[stale]" in prompt
    assert "[undated]" in prompt


def test_signal_prompt_rejects_proposals_analyst_notes_and_shared_ceilings():
    p = Prospect(company="Red Cat", website="https://redcatholdings.com")
    low = build_signal_prompt(p).lower()
    assert "proposal" in low          # unawarded bids are not signals
    assert "price target" in low      # equity-analyst notes are not signals
    assert "ceiling" in low           # a shared multi-award IDIQ ceiling is not their revenue
    assert "directory" in low         # profile/listing pages are not news


def test_signal_prompt_defaults_to_today_when_no_date_is_passed():
    from datetime import date

    p = Prospect(company="X", website="https://x.com")
    assert date.today().isoformat() in build_signal_prompt(p)


# --- trigger dating: item 3, 2026-07-30 — [undated] signals never got a follow-up
# search to actually find out when they happened. date_undated_signal is the one
# search+extract call; redate_undated_signals applies it across a prospect's list.

def test_date_undated_signal_returns_the_date_the_model_found():
    hits = [{"title": "Teal wins award", "link": "https://x.com/a", "snippet": "announced March 2026"}]
    found = date_undated_signal(
        "Teal Drones", "Won Army SRR contract", search=lambda q, num=10: hits,
        client=FakeClient(_SignalDate(date="2026-03")),
    )
    assert found == "2026-03"


def test_date_undated_signal_returns_empty_when_model_finds_nothing():
    hits = [{"title": "unrelated", "link": "https://x.com/a", "snippet": "no date here"}]
    found = date_undated_signal(
        "Teal Drones", "Won Army SRR contract", search=lambda q, num=10: hits,
        client=FakeClient(_SignalDate(date="")),
    )
    assert found == ""


def test_date_undated_signal_skips_the_model_call_when_search_is_empty():
    calls = []

    class ExplodingClient:
        chat = completions = None

        def __getattr__(self, name):
            raise AssertionError("client must not be touched when search returned nothing")

    found = date_undated_signal(
        "Teal Drones", "Won Army SRR contract", search=lambda q, num=10: [],
        client=ExplodingClient(),
    )
    assert found == ""


def test_date_undated_signal_charges_serper_even_on_a_miss():
    from gtm.costlog import CostLog

    class FakeCostLog(CostLog):
        def __init__(self):
            self.records = []

        def record(self, **kwargs):
            self.records.append(kwargs)

    cl = FakeCostLog()
    date_undated_signal(
        "Teal Drones", "Won Army SRR contract", search=lambda q, num=10: [],
        client=FakeClient(_SignalDate(date="")), costlog=cl,
    )
    assert len(cl.records) == 1
    assert cl.records[0]["provider"] == "serper"


def test_date_undated_signal_logs_openai_cost_on_a_hit():
    from gtm.costlog import CostLog

    class FakeCostLog(CostLog):
        def __init__(self):
            self.records = []

        def record(self, **kwargs):
            self.records.append(kwargs)

        def record_serper(self, **kwargs):
            self.records.append({"provider": "serper", **kwargs})

    cl = FakeCostLog()
    hits = [{"title": "t", "link": "https://x.com/a", "snippet": "s"}]
    date_undated_signal(
        "Teal Drones", "Won Army SRR contract", search=lambda q, num=10: hits,
        client=FakeClient(_SignalDate(date="2026-03")), costlog=cl,
    )
    openai_records = [r for r in cl.records if r.get("model") == "gpt-4o-mini"]
    assert len(openai_records) == 1
    assert openai_records[0]["stage"] == "signal_dating"


def test_redate_undated_signals_ignores_lines_that_are_not_undated():
    from datetime import date

    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        buying_signals=[
            "Won Army SRR contract — validates gov demand (TechCrunch, 2026-05) ",
            "Old funding round — context only (PR Newswire, 2020-01) [stale]",
        ],
    )
    before = list(p.buying_signals)
    dated = redate_undated_signals(
        p, search=lambda q, num=10: (_ for _ in ()).throw(AssertionError("must not search")),
        client=None, today=date(2026, 7, 30),
    )
    assert dated == 0
    assert p.buying_signals == before


def test_redate_undated_signals_inserts_a_found_date_and_drops_the_marker():
    from datetime import date

    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        buying_signals=["Won Army SRR contract — validates gov demand (TechCrunch) [undated]"],
    )
    hits = [{"title": "t", "link": "https://x.com/a", "snippet": "March 2026"}]
    dated = redate_undated_signals(
        p, search=lambda q, num=10: hits, client=FakeClient(_SignalDate(date="2026-03")),
        today=date(2026, 7, 30),
    )
    assert dated == 1
    assert p.buying_signals == [
        "Won Army SRR contract — validates gov demand (TechCrunch, dated 2026-03)"
    ]


def test_redate_undated_signals_marks_a_found_old_date_stale():
    from datetime import date

    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        buying_signals=["Old award — still relevant context (TechCrunch) [undated]"],
    )
    dated = redate_undated_signals(
        p, search=lambda q, num=10: [{"title": "t", "link": "https://x.com/a", "snippet": "s"}],
        client=FakeClient(_SignalDate(date="2024-01")), today=date(2026, 7, 30),
    )
    assert dated == 1
    assert p.buying_signals[0].endswith("(TechCrunch, dated 2024-01) [stale]")


def test_redate_undated_signals_leaves_the_marker_when_nothing_is_found():
    from datetime import date

    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        buying_signals=["Mentioned in a roundup — weak signal (blog.example.com) [undated]"],
    )
    dated = redate_undated_signals(
        p, search=lambda q, num=10: [], client=FakeClient(_SignalDate(date="")),
        today=date(2026, 7, 30),
    )
    assert dated == 0
    assert p.buying_signals == [
        "Mentioned in a roundup — weak signal (blog.example.com) [undated]"
    ]


def test_redate_undated_signals_appends_a_parenthetical_when_the_line_has_none():
    from datetime import date

    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        buying_signals=["Some claim with no source at all [undated]"],
    )
    dated = redate_undated_signals(
        p, search=lambda q, num=10: [{"title": "t", "link": "https://x.com/a", "snippet": "s"}],
        client=FakeClient(_SignalDate(date="2026-06")), today=date(2026, 7, 30),
    )
    assert dated == 1
    assert p.buying_signals == ["Some claim with no source at all (dated 2026-06)"]


def test_redate_undated_signals_ignores_a_date_the_model_cannot_parse():
    from datetime import date

    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        buying_signals=["Vague claim (source) [undated]"],
    )
    dated = redate_undated_signals(
        p, search=lambda q, num=10: [{"title": "t", "link": "https://x.com/a", "snippet": "s"}],
        client=FakeClient(_SignalDate(date="not a date")), today=date(2026, 7, 30),
    )
    assert dated == 0
    assert p.buying_signals == ["Vague claim (source) [undated]"]


# 2026-07-30 (user, reading run us-drone-20's Anduril news): "this doesn't give any
# useful info". The truncation they saw was Google's own "..." inside the snippet, not
# ours — but the audit found two real defects behind the complaint: 5 news slots held
# only 2 distinct events (the CCA contract appeared 3x, one of them a YouTube clip),
# and a signal was written "[undated]" from a source whose own text said "April 2024".


def test_find_news_drops_video_and_social_hosts():
    results = [
        {"title": "Anduril Secures Landmark Air Force Drone Contract", "link": "https://www.youtube.com/watch?v=OyG11iKEoJ8", "snippet": "video"},
        {"title": "Army awards Anduril counter-drone task order", "link": "https://breakingdefense.com/x", "snippet": "$87 million"},
    ]
    news = find_news("Anduril", search=lambda q, num=10: results)
    assert len(news) == 1
    assert "breakingdefense.com" in news[0]


def test_find_news_dedupes_the_same_event_across_outlets():
    results = [
        {"title": "Air Force Selects General Atomics and Anduril for CCA production", "link": "https://airandspaceforces.com/a", "snippet": "one"},
        {"title": "Air Force selects Anduril and General Atomics for CCA production", "link": "https://jpost.com/b", "snippet": "same story, other outlet"},
        {"title": "Army awards Anduril $87M counter-drone task order", "link": "https://breakingdefense.com/c", "snippet": "different event"},
    ]
    news = find_news("Anduril", search=lambda q, num=10: results)
    assert len(news) == 2
    assert "airandspaceforces.com" in news[0] and "breakingdefense.com" in news[1]


def test_find_news_backfills_the_freed_slots_with_distinct_events():
    """Dropping dupes must not shrink the list below MAX_NEWS when the SERP still has
    distinct stories further down — same Serper credit, more actual evidence."""
    dupes = [{"title": "Anduril wins CCA production contract", "link": f"https://outlet{i}.com/x", "snippet": "s"} for i in range(4)]
    distinct = [
        {"title": "Anduril opens Ohio manufacturing plant", "link": "https://trade1.com/a", "snippet": "s"},
        {"title": "Lattice software picked as counter-drone backbone", "link": "https://trade2.com/b", "snippet": "s"},
        {"title": "Ghost X airframe cleared for Blue UAS", "link": "https://trade3.com/c", "snippet": "s"},
        {"title": "Series G funding round closes", "link": "https://trade4.com/d", "snippet": "s"},
        {"title": "Navy tests Dive-LD underwater vehicle", "link": "https://trade5.com/e", "snippet": "s"},
    ]
    news = find_news("Anduril", search=lambda q, num=10: dupes + distinct)
    assert len(news) == 5  # 1 of the 4 dupes + 4 distinct, not 1 + nothing


def test_news_line_stamps_the_date_from_the_url_path():
    results = [{"title": "Army awards Anduril task order", "link": "https://breakingdefense.com/2026/03/army-awards-anduril/", "snippet": "$87 million"}]
    assert find_news("Anduril", search=lambda q, num=10: results)[0].endswith("[date: 2026-03]")


def test_news_line_stamps_the_date_from_prose_when_the_url_has_none():
    results = [{"title": "Air Force Selects Anduril for CCA", "link": "https://airandspaceforces.com/cca-contracts/", "snippet": "In April 2024, the Air Force awarded contracts"}]
    assert find_news("Anduril", search=lambda q, num=10: results)[0].endswith("[date: 2024-04]")


def test_news_line_has_no_stamp_when_nothing_dates_the_result():
    results = [{"title": "Anduril profile", "link": "https://trade.com/anduril", "snippet": "no date anywhere"}]
    assert "[date:" not in find_news("Anduril", search=lambda q, num=10: results)[0]


def test_signal_prompt_forbids_undated_on_a_dated_news_line():
    p = Prospect(company="Anduril", website="https://anduril.com", key_news=["X (url) [date: 2026-03]"])
    prompt = build_signal_prompt(p)
    assert "[date: YYYY-MM]" in prompt
    assert "EXACTLY" in prompt


def test_same_event_different_outlet_is_deduped():
    results = [
        {"title": "Army awards Anduril counter-drone task order as first in new vehicle",
         "link": "https://breakingdefense.com/2026/03/army-awards-anduril/",
         "snippet": "The Army-run counter-drone task force has selected Anduril's Lattice"},
        {"title": "Air Force Selects General Atomics and Anduril for CCA production",
         "link": "https://www.airandspaceforces.com/air-force-anduril-cca-production/",
         "snippet": "In April 2024, the Air Force awarded contracts to continue designing"},
        {"title": "US Air Force awards production contracts to Anduril for CCA",
         "link": "https://www.jpost.com/defense-and-tech/article-899781",
         "snippet": "Anduril says the production line can deliver up to 150 aircraft/year"},
    ]
    out = find_news("Anduril", website="https://www.anduril.com/",
                    search=lambda q, num=10: results)
    assert len(out) == 2, out
    assert any("counter-drone" in line for line in out)
    assert sum("CCA" in line for line in out) == 1
