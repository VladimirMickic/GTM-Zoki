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
