"""Evidence hunt: when the site doesn't publish dims/case info, search the wider web
(feedback 2026-07-18 — our cases can't fit huge military drones, so dims matter pre-fit)."""
from gtm.spechunt import SpecFindings, build_spec_queries, hunt_specs


def test_queries_target_dimensions_and_case_evidence():
    qs = build_spec_queries("Skydio", ["Skydio X10", "Skydio R10"])
    assert len(qs) == 2
    dims_q, case_q = qs
    assert "Skydio X10" in dims_q and "dimensions" in dims_q
    assert "Skydio" in case_q
    for cue in ("case", "unboxing"):
        assert cue in case_q
    # more than one model: query the first (flagship) only, keep credits bounded
    assert "R10" not in dims_q


def test_queries_fall_back_to_company_when_no_models():
    dims_q, _ = build_spec_queries("BRINC", [])
    assert "BRINC" in dims_q and "dimensions" in dims_q


class FakeClient:
    def __init__(self, parsed):
        self._parsed = parsed
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        self.last_kwargs = kwargs

        class Msg:
            parsed = self._parsed
            refusal = None

        class Choice:
            message = Msg()

        class Usage:
            prompt_tokens = 80
            completion_tokens = 20

        class Completion:
            choices = [Choice()]
            usage = Usage()

        return Completion()


def test_hunt_specs_extracts_findings_from_serp_snippets():
    findings = SpecFindings(
        drone_dimensions=["X10: 13.7 x 9.8 x 4.6 in folded"],
        drone_weights=["4.66 lbs (2.11 kg)"],
        case_evidence="ships with a soft backpack; hard case sold separately",
    )
    serp = [{"title": "X10 specs", "link": "https://x.com", "snippet": "Folded: 13.7 x 9.8 x 4.6 in"}]
    got = hunt_specs(
        "Skydio", ["Skydio X10"],
        search=lambda q, num=10: serp,
        client=FakeClient(findings),
    )
    assert got.drone_dimensions == ["X10: 13.7 x 9.8 x 4.6 in folded"]
    assert "backpack" in got.case_evidence


def test_hunt_specs_empty_serps_return_empty_findings_without_llm_call():
    calls = []
    got = hunt_specs(
        "Ghost", [],
        search=lambda q, num=10: [],
        client=None,  # would crash if the LLM were called
    )
    assert got == SpecFindings()


def test_hunt_specs_drops_blank_entries_from_findings():
    # live freefly run 2026-07-18: mini returned ['', ''] which reads as "found"
    dirty = SpecFindings(drone_dimensions=["", " "], drone_weights=["", "4.6 lbs"])
    serp = [{"title": "t", "link": "https://x.com", "snippet": "s"}]
    got = hunt_specs("X", [], search=lambda q, num=10: serp, client=FakeClient(dirty))
    assert got.drone_dimensions == []
    assert got.drone_weights == ["4.6 lbs"]
