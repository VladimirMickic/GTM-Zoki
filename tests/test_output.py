"""S6 — output: CSV in SHEET_COLUMNS order + Sheet push (gspread faked)."""
import csv

from gtm.output import (
    CONTACT_COLUMNS,
    _open_worksheet,
    build_contact_rows,
    push_contacts_to_sheet,
    push_to_sheet,
    write_contacts_csv,
    write_csv,
)
from gtm.schema import DraftSet, SHEET_COLUMNS, Prospect

TEAL = Prospect(
    company="Teal Drones",
    website="https://tealdrones.com",
    drone_models=["Teal 2", "Black Widow"],
    fit_score=87,
    status="priority",
)

MULTI = Prospect(
    company="Teal Drones",
    website="https://tealdrones.com",
    source="serper",
    date_processed="2026-07-21",
    status="priority",
    contact_name="Blake Resnick; Manoj Mohan; Steven Butler",
    contact_title="CEO; VP Engineering; Field Technician",
    contact_linkedin=(
        "https://linkedin.com/in/blake; "
        "https://linkedin.com/in/manoj; "
        "https://linkedin.com/in/steven"
    ),
    contact_emails="blake@tealdrones.com (verified); manoj@tealdrones.com (risky); -",
    outreach_angle="Teal's SRR win shows momentum in defense — AeroVault's NDAA case fits their next RFP cycle.",
    drafts_by_tier={
        # CEO + VP Engineering both classify c-suite (gtm/persona.py); Field
        # Technician classifies ic — two distinct draft sets, not a shared one.
        "c-suite": DraftSet(
            pain_points="Damaged units eat into margin | slow RFP turnaround",
            talking_points="MIL-STD-810H drop rating | US-made, matches Teal's own NDAA angle",
            initial_subject="Case built for the Teal 2?",
            initial_body="{FIRST_NAME} — saw Teal's SRR win.",
            qa_flag="passed",
        ),
        "ic": DraftSet(
            pain_points="Field gear takes a beating",
            talking_points="Foam insert sized to the Teal 2 | faster swap in the field",
            initial_subject="Field kit for the Teal 2?",
            initial_body="{FIRST_NAME} — Teal's SRR win means more units in the field.",
            qa_flag="passed",
        ),
    },
)


def test_write_csv_header_and_row(tmp_path):
    path = tmp_path / "out.csv"
    write_csv([TEAL], path)
    rows = list(csv.reader(path.open()))
    assert rows[0] == SHEET_COLUMNS
    assert rows[1][SHEET_COLUMNS.index("company")] == "Teal Drones"
    assert rows[1][SHEET_COLUMNS.index("drone_models")] == "Teal 2; Black Widow"
    assert rows[1][SHEET_COLUMNS.index("fit_score")] == "87/100"


def test_write_csv_includes_all_tiers_including_drops(tmp_path):
    # 2026-07-21 (user): main sheet is the full funnel — Tier 1/2/3. Dropped
    # (Tier 3) companies now appear too, tagged tier "3" via the tier column.
    dropped = TEAL.model_copy(update={"company": "BadCo", "status": "drop", "fit_score": 12})
    path = tmp_path / "out.csv"
    write_csv([TEAL, dropped], path)
    rows = list(csv.reader(path.open()))
    body = path.read_text()
    assert "Teal Drones" in body
    assert "BadCo" in body
    badco = next(r for r in rows if r[SHEET_COLUMNS.index("company")] == "BadCo")
    assert badco[SHEET_COLUMNS.index("tier")] == "3"


class FakeWorksheet:
    def __init__(self):
        self.appended = []
        self.values = []

    def get_all_values(self):
        return self.values

    def append_rows(self, rows, value_input_option="RAW"):
        self.appended.extend(rows)


def test_push_to_sheet_writes_header_once_then_rows():
    ws = FakeWorksheet()
    n = push_to_sheet([TEAL], worksheet=ws)
    assert n == 1
    assert ws.appended[0] == SHEET_COLUMNS
    assert ws.appended[1][0] == "Teal Drones"

    ws2 = FakeWorksheet()
    ws2.values = [SHEET_COLUMNS]  # header already present
    push_to_sheet([TEAL], worksheet=ws2)
    assert ws2.appended[0][0] == "Teal Drones"  # no duplicate header


def test_push_to_sheet_includes_dropped_tier3_rows():
    ws = FakeWorksheet()
    dropped = TEAL.model_copy(update={"company": "BadCo", "status": "drop", "fit_score": 12})
    n = push_to_sheet([TEAL, dropped], worksheet=ws)
    assert n == 2
    pushed = [r[SHEET_COLUMNS.index("company")] for r in ws.appended[1:]]
    assert "BadCo" in pushed


def test_push_to_sheet_writes_header_on_blank_but_nonempty_values():
    # a brand-new Google Sheet can return a row of blank cells (not []) from
    # get_all_values() — must still be treated as "needs header", not "has header"
    ws = FakeWorksheet()
    ws.values = [[""]]
    push_to_sheet([TEAL], worksheet=ws)
    assert ws.appended[0] == SHEET_COLUMNS
    assert ws.appended[1][0] == "Teal Drones"


def test_push_to_sheet_skips_rows_whose_domain_already_present():
    # feedback 2026-07-24: append-only sheet + manual clear ritual is error-prone
    ws = FakeWorksheet()
    ws.values = [SHEET_COLUMNS, ["Teal Drones", "https://tealdrones.com"] + [""] * (len(SHEET_COLUMNS) - 2)]
    n = push_to_sheet([TEAL], worksheet=ws)
    assert n == 0
    assert ws.appended == []


def test_push_to_sheet_domain_dedupe_ignores_scheme_www_and_trailing_slash():
    ws = FakeWorksheet()
    ws.values = [SHEET_COLUMNS, ["Teal Drones", "www.tealdrones.com/"] + [""] * (len(SHEET_COLUMNS) - 2)]
    n = push_to_sheet([TEAL], worksheet=ws)
    assert n == 0


def test_push_to_sheet_still_pushes_new_domains_alongside_existing():
    ws = FakeWorksheet()
    ws.values = [SHEET_COLUMNS, ["Teal Drones", "https://tealdrones.com"] + [""] * (len(SHEET_COLUMNS) - 2)]
    fresh = TEAL.model_copy(update={"company": "NewCo", "website": "https://newco.com"})
    n = push_to_sheet([TEAL, fresh], worksheet=ws)
    assert n == 1
    assert ws.appended[0][SHEET_COLUMNS.index("company")] == "NewCo"


def test_push_contacts_to_sheet_skips_rows_with_existing_email():
    ws = FakeWorksheet()
    existing_row = [""] * len(CONTACT_COLUMNS)
    existing_row[CONTACT_COLUMNS.index("company")] = "Teal Drones"
    existing_row[CONTACT_COLUMNS.index("contact_email")] = "blake@tealdrones.com"
    ws.values = [CONTACT_COLUMNS, existing_row]
    n = push_contacts_to_sheet([MULTI], worksheet=ws)
    # Blake (email match) skipped; Manoj + Steven (no prior email match) still pushed
    assert n == 2
    pushed_names = [r[CONTACT_COLUMNS.index("contact_name")] for r in ws.appended]
    assert "Blake Resnick" not in pushed_names
    assert "Manoj Mohan" in pushed_names


def test_contact_columns_locked_order():
    # 2026-07-21 (user layout): drafts live on the Contacts tab again; source/status
    # dropped. One row per contact; company-level cells (outreach_angle, drafts,
    # date_processed) repeat on every contact row.
    assert CONTACT_COLUMNS == [
        "company",
        "contact_name",
        "contact_title",
        "contact_linkedin",
        "contact_email",
        "email_status",
        "outreach_angle",
        "pain_points",
        "talking_points",
        "draft_initial_subject",
        "draft_initial_body",
        "needs_research",
        "qa_flag",
        "date_processed",
    ]


def test_open_worksheet_default_name_is_companies():
    # main tab must match the user's existing "Companies" sheet tab (exact
    # case — gspread's worksheet() lookup is case-sensitive) — never gspread's
    # generic default "Sheet1" (2026-07-21: a run pushed to "Sheet1" instead).
    import inspect

    assert inspect.signature(_open_worksheet).parameters["name"].default == "Companies"


def test_build_contact_rows_keeps_all_contacts_including_email_miss():
    rows = build_contact_rows(MULTI)
    assert len(rows) == 3
    assert [r["contact_name"] for r in rows] == ["Blake Resnick", "Manoj Mohan", "Steven Butler"]
    assert rows[0]["contact_email"] == "blake@tealdrones.com"
    assert rows[0]["email_status"] == "verified"
    assert rows[1]["contact_email"] == "manoj@tealdrones.com"
    assert rows[1]["email_status"] == "risky"
    assert rows[2]["contact_email"] == ""
    assert rows[2]["email_status"] == "miss"


def test_build_contact_rows_company_level_fields_repeat_on_every_row():
    # 2026-07-21 (user layout): company-level fields (company, outreach_angle,
    # the four draft cells, date_processed) repeat on every contact row so each
    # row is self-contained. source/status are no longer on this tab.
    rows = build_contact_rows(MULTI)
    for r in rows:
        assert r["company"] == "Teal Drones"
        assert r["outreach_angle"] == MULTI.outreach_angle
        assert r["date_processed"] == "2026-07-21"
        assert "source" not in r
        assert "status" not in r
    # per-contact fields still differ row to row
    assert [r["contact_title"] for r in rows] == ["CEO", "VP Engineering", "Field Technician"]


def test_build_contact_rows_picks_draft_matching_each_contacts_persona_tier():
    # c-suite (Blake: CEO, Manoj: VP Engineering) gets the c-suite draft;
    # ic (Steven: Field Technician) gets its own distinct draft — not the same
    # email for every contact, per the persona-tiered drafts design.
    rows = build_contact_rows(MULTI)
    assert rows[0]["draft_initial_subject"] == "Case built for the Teal 2?"  # Blake, CEO -> c-suite
    assert rows[1]["draft_initial_subject"] == "Case built for the Teal 2?"  # Manoj, VP Eng -> c-suite
    assert rows[2]["draft_initial_subject"] == "Field kit for the Teal 2?"   # Steven, Field Tech -> ic
    assert rows[0]["qa_flag"] == "passed"
    assert rows[2]["qa_flag"] == "passed"


def test_build_contact_rows_carries_pain_points_talking_points_and_needs_research():
    # 2026-07-25: pain_points/talking_points are the primary deliverable, and
    # the fact-check result (qa_flag) must be visible on the Contacts tab —
    # never dropped silently.
    rows = build_contact_rows(MULTI)
    assert rows[0]["pain_points"] == "Damaged units eat into margin | slow RFP turnaround"
    assert rows[0]["talking_points"] == "MIL-STD-810H drop rating | US-made, matches Teal's own NDAA angle"
    assert rows[0]["needs_research"] == "no"
    assert rows[0]["qa_flag"] == "passed"


def test_build_contact_rows_needs_research_yes_when_tier_has_no_draft():
    p = MULTI.model_copy(update={
        "drafts_by_tier": {
            "c-suite": DraftSet(pain_points="thin signal pain", talking_points="thin signal talk", needs_research=True, qa_flag="n/a — talking-points only, signal too thin to draft a specific email"),
            "ic": MULTI.drafts_by_tier["ic"],
        }
    })
    rows = build_contact_rows(p)
    assert rows[0]["needs_research"] == "yes"
    assert rows[0]["draft_initial_subject"] == ""
    assert "talking-points only" in rows[0]["qa_flag"]


def test_build_contact_rows_falls_back_to_unknown_tier_draft_when_contacts_tier_has_no_draft():
    p = MULTI.model_copy(update={
        "drafts_by_tier": {"unknown": DraftSet(initial_subject="Generic subject", initial_body="Hi {FIRST_NAME}.")},
    })
    rows = build_contact_rows(p)
    # none of CEO/VP Engineering/Field Technician classify as "unknown", but no
    # tier-specific draft exists for them either — falls back to "unknown"
    assert all(r["draft_initial_subject"] == "Generic subject" for r in rows)


def test_build_contact_rows_blank_draft_when_no_matching_or_unknown_tier():
    p = MULTI.model_copy(update={"drafts_by_tier": {}})
    rows = build_contact_rows(p)
    assert all(r["draft_initial_subject"] == "" for r in rows)
    assert all(r["qa_flag"] == "" for r in rows)


def test_build_contact_rows_merges_first_name_per_row():
    # 2026-07-21 (user): {FIRST_NAME} must never ship literal — merge each
    # contact's own first name into their (tier-matched) draft body.
    rows = build_contact_rows(MULTI)
    assert rows[0]["draft_initial_body"] == "Blake — saw Teal's SRR win."
    assert rows[1]["draft_initial_body"] == "Manoj — saw Teal's SRR win."
    assert rows[2]["draft_initial_body"] == "Steven — Teal's SRR win means more units in the field."
    for r in rows:
        assert "{FIRST_NAME}" not in r["draft_initial_body"]


def test_build_contact_rows_merges_company_variable():
    p = MULTI.model_copy(update={
        "drafts_by_tier": {
            **MULTI.drafts_by_tier,
            "c-suite": MULTI.drafts_by_tier["c-suite"].model_copy(
                update={"initial_body": "Hi {FIRST_NAME}, {COMPANY} ships tough."}
            ),
        }
    })
    rows = build_contact_rows(p)
    assert rows[0]["draft_initial_body"] == "Hi Blake, Teal Drones ships tough."


def test_build_contact_rows_blank_name_falls_back_to_there():
    p = MULTI.model_copy(update={"contact_name": "; Manoj Mohan; Steven Butler"})
    rows = build_contact_rows(p)
    assert rows[0]["draft_initial_body"] == "there — saw Teal's SRR win."


def test_build_contact_rows_trims_long_outreach_angle():
    p = MULTI.model_copy(update={"outreach_angle": "angle " * 100})  # ~600 chars
    rows = build_contact_rows(p)
    assert len(rows[0]["outreach_angle"]) <= 221  # 220 + ellipsis
    assert rows[0]["outreach_angle"].endswith("…")


def test_build_contact_rows_zero_contacts_returns_empty_list():
    p = Prospect(company="X", website="https://x.com", status="priority")
    assert build_contact_rows(p) == []


def test_build_contact_rows_single_contact_carries_company_meta():
    p = Prospect(
        company="X", website="https://x.com",
        date_processed="2026-07-21", status="priority",
        contact_name="Jane Doe", contact_title="VP Ops",
        contact_linkedin="https://linkedin.com/in/jane",
        contact_emails="jane@x.com (verified)",
        outreach_angle="angle text",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="Subject A")},
    )
    rows = build_contact_rows(p)
    assert len(rows) == 1
    assert rows[0]["contact_title"] == "VP Ops"
    assert rows[0]["outreach_angle"] == "angle text"
    assert rows[0]["draft_initial_subject"] == "Subject A"
    assert rows[0]["date_processed"] == "2026-07-21"


def test_write_contacts_csv_header_and_rows(tmp_path):
    path = tmp_path / "contacts.csv"
    n = write_contacts_csv([MULTI], path)
    assert n == 3
    rows = list(csv.reader(path.open()))
    assert rows[0] == CONTACT_COLUMNS
    assert rows[1][CONTACT_COLUMNS.index("contact_name")] == "Blake Resnick"
    assert rows[3][CONTACT_COLUMNS.index("email_status")] == "miss"


def test_write_contacts_csv_drops_are_excluded(tmp_path):
    dropped = MULTI.model_copy(update={"company": "BadCo", "status": "drop"})
    path = tmp_path / "contacts.csv"
    write_contacts_csv([MULTI, dropped], path)
    body = path.read_text()
    assert "Blake Resnick" in body
    assert "BadCo" not in body


def test_push_contacts_to_sheet_writes_header_once_then_rows():
    ws = FakeWorksheet()
    n = push_contacts_to_sheet([MULTI], worksheet=ws)
    assert n == 3
    assert ws.appended[0] == CONTACT_COLUMNS
    assert ws.appended[1][CONTACT_COLUMNS.index("contact_name")] == "Blake Resnick"

    ws2 = FakeWorksheet()
    ws2.values = [CONTACT_COLUMNS]  # header already present
    push_contacts_to_sheet([MULTI], worksheet=ws2)
    assert ws2.appended[0][CONTACT_COLUMNS.index("contact_name")] == "Blake Resnick"


def test_push_contacts_to_sheet_writes_header_on_blank_but_nonempty_values():
    ws = FakeWorksheet()
    ws.values = [[""]]
    push_contacts_to_sheet([MULTI], worksheet=ws)
    assert ws.appended[0] == CONTACT_COLUMNS
    assert ws.appended[1][CONTACT_COLUMNS.index("contact_name")] == "Blake Resnick"
