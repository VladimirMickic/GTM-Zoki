"""S6 — output: CSV in SHEET_COLUMNS order + Sheet push (gspread faked)."""
import csv

from gtm.output import (
    CONTACT_COLUMNS,
    build_contact_rows,
    push_contacts_to_sheet,
    push_to_sheet,
    write_contacts_csv,
    write_csv,
)
from gtm.schema import SHEET_COLUMNS, Prospect

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
    draft_initial_subject="Case built for the Teal 2?",
    draft_initial_body="{FIRST_NAME} — saw Teal's SRR win.",
    draft_followup_subject="Following up",
    draft_followup_body="Just circling back.",
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
        "draft_initial_subject",
        "draft_initial_body",
        "draft_followup_subject",
        "draft_followup_body",
        "date_processed",
    ]


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


def test_build_contact_rows_drafts_repeat_on_every_contact_row():
    # one draft set per company, shared by all its contacts (same as outreach_angle)
    rows = build_contact_rows(MULTI)
    for r in rows:
        assert r["draft_initial_subject"] == "Case built for the Teal 2?"
        assert r["draft_initial_body"] == "{FIRST_NAME} — saw Teal's SRR win."
        assert r["draft_followup_subject"] == "Following up"
        assert r["draft_followup_body"] == "Just circling back."


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
        draft_initial_subject="Subject A",
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
