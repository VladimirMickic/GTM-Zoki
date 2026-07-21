"""S6 — output: prospects → CSV → Google Sheet (service account, gspread).

CSV is always written (local state). Sheet push needs
credentials/service_account.json + GTM_SHEET_KEY (docs/tools/gspread.md).

Contacts get their own parallel output (prospects_contacts.csv + a "Contacts"
worksheet tab) — one row per tracked contact instead of packed into the
company row. See
docs/superpowers/specs/2026-07-21-contacts-sheet-tab-design.md.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

from gtm.schema import SHEET_COLUMNS, Prospect

SERVICE_ACCOUNT_FILE = "credentials/service_account.json"

CONTACT_COLUMNS = [
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
]


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


def _parse_email_entry(entry: str) -> tuple[str, str]:
    """Splits one "email (status)" entry from Prospect.contact_emails into
    (email, status). "-" (or blank) means no email was found — returns
    ("", "miss"), never dropped (unlike gtm/hubspot.py::_parse_email, which
    drops misses for its own CRM-push purposes; the Contacts tab must show
    every tracked person)."""
    entry = entry.strip()
    if not entry or entry == "-":
        return "", "miss"
    if entry.endswith(")") and " (" in entry:
        email, _, status = entry[:-1].partition(" (")
        return email.strip(), status.strip()
    return entry, ""


def build_contact_rows(prospect: Prospect) -> list[dict]:
    """Reconstructs one dict per tracked contact from the "; "-joined parallel
    fields (contact_name/contact_title/contact_linkedin/contact_emails). Every
    index is kept, including email misses. Only the top-ranked contact (index
    0 — the same person build_draft_prompt addresses) carries outreach_angle
    and the draft fields; other rows leave those blank."""
    names = prospect.contact_name.split("; ") if prospect.contact_name else []
    titles = prospect.contact_title.split("; ") if prospect.contact_title else []
    linkedins = prospect.contact_linkedin.split("; ") if prospect.contact_linkedin else []
    emails = prospect.contact_emails.split("; ") if prospect.contact_emails else []

    rows = []
    for i, name in enumerate(names):
        email, status = _parse_email_entry(emails[i]) if i < len(emails) else ("", "miss")
        row = {
            "company": prospect.company,
            "contact_name": name.strip(),
            "contact_title": titles[i] if i < len(titles) else "",
            "contact_linkedin": linkedins[i] if i < len(linkedins) else "",
            "contact_email": email,
            "email_status": status,
            "outreach_angle": "",
            "draft_initial_subject": "",
            "draft_initial_body": "",
            "draft_followup_subject": "",
            "draft_followup_body": "",
        }
        if i == 0:
            row["outreach_angle"] = prospect.outreach_angle
            row["draft_initial_subject"] = prospect.draft_initial_subject
            row["draft_initial_body"] = prospect.draft_initial_body
            row["draft_followup_subject"] = prospect.draft_followup_subject
            row["draft_followup_body"] = prospect.draft_followup_body
        rows.append(row)
    return rows


def write_contacts_csv(prospects: list[Prospect], path: str | Path) -> int:
    keep = [p for p in prospects if p.status != "drop"]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CONTACT_COLUMNS)
        for p in keep:
            for row in build_contact_rows(p):
                w.writerow([row[col] for col in CONTACT_COLUMNS])
                n += 1
    return n


def _open_worksheet(name: str = "Sheet1"):
    import gspread

    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    ss = gc.open_by_key(os.environ["GTM_SHEET_KEY"])
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=name, rows=1000, cols=len(CONTACT_COLUMNS) + 5)


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


def push_contacts_to_sheet(prospects: list[Prospect], *, worksheet=None) -> int:
    ws = worksheet if worksheet is not None else _open_worksheet("Contacts")
    keep = [p for p in prospects if p.status != "drop"]
    rows = [
        [row[col] for col in CONTACT_COLUMNS]
        for p in keep
        for row in build_contact_rows(p)
    ]
    n = len(rows)
    existing = ws.get_all_values()
    has_content = any(cell.strip() for row in existing for cell in row)
    if not has_content:
        rows.insert(0, list(CONTACT_COLUMNS))
    ws.append_rows(rows, value_input_option="RAW")
    return n
