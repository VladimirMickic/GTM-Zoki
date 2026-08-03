# tests/test_budget.py
import pytest

from gtm.budget import score_budget
from gtm.schema import Prospect


def _p(**kw):
    return Prospect(company="X", website="https://x.com/", **kw)


def test_full_marks_for_award_scale_and_capital():
    p = _p(headcount="7000",
           key_news=["Army awards Anduril counter-drone task order (breakingdefense.com)",
                     "Anduril raises $1.5B Series G (techcrunch.com)"])
    points, line = score_budget(p)
    assert points == 20
    assert line.startswith("Budget & procurement 20/20 — [field:")


def test_unknown_everything_scores_zero_not_a_midpoint():
    points, line = score_budget(_p())
    assert points == 0
    assert "none found" in line


# One assertion per regex alternative. The old combined fixtures passed for the wrong
# reason: the award assertion was carried by "task order" and the capital one by "raises",
# so both would still have passed with the `award` and `$...` alternatives deleted.
@pytest.mark.parametrize("headline", [
    "Army awards Teal Drones $12M for SRR Tranche 2 (dronelife.com)",
    "Teal wins Army award (dronelife.com)",
    "Teal awarded an Army deal (dronelife.com)",
    "Teal named a Blue UAS awardee (dronelife.com)",
    "Teal wins Army contract (dronelife.com)",
    "Teal wins two Army contracts (dronelife.com)",
    "Army issues Teal a task order (dronelife.com)",
    "Teal joins the DoD procurement list (dronelife.com)",
    "Bundeswehr framework agreement names Teal (hartpunkt.de)",
    "Teal cleared under NDAA section 848 (dronelife.com)",
    "Teal added to the Blue UAS list (dronelife.com)",
    "Teal issued a NATO stock number (nato.int)",
    "Teal receives type certification (easa.europa.eu)",
    "Teal approved for BVLOS operations (faa.gov)",
])
def test_each_award_alternative_earns_the_procurement_component(headline):
    assert score_budget(_p(key_news=[headline]))[0] >= 8


@pytest.mark.parametrize("headline", [
    "Foo Drones closes $40 million round led by Acme (techcrunch.com)",
    "Foo Drones lands $87M (techcrunch.com)",
    "Foo Drones valued after a $1.5 billion round (techcrunch.com)",
    "Foo Drones raise led by Acme (techcrunch.com)",
    "Foo Drones raised new money (techcrunch.com)",
    "Foo Drones raises new money (techcrunch.com)",
    "Foo Drones raising new money (techcrunch.com)",
    "Foo Drones closes a funding round (techcrunch.com)",
    "Foo Drones closes a seed round (techcrunch.com)",
    "Foo Drones closes a Series C (techcrunch.com)",
])
def test_each_capital_alternative_earns_the_capital_component(headline):
    assert score_budget(_p(key_news=[headline]))[0] >= 5


@pytest.mark.parametrize("headline", [
    "Foo Drones ships a new airframe (dronelife.com)",   # nothing at all
    "Praise for the Foo Drones airframe (dronelife.com)",  # 'praise' is not 'raise'
])
def test_news_without_award_or_capital_evidence_scores_zero(headline):
    assert score_budget(_p(key_news=[headline]))[0] == 0


def test_headcount_bands():
    assert score_budget(_p(headcount="7000"))[0] == 7
    assert score_budget(_p(headcount="51-200"))[0] == 7
    assert score_budget(_p(headcount="25"))[0] == 4
    assert score_budget(_p(headcount="4"))[0] == 1


# LinkedIn's own band labels above 1,000 all carry a thousands separator, and
# _HEADCOUNT_PROMPT asks enrichment to reproduce the source's wording verbatim — so these
# are the formats the enricher actually emits for the largest (best) prospects.
@pytest.mark.parametrize("headcount", ["501-1,000", "1,001-5,000", "5,001-10,000",
                                       "10,001+", "7,000"])
def test_comma_grouped_headcount_bands_score_the_top_band(headcount):
    points, line = score_budget(_p(headcount=headcount))
    assert points == 7
    assert f"headcount {headcount}" in line


def test_compliance_evidence_alone_earns_the_procurement_component():
    assert score_budget(_p(compliance_evidence="NATO stock number 1550-99-123-4567"))[0] == 8


def test_geography_is_not_a_component():
    us = _p(us_made_ndaa=True)
    foreign = _p(compliance_evidence="Bundeswehr framework agreement")
    assert score_budget(us)[0] == score_budget(foreign)[0]
