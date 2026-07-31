# tests/test_budget.py
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


def test_headcount_bands():
    assert score_budget(_p(headcount="7000"))[0] == 7
    assert score_budget(_p(headcount="51-200"))[0] == 7
    assert score_budget(_p(headcount="25"))[0] == 4
    assert score_budget(_p(headcount="4"))[0] == 1


def test_compliance_evidence_alone_earns_the_procurement_component():
    assert score_budget(_p(compliance_evidence="NATO stock number 1550-99-123-4567"))[0] == 8


def test_geography_is_not_a_component():
    us = _p(us_made_ndaa=True)
    foreign = _p(compliance_evidence="Bundeswehr framework agreement")
    assert score_budget(us)[0] == score_budget(foreign)[0]
