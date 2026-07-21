"""New stage: deterministic competitor detection + displacement research prompt."""
from gtm.displace import build_displacement_prompt, detect_competitor


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
