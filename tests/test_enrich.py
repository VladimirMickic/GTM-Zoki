"""S5 — enrichment: Serper-sourced raw signals + Claude synthesis prompt."""
from gtm.enrich import (
    _Headcount,
    _SignalList,
    build_signal_prompt,
    enrich,
    find_community_signals,
    find_company_linkedin,
    find_headcount,
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
    assert "field-deployed drone" in captured[1]
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


def test_infer_category_falls_back_to_gear_level_not_mission_level():
    """No use-case keyword → the gear-level fallback, never a mission phrase.
    Measured 2026-07-27: "defense sUAS" returned 10/10 defense-policy results and
    "defense drone" returned 4/10 FTL: Faster Than Light (the game has a "Defense
    Drone" item) — both 0 pain. The gear-level phrase measured 8/10 pain vocabulary."""
    from gtm.enrich import _infer_category

    p = Prospect(
        company="Neros",
        website="https://n.com",
        us_made_ndaa=True,
        description="American-made NDAA-compliant unmanned aircraft.",
    )
    assert _infer_category(p) == "field-deployed drone"


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
    assert "field-deployed drone" in captured[0]


def test_community_signals_falls_back_to_gear_level_category():
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
