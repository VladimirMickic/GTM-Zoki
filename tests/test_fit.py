"""S3 — fit stage: validated FitResult, deterministic disqualifiers, prompt builder."""
import pytest
from pydantic import ValidationError

from gtm.extract import DroneExtraction
from gtm.fit import FitResult, apply_fit, build_fit_prompt, check_disqualifiers, evidence_cap
from gtm.schema import Prospect


def test_fit_score_bounded_0_80():
    FitResult(fit_score=75, fit_reason="strong", best_case_line="AV-Field")
    with pytest.raises(ValidationError):
        FitResult(fit_score=81, fit_reason="x", best_case_line="")
    with pytest.raises(ValidationError):
        FitResult(fit_score=-5, fit_reason="x", best_case_line="")


def test_all_weights_under_250g_disqualifies():
    ex = DroneExtraction(drone_models=["NanoFun"], drone_weights=["Weight: 180 g", "0.4 lbs"])
    assert "toy/hobby" in check_disqualifiers(ex)


def test_heavy_drone_not_disqualified():
    ex = DroneExtraction(drone_models=["Teal 2"], drone_weights=["2.75 lbs (1.25 kg)"])
    assert check_disqualifiers(ex) is None


def test_no_weights_found_defers_to_claude():
    ex = DroneExtraction(drone_models=["Mystery"], drone_weights=[])
    assert check_disqualifiers(ex) is None


def test_prompt_contains_icp_and_extraction():
    ex = DroneExtraction(company_description="tactical sUAS", drone_models=["Teal 2"])
    prompt = build_fit_prompt("ICP TEXT HERE", "Teal Drones", ex)
    assert "ICP TEXT HERE" in prompt
    assert "Teal 2" in prompt
    assert "Teal Drones" in prompt
    assert "fit_score" in prompt  # asks for the JSON contract


@pytest.mark.parametrize(
    "score,disqualified,status",
    [(75, False, "priority"), (55, False, "keep"), (20, False, "drop"), (75, True, "drop")],
)
def test_apply_fit_maps_thresholds_to_status(score, disqualified, status):
    p = Prospect(company="X", website="https://x.com")
    fit = FitResult(fit_score=score, fit_reason="r", best_case_line="AV-Field", disqualified=disqualified)
    apply_fit(p, fit)
    assert p.status == status
    assert p.fit_score == score
    assert p.fit_reason == "r"


def test_fit_prompt_includes_dimensions_and_weights():
    from gtm.fit import build_fit_prompt

    ex = DroneExtraction(
        drone_models=["Black Widow"],
        drone_dimensions=["13.7 x 9.8 x 3.5 in folded"],
        drone_weights=["4.26 lbs (1.93 kg)"],
    )
    prompt = build_fit_prompt("ICP TEXT", "Teal Drones", ex)
    assert "13.7 x 9.8 x 3.5 in folded" in prompt
    assert "4.26 lbs (1.93 kg)" in prompt


def test_fit_prompt_demands_one_line_per_criterion_plain_english():
    # feedback 2026-07-18: fit_reason was a dense run-on string
    prompt = build_fit_prompt("ICP TEXT", "X", DroneExtraction())
    assert "one line per" in prompt.lower()
    assert "plain english" in prompt.lower()
    assert "jargon" in prompt.lower()


def test_fit_prompt_shows_case_evidence_or_flags_unknown():
    ex = DroneExtraction(drone_models=["X10"], case_evidence="ships with soft backpack")
    assert "ships with soft backpack" in build_fit_prompt("ICP", "Skydio", ex)
    # unknown after hunting must be visible so the ICP's 3/15 rule can bite
    assert "unknown" in build_fit_prompt("ICP", "Ghost", DroneExtraction()).lower()


from pathlib import Path


def test_icp_uses_displacement_opportunity_not_upgrade_gap():
    text = Path("company/ICP.md").read_text()
    assert "Displacement opportunity" in text
    lowered = text.lower()
    assert "upgrade gap" not in lowered
    assert "upgrade-gap" not in lowered


# --- 2026-07-28: size is the only hard constraint; geography is not a constraint ---
# Live test-batch-1 review found the rubric handed 15 points to every US company and 0
# to every non-US one — a geography bias, not a business signal.


def test_oversize_airframe_is_disqualified():
    # Heavy-lift ag sprayer: nothing this maker publishes fits AV-Convoy (40x24x16 in).
    ex = DroneExtraction(
        drone_models=["AgHawk 60"], drone_dimensions=["58 x 52 x 30 in folded"]
    )
    dq = check_disqualifiers(ex)
    assert dq is not None and "oversize" in dq
    assert "AV-Convoy" in dq


def test_oversize_check_uses_the_smallest_airframe_that_fits():
    # A maker with one huge fixed-wing AND a pocketable quad is still a prospect for
    # the quad — one oversize model must not drop the whole company.
    ex = DroneExtraction(
        drone_models=["Titan", "Sparrow"],
        drone_dimensions=["120 x 90 x 40 in", "13.7 x 9.8 x 3.5 in folded"],
    )
    assert check_disqualifiers(ex) is None


def test_oversize_check_converts_metric_dimensions():
    # 1200 x 900 x 400 mm = 47.2 x 35.4 x 15.7 in — over on two axes.
    ex = DroneExtraction(drone_models=["EU-Lift"], drone_dimensions=["1200 x 900 x 400 mm"])
    assert "oversize" in check_disqualifiers(ex)
    # 500 x 350 x 200 mm = 19.7 x 13.8 x 7.9 in — comfortably inside AV-Field.
    ex_ok = DroneExtraction(drone_models=["EU-Scout"], drone_dimensions=["500 × 350 × 200 mm"])
    assert check_disqualifiers(ex_ok) is None


def test_unitless_dimensions_never_disqualify():
    # "685 x 385 x 175" is almost certainly mm, but if it were inches we'd drop a good
    # prospect on a guess. A false drop is the expensive error — defer to Claude.
    ex = DroneExtraction(drone_models=["Ambiguous"], drone_dimensions=["685 x 385 x 175"])
    assert check_disqualifiers(ex) is None


def test_unfolded_dimensions_are_ignored_for_the_size_bound():
    # The ICP's limit is on the folded/packed footprint; rotors-out span is not it.
    ex = DroneExtraction(
        drone_models=["Osprey"], drone_dimensions=["48 x 48 x 20 in unfolded"]
    )
    assert check_disqualifiers(ex) is None


def test_foreign_manufacturer_is_never_disqualified():
    ex = DroneExtraction(
        company_description="German maker of inspection sUAS",
        drone_weights=["3.1 kg"],
        drone_dimensions=["18 x 12 x 7 in folded"],
        us_made_ndaa=False,
        hq_country="Germany",
    )
    assert check_disqualifiers(ex) is None


def test_fit_prompt_states_geography_is_not_scored():
    ex = DroneExtraction(us_made_ndaa=False, hq_country="Norway")
    prompt = build_fit_prompt("ICP", "NordUAS", ex)
    assert "Geography is NOT a scoring factor" in prompt
    assert "Norway" in prompt
    assert "never deduct" in prompt.lower()


def test_fit_prompt_carries_non_us_compliance_evidence():
    ex = DroneExtraction(compliance_evidence="NATO stock number, Bundeswehr framework")
    prompt = build_fit_prompt("ICP", "NordUAS", ex)
    assert "NATO stock number, Bundeswehr framework" in prompt
    # ...and says so explicitly when there is none, so the 0-3 band can bite.
    assert "none found" in build_fit_prompt("ICP", "X", DroneExtraction())


def test_field_citation_list_excludes_the_python_scored_fields():
    """The [field: ...] citation list must not offer compliance_evidence or us_made_ndaa.

    A citation asserts the score was *derived* from that field, so listing either one
    licenses exactly the behavior the rest of the prompt forbids ("not yours to score ...
    do not mention them here") — and it is the hook Anduril's bogus procurement line hung
    on. Scoped to the citation sentence on purpose: both names legitimately appear earlier
    in the prompt as data fields, which
    test_fit_prompt_carries_non_us_compliance_evidence pins.
    """
    prompt = build_fit_prompt("ICP", "X", DroneExtraction())
    _, sep, tail = prompt.partition("<field name> is the exact field you read it from:")
    assert sep, "citation sentence not found — did the prompt wording change?"
    sentence = tail.split("Plain English only")[0]
    # the enumerated allowlist, i.e. everything before the "none found" fallback clause
    allowlist = sentence.split("— or")[0]
    assert "compliance_evidence" not in allowlist
    assert "us_made_ndaa" not in allowlist
    # the legitimate scrape-phase fields are still offered
    for field in ("description", "drone_models", "drone_dimensions", "drone_weights",
                  "case_evidence"):
        assert field in allowlist
    assert "none found" in sentence
    # naming them is fine — required, even — as long as it is to forbid citing them
    assert "never cite them here" in sentence


def test_icp_scores_procurement_fit_not_us_origin():
    text = Path("company/ICP.md").read_text()
    assert "Budget & procurement" in text
    assert "| US-made / NDAA / defense/gov buyers | 15 |" not in text


# --- 2026-07-31: rubric reweighted 30/25/15/15/15 -> 35/25/20/20, every criterion
# banded, "Volume/price" + "Procurement & compliance fit" merged into one post-enrich
# "Budget & procurement" criterion scored deterministically by gtm/budget.py. ---


def test_icp_fit_scoring_table_has_four_criteria_weighted_35_25_20_20():
    import re

    text = Path("company/ICP.md").read_text()
    labels = [
        "Airframe physically fits a case line",
        "Field-deployed / rugged use case",
        "Displacement opportunity",
        "Budget & procurement",
    ]
    weights = []
    for label in labels:
        assert label in text, f"missing criterion label in company/ICP.md: {label}"
        match = re.search(r"\|\s*" + re.escape(label) + r"\s*\|\s*(\d+)\s*\|", text)
        assert match, f"could not find a weight-table row for: {label}"
        weights.append(int(match.group(1)))
    assert weights == [35, 25, 20, 20]
    assert sum(weights) == 100


def test_no_airframe_identified_caps_the_score_below_priority():
    ex = DroneExtraction(
        company_description="Anduril develops advanced defense technologies, "
                            "including drones, for military applications.",
        drone_models=[],
        drone_dimensions=[],
        drone_weights=["approximately 12 lbs"],
    )
    assert evidence_cap(ex) == 48


def test_a_named_model_lifts_the_cap():
    ex = DroneExtraction(drone_models=["Ghost-X"], drone_dimensions=[])
    assert evidence_cap(ex) is None


def test_apply_fit_clamps_to_the_cap_and_demotes_the_tier():
    p = Prospect(company="Anduril", website="https://www.anduril.com/")
    fit = FitResult(fit_score=78, fit_reason="...", best_case_line="AV-Field")
    apply_fit(p, fit, cap=48)
    assert p.fit_score == 48
    assert p.status == "keep"


# --- 2026-07-31: Anduril run scored 83/100 with "Volume/price" justified by "Anduril is
# an established defense prime" (training data, not a prompt field) and a 12-15
# "Procurement" score whose own text admitted "no specific named certification found" —
# the band it claimed requires one. The prompt must ban prior knowledge and demand every
# scored line cite the field it came from. ---


def test_prompt_bans_prior_knowledge_and_demands_field_citations():
    prompt = build_fit_prompt("ICP TEXT", "Anduril", DroneExtraction())
    lowered = prompt.lower()
    assert "not evidence" in lowered
    assert "already know" in lowered
    assert "[field:" in prompt
    # 80-point scale: budget is scored later, in Python
    assert "80" in prompt
    assert "Budget & procurement" not in prompt


# --- fix round 1: the geography paragraph (preserved "verbatim" out of A3) still routed
# us_made_ndaa into "Procurement & compliance fit"'s 12-15 band — a criterion Task A1
# deleted, and that the tail three lines later explicitly forbids scoring or mentioning.
# Rewritten to drop the deleted-criterion routing while keeping geography-neutrality in
# force. This test locks both halves of that fix in place. ---


def test_prompt_geography_paragraph_does_not_name_a_deleted_criterion():
    prompt = build_fit_prompt("ICP TEXT", "NordUAS", DroneExtraction())
    assert "Procurement & compliance" not in prompt
    lowered = prompt.lower()
    assert "geography" in lowered
    assert "not a scoring factor" in lowered
