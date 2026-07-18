"""S6 — output: prospects → CSV → Google Sheet (service account, gspread).

CSV is always written (local state). Sheet push needs
credentials/service_account.json + GTM_SHEET_KEY (docs/tools/gspread.md).
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

from gtm.schema import SHEET_COLUMNS, Prospect

SERVICE_ACCOUNT_FILE = "credentials/service_account.json"


def write_csv(prospects: list[Prospect], path: str | Path, include_drops: bool = False) -> int:
    keep = [p for p in prospects if include_drops or p.status != "drop"]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SHEET_COLUMNS)
        for p in keep:
            w.writerow(p.to_sheet_row())
    return len(keep)


def _open_worksheet():
    import gspread

    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    return gc.open_by_key(os.environ["GTM_SHEET_KEY"]).sheet1


def push_to_sheet(prospects: list[Prospect], *, worksheet=None) -> int:
    ws = worksheet if worksheet is not None else _open_worksheet()
    keep = [p for p in prospects if p.status != "drop"]
    rows = [p.to_sheet_row() for p in keep]
    existing = ws.get_all_values()
    has_content = any(cell.strip() for row in existing for cell in row)
    if not has_content:
        rows.insert(0, list(SHEET_COLUMNS))
    ws.append_rows(rows, value_input_option="RAW")
    return len(keep)
