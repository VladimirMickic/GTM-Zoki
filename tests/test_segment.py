from gtm.schema import Prospect
from gtm.segment import assign_segment


def test_ndaa_true_alone_gives_procurement_compliance_win():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=True)
    assert assign_segment(p) == "procurement-compliance-win"


def test_soft_case_evidence_gives_upgrade_gap_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="ships in a soft backpack today")
    assert assign_segment(p) == "generic-case-upgrade"


def test_named_competitor_brand_gives_displacement_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="upgraded to a soft-sided Pelican-branded case")
    assert assign_segment(p) == "competitor-displacement"


def test_launch_signal_gives_new_model_launch_segment():
    p = Prospect(
        company="X", website="https://x.com", us_made_ndaa=False, case_evidence="",
        buying_signals=["Teal launches new Golden Eagle model — expands into mapping (source, 2026-06-01)"],
    )
    assert assign_segment(p) == "new-model-launch"


def test_no_signals_falls_back_to_field_harsh_environment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=False, case_evidence="", buying_signals=[])
    assert assign_segment(p) == "field-harsh-environment"


# --- 2026-07-28: the compliance short-circuit no longer starves the other branches ---
# Symptom in run data/runs/test-batch-1: assign_segment checked us_made_ndaa FIRST and
# returned, so every qualified prospect (NDAA compliance is near-universal in this ICP)
# landed in one bucket and the drafts read near-identically.


def test_competitor_beats_compliance_win_when_both_match():
    p = Prospect(
        company="X", website="https://x.com", us_made_ndaa=True,
        case_evidence="ships in a Pelican 1520 case",
    )
    assert assign_segment(p) == "competitor-displacement"


def test_generic_case_upgrade_beats_compliance_win_when_both_match():
    p = Prospect(
        company="X", website="https://x.com", us_made_ndaa=True,
        case_evidence="ships in a soft backpack",
    )
    assert assign_segment(p) == "generic-case-upgrade"


def test_new_model_launch_beats_compliance_win_when_both_match():
    p = Prospect(
        company="X", website="https://x.com", us_made_ndaa=True, case_evidence="",
        buying_signals=["Red Cat unveils the Black Widow 2 (source, 2026-05-02)"],
    )
    assert assign_segment(p) == "new-model-launch"


def test_ndaa_true_batch_does_not_collapse_into_one_segment():
    # The live symptom, as an assertion: three NDAA-compliant makers with different
    # case/launch evidence must land in three different buckets, not one.
    batch = [
        Prospect(company="A", website="https://a.com", us_made_ndaa=True, case_evidence="ships in a Pelican 1520"),
        Prospect(company="B", website="https://b.com", us_made_ndaa=True, case_evidence="ships in a soft case"),
        Prospect(company="C", website="https://c.com", us_made_ndaa=True, case_evidence=""),
    ]
    assert len({assign_segment(p) for p in batch}) == 3


def test_non_us_compliance_evidence_reaches_the_compliance_segment():
    # Geography-neutral (Slice 1): a NATO/MoD credential is the same hook as NDAA.
    p = Prospect(
        company="X", website="https://x.com", us_made_ndaa=False,
        compliance_evidence="NATO stock number; Norwegian MoD framework agreement",
    )
    assert assign_segment(p) == "procurement-compliance-win"


def test_compliance_segment_name_carries_no_us_program_wording():
    # The segment string is interpolated straight into the draft prompt; an
    # "ndaa" label pushed US program language onto non-US prospects.
    p = Prospect(company="X", website="https://x.com", compliance_evidence="EASA type certificate")
    assert "ndaa" not in assign_segment(p).lower()


def test_blank_compliance_evidence_does_not_trigger_the_compliance_segment():
    p = Prospect(company="X", website="https://x.com", us_made_ndaa=None, compliance_evidence="   ")
    assert assign_segment(p) == "field-harsh-environment"


def test_inhouse_enclosure_gives_oem_displacement_segment():
    p = Prospect(
        company="Easy Aerial", website="https://easyaerial.com", us_made_ndaa=True,
        case_evidence="The Sparrow ships as a Drone-in-a-Box system with a weatherproof enclosure",
    )
    assert assign_segment(p) == "oem-inhouse-displacement"


def test_inhouse_enclosure_beats_generic_case_upgrade():
    # "backpack" also matches the generic-upgrade keywords; the OEM build is the
    # more specific (and harder, higher-value) pitch.
    p = Prospect(
        company="X", website="https://x.com",
        case_evidence="backpack-portable, and the system docks in our own custom-molded hard case",
    )
    assert assign_segment(p) == "oem-inhouse-displacement"


def test_named_competitor_still_beats_inhouse_enclosure():
    p = Prospect(
        company="X", website="https://x.com",
        case_evidence="the drone-in-a-box unit ships with a Pelican 1520",
    )
    assert assign_segment(p) == "competitor-displacement"
