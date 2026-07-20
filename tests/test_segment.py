from gtm.schema import Prospect
from gtm.segment import assign_segment


def test_ndaa_true_wins_defense_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=True)
    assert assign_segment(p) == "defense-ndaa-win"


def test_ndaa_and_upgrade_evidence_both_present_ndaa_wins():
    # priority order: defense-ndaa-win beats generic-case-upgrade even when both match
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=True, case_evidence="ships in a soft backpack")
    assert assign_segment(p) == "defense-ndaa-win"


def test_soft_case_evidence_gives_upgrade_gap_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="ships in a soft backpack today")
    assert assign_segment(p) == "generic-case-upgrade"


def test_named_rugged_brand_does_not_count_as_upgrade_gap():
    # evidence names an incumbent rugged-case brand alongside upgrade language — excluded
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="upgraded to a soft-sided Pelican-branded case")
    assert assign_segment(p) != "generic-case-upgrade"


def test_launch_signal_gives_new_model_launch_segment():
    p = Prospect(
        company="X", website="https://x.com", us_made_ndaa=False, case_evidence="",
        buying_signals=["Teal launches new Golden Eagle model — expands into mapping (source, 2026-06-01)"],
    )
    assert assign_segment(p) == "new-model-launch"


def test_no_signals_falls_back_to_field_harsh_environment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="", buying_signals=[])
    assert assign_segment(p) == "field-harsh-environment"
