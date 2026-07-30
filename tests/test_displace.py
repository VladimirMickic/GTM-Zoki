"""New stage: deterministic competitor detection + displacement research prompt."""
from gtm.displace import build_displacement_prompt, detect_competitor, detect_inhouse_case


def test_detect_competitor_named_brand_with_model_number():
    assert detect_competitor("ships in a Pelican 1520 case") == "Pelican 1520"


def test_detect_competitor_named_brand_no_model_number():
    assert detect_competitor("upgraded to a Nanuk case") == "Nanuk"


def test_detect_competitor_case_insensitive():
    assert detect_competitor("ships in a PELICAN case") == "Pelican"


def test_detect_competitor_no_match_on_generic_case():
    assert detect_competitor("ships in a soft backpack") == ""


def test_detect_competitor_empty_evidence():
    assert detect_competitor("") == ""


def test_detect_competitor_explorer_case_brand():
    assert detect_competitor("uses an Explorer Case 5325") == "Explorer Case 5325"


def test_detect_competitor_ignores_ip_rating_as_model_number():
    assert detect_competitor("Pelican case rated IP67") == "Pelican"


def test_detect_competitor_ignores_mil_std_reference_as_model_number():
    assert detect_competitor("uses a Pelican case, MIL-STD-810") == "Pelican"


def test_detect_competitor_ignores_ip_rating_after_branded_case():
    assert detect_competitor("ships in a Pelican-branded case with IP67 seal") == "Pelican"


def test_build_displacement_prompt_names_company_and_competitor():
    prompt = build_displacement_prompt("AeroVironment", "Pelican 1520")
    assert "AeroVironment" in prompt
    assert "Pelican 1520" in prompt
    assert "reddit-find" in prompt
    assert "company-research" in prompt
    assert "competitor_weaknesses" in prompt


# --- 2026-07-28: OEM-built enclosures (drone-in-a-box, docks, own hard case) ---
# Symptom in run data/runs/test-batch-1: Easy Aerial builds its own Drone-in-a-Box
# ground station — the single most important displacement fact — and nothing in the
# pipeline could represent it, because detect_competitor only knows 6 brand names.


def test_detect_inhouse_case_drone_in_a_box():
    assert detect_inhouse_case("The Sparrow ships as a Drone-in-a-Box system") == "drone-in-a-box enclosure"


def test_detect_inhouse_case_hyphenless_drone_in_a_box():
    assert detect_inhouse_case("an autonomous drone in a box solution") == "drone-in-a-box enclosure"


def test_detect_inhouse_case_docking_station():
    assert detect_inhouse_case("recharges inside a weatherproof docking station") == "docking station"


def test_detect_inhouse_case_base_station():
    assert detect_inhouse_case("returns to the ruggedized base station between flights") == "base station enclosure"


def test_detect_inhouse_case_ground_control_station_is_not_an_enclosure():
    # A ground CONTROL station is a controller/laptop, not a housing for the airframe.
    assert detect_inhouse_case("flown from a handheld ground control station") == ""


def test_detect_inhouse_case_self_manufactured_case():
    assert detect_inhouse_case("Every unit ships in our own custom-molded hard case") == "OEM-built case"


def test_detect_inhouse_case_proprietary_case():
    assert detect_inhouse_case("a proprietary transport case designed in house") == "OEM-built case"


def test_detect_inhouse_case_unbranded_included_hard_case():
    assert detect_inhouse_case("includes a hard case") == "OEM-supplied hard case"


def test_detect_inhouse_case_defers_to_a_named_competitor_brand():
    # A Pelican-supplied case is a third-party displacement target, not an OEM build —
    # detect_competitor owns that string.
    assert detect_inhouse_case("includes a Pelican 1520 hard case") == ""


def test_detect_inhouse_case_no_match_on_soft_bag():
    assert detect_inhouse_case("ships in a soft backpack") == ""


def test_detect_inhouse_case_no_match_on_payload_sentence():
    # The exact wrong string case_evidence returned for Easy Aerial in the live run.
    assert detect_inhouse_case("The Sparrow drone is backpack-portable and can carry a 5 lb. payload.") == ""


# 2026-07-29 (us-drone-19 postmortem): detect_inhouse_case returned "" for BOTH
# self-building companies in the run, while Fit independently scored them
# Displacement 14/15. The consequence is silent and expensive — no inhouse_case
# means gtm/segment.py never assigns the displacement segment and gtm/draft.py's
# displacement pitch block never fires, so the highest-value angle only ever
# reaches the email if a human writes it into outreach_angle by hand.


def test_detect_inhouse_case_built_by_the_manufacturer_itself():
    # Cleo Robotics, live case_evidence. "built by the manufacturer itself" is the
    # same claim as "their own case" with the possessive moved after the noun.
    assert detect_inhouse_case(
        'The system ships in a case built by the manufacturer itself, stated as '
        '"Proudly engineered and manufactured in the USA."'
    ) == "OEM-built case"


def test_detect_inhouse_case_built_in_house_after_the_noun():
    assert detect_inhouse_case("The transport case is manufactured in-house") == "OEM-built case"


def test_detect_inhouse_case_sheet_metal_shell_is_an_enclosure():
    # Asylon, live case_evidence. "shell" was missing from the housing-noun list, so
    # a weatherproof metal enclosure the OEM tools itself read as no evidence at all.
    assert detect_inhouse_case(
        "Asylon's drone station technology is built in a weather-proof, stable sheet "
        "metal shell, manufactured with Xometry."
    ) == "OEM-built case"


def test_detect_inhouse_case_generic_transport_case_is_still_no_evidence():
    # Harris Aerial, live case_evidence — a genuine miss that must STAY a miss.
    # "designed to fit in a standard transport case" says nothing about who built it.
    assert detect_inhouse_case('The drones are designed to fit in a "standard transport case."') == ""


def test_detect_inhouse_case_built_by_a_named_competitor_still_defers():
    # The new "built by ..." route must not swallow a third-party build.
    assert detect_inhouse_case("ships in a case built by Pelican for us") == ""


def test_detect_inhouse_case_empty_evidence():
    assert detect_inhouse_case("") == ""


def test_build_displacement_prompt_pitches_tooling_cost_for_an_inhouse_enclosure():
    prompt = build_displacement_prompt("Easy Aerial", "drone-in-a-box enclosure", inhouse=True)
    assert "Easy Aerial" in prompt
    assert "drone-in-a-box enclosure" in prompt
    assert "tooling" in prompt.lower()
    assert "competitor_weaknesses" in prompt
