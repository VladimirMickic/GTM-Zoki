"""S3 — fit stage: validated FitResult, deterministic disqualifiers, prompt builder."""
import pytest
from pydantic import ValidationError

from gtm.extract import DroneExtraction
from gtm.fit import FitResult, apply_fit, build_fit_prompt, check_disqualifiers
from gtm.schema import Prospect


def test_fit_score_bounded_0_100():
    FitResult(fit_score=85, fit_reason="strong", best_case_line="AV-Field")
    with pytest.raises(ValidationError):
        FitResult(fit_score=150, fit_reason="x", best_case_line="")
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
    [(85, False, "priority"), (55, False, "keep"), (20, False, "drop"), (85, True, "drop")],
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
