from gtm.persona import classify_persona


def test_c_suite_titles():
    assert classify_persona("CEO") == "c-suite"
    assert classify_persona("VP of Operations") == "c-suite"
    assert classify_persona("Founder & CEO") == "c-suite"


def test_manager_titles():
    assert classify_persona("Director of Logistics") == "manager"
    assert classify_persona("Operations Manager") == "manager"


def test_ic_titles():
    assert classify_persona("Field Technician") == "ic"
    assert classify_persona("Procurement Buyer") == "ic"


def test_unknown_when_empty():
    assert classify_persona("") == "unknown"
    assert classify_persona("   ") == "unknown"
