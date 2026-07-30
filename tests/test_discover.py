"""S7a — discover: NL query → Serper → gpt-4o-mini filter → real manufacturers only."""
from gtm.discover import CandidateList, discover, region_query

SERP = [
    {"title": "Teal Drones — Military sUAS", "link": "https://tealdrones.com/", "snippet": "US maker of tactical drones"},
    {"title": "Top 10 drone companies 2026", "link": "https://blog.example.com/top10", "snippet": "listicle"},
    {"title": "Skydio | Autonomous Drones", "link": "https://www.skydio.com/products", "snippet": "US drone manufacturer"},
    {"title": "Teal Drones shop", "link": "https://tealdrones.com/shop", "snippet": "dup domain"},
]


class FakeClient:
    def __init__(self, parsed):
        self._parsed = parsed
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        parsed = self._parsed

        class Msg:
            pass

        Msg.parsed = parsed
        Msg.refusal = None

        class Choice:
            message = Msg()
            finish_reason = "stop"

        class Usage:
            prompt_tokens = 50
            completion_tokens = 10

        class Completion:
            choices = [Choice()]
            usage = Usage()

        return Completion()


FILTERED = CandidateList(
    candidates=[
        {"company": "Teal Drones", "website": "https://tealdrones.com/", "is_manufacturer": True},
        {"company": "Example Blog", "website": "https://blog.example.com/top10", "is_manufacturer": False},
        {"company": "Skydio", "website": "https://www.skydio.com/products", "is_manufacturer": True},
        {"company": "Teal Drones", "website": "https://tealdrones.com/shop", "is_manufacturer": True},
    ]
)


def test_discover_keeps_only_manufacturers_deduped_by_domain():
    got = discover("drone makers", search=lambda q, num=10: SERP, client=FakeClient(FILTERED))
    assert [(c.company, c.website) for c in got] == [
        ("Teal Drones", "https://tealdrones.com/"),
        ("Skydio", "https://www.skydio.com/products"),
    ]


def test_discover_respects_cap():
    got = discover("drone makers", max_companies=1, search=lambda q, num=10: SERP, client=FakeClient(FILTERED))
    assert len(got) == 1


def test_discover_empty_serp():
    assert discover("nothing", search=lambda q, num=10: [], client=FakeClient(CandidateList(candidates=[]))) == []


def test_discover_scales_serper_num_to_max_companies():
    captured = {}

    def spy_search(q, num=10):
        captured["num"] = num
        return SERP

    discover("drone makers", max_companies=5, search=spy_search, client=FakeClient(FILTERED))
    assert captured["num"] == 20


def test_filter_prompt_flags_reseller_and_dealer_cues():
    # discover-1 leak 2026-07-18: Advexure/Drone Nerds/LE Drones (dealers) passed the filter
    from gtm.discover import FILTER_PROMPT

    low = FILTER_PROMPT.lower()
    for cue in ("reseller", "dealer", "brands", "shop"):
        assert cue in low, f"prompt missing reseller cue: {cue}"


def test_discover_drops_denylisted_domains():
    marked_true = CandidateList(
        candidates=[
            {"company": "Advexure", "website": "https://advexure.com/pages/x", "is_manufacturer": True},
            {"company": "Skydio", "website": "https://www.skydio.com/", "is_manufacturer": True},
        ]
    )
    serp = [{"title": "t", "link": "https://x.com", "snippet": "s"}]
    got = discover(
        "q", search=lambda q, num=10: serp, client=FakeClient(marked_true),
        denylist={"advexure.com"},
    )
    assert [c.company for c in got] == ["Skydio"]  # denylist beats the LLM's opinion


def test_load_denylist_parses_domains_ignoring_prose(tmp_path):
    from gtm.discover import load_denylist

    f = tmp_path / "denylist.md"
    f.write_text(
        "# Denylist\n"
        "Domains discover() must never emit.\n"
        "\n"
        "- advexure.com — reseller (discover-1, 2026-07-18)\n"
        "- enterprise.dronenerds.com — reseller\n"
        "- www.ledrones.org — reseller\n"
    )
    assert load_denylist(f) == {"advexure.com", "enterprise.dronenerds.com", "ledrones.org"}


def test_load_denylist_missing_file_is_empty(tmp_path):
    from gtm.discover import load_denylist

    assert load_denylist(tmp_path / "nope.md") == set()


def test_filter_prompt_requires_company_own_domain_not_articles():
    # discover-2 leak 2026-07-18: news article about Red Cat passed with the news site's URL
    from gtm.discover import FILTER_PROMPT

    low = FILTER_PROMPT.lower()
    assert "own domain" in low
    assert "about" in low


def test_discover_drops_candidates_whose_name_is_absent_from_domain():
    # discover-3 leak 2026-07-18: "Skydio" passed with a blog listicle URL
    marked = CandidateList(
        candidates=[
            {"company": "Skydio", "website": "https://abjacademy.global/drone-blog/top-us/", "is_manufacturer": True},
            {"company": "BRINC", "website": "https://brincdrones.com/", "is_manufacturer": True},
            {"company": "Teal Drones", "website": "https://tealdrones.com/", "is_manufacturer": True},
            {"company": "Red Cat Holdings", "website": "https://redcat.red/", "is_manufacturer": True},
        ]
    )
    serp = [{"title": "t", "link": "https://x.com", "snippet": "s"}]
    got = discover("q", search=lambda q, num=10: serp, client=FakeClient(marked), denylist=set())
    # Skydio's URL is someone else's site; the other three match their own domains
    assert [c.company for c in got] == ["BRINC", "Teal Drones", "Red Cat Holdings"]


def test_name_matches_domain_accepts_a_short_name_that_is_the_domain_label():
    """The >=4-char rule silently dropped every maker whose distinctive token is short:
    "AAI Corporation" at aai.com produced candidates {corporation, aaicorporation} and
    matched nothing. Substring-matching a 3-char token against the whole domain would
    fire on anything, so a short token has to BE the domain's own label."""
    from gtm.discover import _name_matches_domain

    assert _name_matches_domain("AAI Corporation", "aai.com")
    assert _name_matches_domain("SES Drones", "ses.com")
    assert _name_matches_domain("XAG", "xag.com")  # already worked, via the joined form


def test_name_matches_domain_short_token_must_be_the_label_not_a_substring():
    from gtm.discover import _name_matches_domain

    # a listicle's "US" must not claim a .us domain, nor "ses" claim sesame.com
    assert not _name_matches_domain("US Drone Makers", "dronelife.us")
    assert not _name_matches_domain("SES Drones", "sesame.com")
    assert not _name_matches_domain("Skydio", "abjacademy.global")


def test_discover_keeps_a_short_named_maker():
    marked = CandidateList(
        candidates=[
            {"company": "AAI Corporation", "website": "https://aai.com/", "is_manufacturer": True},
            {"company": "Top US Drones", "website": "https://dronelife.us/list", "is_manufacturer": True},
        ]
    )
    serp = [{"title": "t", "link": "https://x.com", "snippet": "s"}]
    got = discover("q", search=lambda q, num=10: serp, client=FakeClient(marked), denylist=set())
    assert [c.company for c in got] == ["AAI Corporation"]


def test_discover_does_not_narrow_to_us_by_default():
    seen = []

    def fake_search(q, num=10):
        seen.append(q)
        return []

    discover("drone manufacturers", 5, search=fake_search, denylist=set())
    assert seen == ["drone manufacturers"]


def test_require_us_narrows_the_search_query():
    seen = []

    def fake_search(q, num=10):
        seen.append(q)
        return []

    discover("drone manufacturers", 5, search=fake_search, denylist=set(), require_us=True)
    assert "NDAA" in seen[0]
    assert seen[0].startswith("drone manufacturers")


def test_require_us_does_not_double_up_an_already_ndaa_query():
    seen = []

    def fake_search(q, num=10):
        seen.append(q)
        return []

    discover("NDAA drone makers", 5, search=fake_search, denylist=set(), require_us=True)
    assert seen == ["NDAA drone makers"]


# 2026-07-30: a missing region used to stop the run and cost a user question. It now
# falls back to Brief.region (default "us") and only shapes the query — same credit.


def test_region_query_appends_the_spelled_out_region():
    assert region_query("drone manufacturer", "us") == "drone manufacturer United States"
    assert region_query("drone manufacturer", "uk") == "drone manufacturer United Kingdom"


def test_region_query_passes_an_unknown_region_through_verbatim():
    assert region_query("drone maker", "Nordics") == "drone maker Nordics"


def test_region_query_is_a_no_op_when_the_query_already_says_it():
    assert region_query("United States drone maker", "us") == "United States drone maker"


def test_region_query_skips_us_when_require_us_already_narrowed_the_search():
    """Stacking the NDAA clause and 'United States' over-constrains the SERP."""
    assert region_query("drone maker", "us", require_us=True) == "drone maker"


def test_region_query_is_a_no_op_for_a_worldwide_run():
    assert region_query("drone maker", "") == "drone maker"


def test_discover_searches_the_region_scoped_query():
    seen = {}

    def search(query, num=10):
        seen["q"] = query
        return []

    discover("drone manufacturer", 3, search=search, region="uk", denylist=set())
    assert seen["q"] == "drone manufacturer United Kingdom"
