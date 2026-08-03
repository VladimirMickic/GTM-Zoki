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


# --- 2026-08-03, follow-ups 2 and 3. Both regexes were widened on 2026-08-02 and both
# widenings brought a false-positive class with them: `$Nm/bn` also matches a market-size
# headline, and bare `award` also matches an industry award. Neither is evidence that this
# company can pay for or procure anything, and each is worth 5 and 8 points respectively.
#
# Both guards are per-news-item, not per-blob: score_budget used to join key_news into one
# string, so a market-size headline in slot 3 could hand capital points to a company whose
# only other news was unrelated. ---


@pytest.mark.parametrize("headline", [
    "Drone market to hit $12 billion by 2030 (marketwatch.com)",
    "Global counter-UAS market worth $4.5 billion, report says (globenewswire.com)",
    "Commercial drone industry projected to reach $58 billion (forbes.com)",
    "Analysts size the sUAS sector at $9.2 billion (marketsandmarkets.com)",
])
def test_a_market_size_headline_is_not_a_capital_event(headline):
    assert score_budget(_p(key_news=[headline]))[0] == 0


def test_a_market_size_headline_does_not_lend_capital_points_to_other_news():
    # The per-blob bug: the airframe item carries no evidence at all, and the market item
    # is about the industry, not this company. Together they must still score 0.
    p = _p(key_news=["Foo Drones ships a new airframe (dronelife.com)",
                     "Drone market to hit $12 billion by 2030 (marketwatch.com)"])
    assert score_budget(p)[0] == 0


def test_a_real_raise_in_the_same_list_as_a_market_headline_still_scores():
    # The guard vetoes the market item, not the list.
    p = _p(key_news=["Drone market to hit $12 billion by 2030 (marketwatch.com)",
                     "Foo Drones lands $87M (techcrunch.com)"])
    assert score_budget(p)[0] == 5


@pytest.mark.parametrize("headline", [
    "Foo Drones wins an Edison Award (prnewswire.com)",
    "Foo Drones named a finalist for the Innovation Award (suasnews.com)",
    "Foo Drones takes home a Best of CES award (theverge.com)",
    "Award-winning Foo Drones unveils its new airframe (dronelife.com)",
    "Foo Drones shortlisted in the 2026 Awards season (dronelife.com)",
])
def test_an_industry_award_is_not_procurement_evidence(headline):
    assert score_budget(_p(key_news=[headline]))[0] == 0


def test_a_real_procurement_award_in_the_same_list_as_a_trophy_still_scores():
    # 13, not 8: the "$12M" also clears _CAPITAL_RE. That is pre-existing and deliberate —
    # a named eight-figure defence contract is evidence of procurement capacity twice over
    # — and it is not what the trophy veto is about. The assertion that matters here is
    # that the Edison item did not cost the real one its procurement points.
    p = _p(key_news=["Foo Drones wins an Edison Award (prnewswire.com)",
                     "Army awards Foo Drones $12M for SRR Tranche 2 (dronelife.com)"])
    assert score_budget(p)[0] == 13
    assert score_budget(_p(key_news=[p.key_news[0]]))[0] == 0  # the trophy alone is worth 0


def test_a_contract_award_is_not_vetoed_by_a_trophy_word_in_the_same_headline():
    # The veto applies to the weak bare-`award` branch only. A headline naming a real
    # contract keeps its points even when it also mentions a trophy.
    p = _p(key_news=["Award-winning Foo Drones wins an Army contract (dronelife.com)"])
    assert score_budget(p)[0] == 8
