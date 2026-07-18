"""S7a — discover: NL query → Serper → gpt-4o-mini filter → real manufacturers only."""
from gtm.discover import CandidateList, discover

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
