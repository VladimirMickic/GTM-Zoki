from gtm.persona import classify_persona, distinct_tiers_present
from gtm.schema import CONTACT_FIELD_SEP


def test_c_suite_titles():
    assert classify_persona("CEO") == "c-suite"
    assert classify_persona("VP of Operations") == "c-suite"
    assert classify_persona("Founder & CEO") == "c-suite"


def test_finance_titles():
    assert classify_persona("CFO") == "finance"
    assert classify_persona("Chief Financial Officer") == "finance"
    assert classify_persona("Controller") == "finance"
    assert classify_persona("VP of Finance") == "finance"  # finance beats generic vp


def test_director_titles():
    assert classify_persona("Director of Logistics") == "director"
    assert classify_persona("Head of Operations") == "director"


def test_manager_titles():
    assert classify_persona("Operations Manager") == "manager"
    assert classify_persona("Program Manager") == "manager"


def test_ic_titles():
    assert classify_persona("Field Technician") == "ic"
    assert classify_persona("Procurement Buyer") == "ic"


def test_unknown_when_empty():
    assert classify_persona("") == "unknown"
    assert classify_persona("   ") == "unknown"


def test_distinct_tiers_present_dedupes_same_tier():
    # real AeroVironment titles (2026-07-21 handoff) — both classify c-suite
    titles = CONTACT_FIELD_SEP.join(["Vice President and Chief Technologist", "VP Logistics Operations"])
    assert distinct_tiers_present(titles) == ["c-suite"]


def test_distinct_tiers_present_keeps_distinct_tiers_in_order():
    titles = CONTACT_FIELD_SEP.join(["Vice President and Chief Technologist", "Senior Director International Sales"])
    assert distinct_tiers_present(titles) == ["c-suite", "director"]


def test_distinct_tiers_present_blank_titles_default_to_unknown():
    assert distinct_tiers_present("") == ["unknown"]
