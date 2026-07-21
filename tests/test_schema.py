"""S0: Prospect schema — the contract every stage reads/writes."""
from gtm.schema import Prospect, SHEET_COLUMNS


def test_new_prospect_needs_only_company_and_website():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com")
    assert p.company == "Teal Drones"
    assert p.fit_score is None          # not scored yet
    assert p.drone_models == []          # not extracted yet
    assert p.status == ""                # feedback empty until user grades


def test_sheet_row_matches_locked_column_order():
    assert SHEET_COLUMNS[:3] == ["company", "website", "description"]
    # 2026-07-21: main sheet ends at community_signals — outreach/drafts/qa/source/
    # date/status all moved to the Contacts tab (gtm/output.py::CONTACT_COLUMNS).
    assert SHEET_COLUMNS[-1] == "community_signals"
    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        drone_models=["Black Widow", "Hellcat"],
        fit_score=87,
        source="manual",
    )
    row = p.to_sheet_row()
    assert len(row) == len(SHEET_COLUMNS)
    assert row[0] == "Teal Drones"
    assert row[SHEET_COLUMNS.index("fit_score")] == "87/100"
    # lists are joined for the sheet, not dumped as python repr
    assert row[SHEET_COLUMNS.index("drone_models")] == "Black Widow; Hellcat"


def test_unscored_fit_renders_blank_not_slash_100():
    p = Prospect(company="X", website="https://x.com")
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("fit_score")] == ""


def test_roundtrips_through_json():
    p = Prospect(company="X", website="https://x.com", fit_score=55)
    again = Prospect.model_validate_json(p.model_dump_json())
    assert again == p


def test_schema_splits_dimensions_and_weights():
    # feedback 2026-07-18: dims (L×W×H) drive foam fit; weights alone aren't enough
    assert "drone_sizes" not in SHEET_COLUMNS
    i = SHEET_COLUMNS.index("drone_dimensions")
    assert SHEET_COLUMNS[i + 1] == "drone_weights"
    p = Prospect(
        company="X", website="https://x.com",
        drone_dimensions=["13.7 x 9.8 x 3.5 in folded"],
        drone_weights=["4.26 lbs (1.93 kg)"],
    )
    row = p.to_sheet_row()
    assert row[i] == "13.7 x 9.8 x 3.5 in folded"
    assert row[i + 1] == "4.26 lbs (1.93 kg)"


def test_news_and_signals_render_one_per_line():
    # feedback 2026-07-18: one line per point in the sheet, not run-on "; " strings
    p = Prospect(
        company="X", website="https://x.com",
        key_news=["A — a (url1)", "B — b (url2)"],
        buying_signals=["Signal one — why (src)", "Signal two — why (src)"],
        community_signals=["Reddit thread — hot take (url3)", "X post — reveal (url4)"],
    )
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("key_news")] == "A — a (url1)\nB — b (url2)"
    assert row[SHEET_COLUMNS.index("buying_signals")] == "Signal one — why (src)\nSignal two — why (src)"
    assert row[SHEET_COLUMNS.index("community_signals")] == "Reddit thread — hot take (url3)\nX post — reveal (url4)"


def test_contact_fields_are_state_only_not_on_sheet():
    # sub-project B (2026-07-21): contacts moved to their own Sheet tab/CSV
    # (gtm/output.py::build_contact_rows) — the packed fields stay on Prospect
    # for gtm/draft.py and gtm/hubspot.py, but no longer render on the main row.
    for col in ("contact_name", "contact_title", "contact_linkedin", "contact_emails"):
        assert col not in SHEET_COLUMNS
    p = Prospect(
        company="X", website="https://x.com",
        contact_name="Jane Doe", contact_title="VP Engineering",
        contact_linkedin="https://linkedin.com/in/janedoe",
        contact_emails="jane@x.com (verified)",
    )
    row = p.to_sheet_row()
    assert "Jane Doe" not in row
    assert p.contact_name == "Jane Doe"  # still readable by draft.py/hubspot.py


def test_segment_field_is_state_only_not_on_sheet():
    assert "segment" not in SHEET_COLUMNS
    p = Prospect(company="X", website="https://x.com", segment="defense-ndaa-win")
    assert p.segment == "defense-ndaa-win"


def test_outreach_drafts_qa_status_are_state_only_not_on_main_sheet():
    # 2026-07-21: main sheet = company…community_signals only. outreach_angle,
    # the draft fields, qa_flag, source, date_processed, and status all live on
    # the Contacts tab (gtm/output.py) or in local state, never on the main row.
    for col in (
        "outreach_angle",
        "draft_initial_subject", "draft_initial_body",
        "draft_followup_subject", "draft_followup_body",
        "draft_initial_subject_alt", "draft_initial_body_alt",
        "draft_followup_subject_alt", "draft_followup_body_alt",
        "qa_flag", "source", "date_processed", "status",
    ):
        assert col not in SHEET_COLUMNS

    p = Prospect(
        company="X", website="https://x.com",
        outreach_angle="the hook",
        draft_initial_subject="Case built for the Teal 2?",
        qa_flag="unsupported claim",
        status="priority",
    )
    row = p.to_sheet_row()
    assert "Case built for the Teal 2?" not in row
    # fields still exist on the model for draft.py / hubspot.py / the Contacts tab
    assert p.draft_initial_subject == "Case built for the Teal 2?"
    assert p.qa_flag == "unsupported claim"
    assert p.status == "priority"
