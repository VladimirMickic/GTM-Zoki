"""S6 — output: CSV in SHEET_COLUMNS order + Sheet push (gspread faked)."""
import csv

from gtm.output import push_to_sheet, write_csv
from gtm.schema import SHEET_COLUMNS, Prospect

TEAL = Prospect(
    company="Teal Drones",
    website="https://tealdrones.com",
    drone_models=["Teal 2", "Black Widow"],
    fit_score=87,
    status="priority",
)


def test_write_csv_header_and_row(tmp_path):
    path = tmp_path / "out.csv"
    write_csv([TEAL], path)
    rows = list(csv.reader(path.open()))
    assert rows[0] == SHEET_COLUMNS
    assert rows[1][SHEET_COLUMNS.index("company")] == "Teal Drones"
    assert rows[1][SHEET_COLUMNS.index("drone_models")] == "Teal 2; Black Widow"
    assert rows[1][SHEET_COLUMNS.index("fit_score")] == "87/100"


def test_write_csv_drops_are_excluded_by_default(tmp_path):
    dropped = TEAL.model_copy(update={"company": "BadCo", "status": "drop"})
    path = tmp_path / "out.csv"
    write_csv([TEAL, dropped], path)
    body = path.read_text()
    assert "Teal Drones" in body
    assert "BadCo" not in body


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


def test_push_to_sheet_writes_header_on_blank_but_nonempty_values():
    # a brand-new Google Sheet can return a row of blank cells (not []) from
    # get_all_values() — must still be treated as "needs header", not "has header"
    ws = FakeWorksheet()
    ws.values = [[""]]
    push_to_sheet([TEAL], worksheet=ws)
    assert ws.appended[0] == SHEET_COLUMNS
    assert ws.appended[1][0] == "Teal Drones"
