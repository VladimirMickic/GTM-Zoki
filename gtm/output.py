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
import re
from pathlib import Path

from gtm.schema import CONTACT_FIELD_SEP, SHEET_COLUMNS, DraftSet, Prospect, _trim

SERVICE_ACCOUNT_FILE = "credentials/service_account.json"

# 2026-07-21 (user): the outreach_angle blob repeats on every contact row — cap it
# on the sheet so the cell stays scannable; full text stays in prospects.json.
_OUTREACH_ANGLE_MAX_CHARS = 220

CONTACT_COLUMNS = [
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


def write_csv(prospects: list[Prospect], path: str | Path, include_drops: bool = True) -> int:
    # 2026-07-21: main sheet is the full funnel (Tier 1/2/3) — drops included by
    # default, tagged tier "3" via the tier column. Pass include_drops=False to
    # get only the qualified (Tier 1/2) rows.
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
    (email, status). Anything that isn't a well-formed "email (status)" entry —
    "-", blank, or malformed — is a miss: returns ("", "miss"), never dropped
    (unlike gtm/hubspot.py::_parse_email, which drops misses for its own
    CRM-push purposes; the Contacts tab must show every tracked person)."""
    entry = entry.strip()
    if entry.endswith(")") and " (" in entry:
        email, _, status = entry[:-1].partition(" (")
        return email.strip(), status.strip()
    return "", "miss"


def build_contact_rows(prospect: Prospect) -> list[dict]:
    """Reconstructs one dict per tracked contact from the CONTACT_FIELD_SEP-joined
    parallel fields (contact_name/contact_title/contact_linkedin/contact_emails).
    Every index is kept, including email misses. Company-level fields
    (company/outreach_angle/date_processed) repeat on every row so each contact
    row is self-contained; per-contact fields (name/title/linkedin/email/
    email_status) vary by index, and so does the draft — each contact's own
    title is classified into a persona tier (gtm/persona.py::classify_persona)
    and matched against prospect.drafts_by_tier, falling back to the "unknown"
    tier's draft if that contact's classified tier has no draft of its own."""
    from gtm.persona import classify_persona

    names = prospect.contact_name.split(CONTACT_FIELD_SEP) if prospect.contact_name else []
    titles = prospect.contact_title.split(CONTACT_FIELD_SEP) if prospect.contact_title else []
    linkedins = (
        prospect.contact_linkedin.split(CONTACT_FIELD_SEP) if prospect.contact_linkedin else []
    )
    emails = prospect.contact_emails.split(CONTACT_FIELD_SEP) if prospect.contact_emails else []

    rows = []
    for i, name in enumerate(names):
        email, status = _parse_email_entry(emails[i]) if i < len(emails) else ("", "miss")
        name = name.strip()
        first = name.split()[0] if name else ""
        title = titles[i].strip() if i < len(titles) else ""
        tier = classify_persona(title)
        draft = prospect.drafts_by_tier.get(tier) or prospect.drafts_by_tier.get("unknown") or DraftSet()

        def merge(text: str) -> str:
            # {FIRST_NAME}/{COMPANY} are drafted once per company, substitute this
            # contact's own first name so no placeholder ever ships literal.
            return text.replace("{FIRST_NAME}", first or "there").replace(
                "{COMPANY}", prospect.company
            )

        rows.append({
            "company": prospect.company,
            "contact_name": name,
            "contact_title": title,
            "contact_linkedin": linkedins[i].strip() if i < len(linkedins) else "",
            "contact_email": email,
            "email_status": status,
            "outreach_angle": _trim(prospect.outreach_angle, _OUTREACH_ANGLE_MAX_CHARS),
            "pain_points": merge(draft.pain_points),
            "talking_points": merge(draft.talking_points),
            "draft_initial_subject": merge(draft.initial_subject),
            "draft_initial_body": merge(draft.initial_body),
            "needs_research": "yes" if draft.needs_research else "no",
            "qa_flag": draft.qa_flag,
            "date_processed": prospect.date_processed,
        })
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


def _normalize_domain(website: str) -> str:
    """"https://Teal-Drones.com/" and "tealdrones.com" must dedupe as the same
    row — strip scheme/www/trailing slash/case."""
    d = website.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    return d.rstrip("/")


def _contact_dedupe_key(row: dict) -> str:
    """Email is the most reliable identity; LinkedIn next; name+company last
    resort when a contact has neither (still better than always appending)."""
    if row["contact_email"]:
        return f"email:{row['contact_email'].lower()}"
    if row["contact_linkedin"]:
        return f"li:{row['contact_linkedin'].lower()}"
    return f"name:{row['company'].lower()}|{row['contact_name'].lower()}"


def _open_worksheet(name: str = "Companies"):
    import gspread

    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    ss = gc.open_by_key(os.environ["GTM_SHEET_KEY"])
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=name, rows=1000, cols=len(CONTACT_COLUMNS) + 5)


def push_to_sheet(prospects: list[Prospect], *, worksheet=None) -> int:
    # main sheet = full funnel: every tier, drops included (tagged tier "3").
    # Append-only, no manual-clear ritual: skip any prospect whose domain is
    # already a row on the sheet (2026-07-24 feedback).
    ws = worksheet if worksheet is not None else _open_worksheet()
    existing = ws.get_all_values()
    has_content = any(cell.strip() for row in existing for cell in row)
    website_idx = SHEET_COLUMNS.index("website")
    data_rows = existing[1:] if has_content else []
    existing_domains = {
        _normalize_domain(row[website_idx]) for row in data_rows if len(row) > website_idx
    }
    keep = [p for p in prospects if _normalize_domain(p.website) not in existing_domains]
    rows = [p.to_sheet_row() for p in keep]
    if not rows:
        return 0
    if not has_content:
        rows.insert(0, list(SHEET_COLUMNS))
    ws.append_rows(rows, value_input_option="RAW")
    return len(keep)


def push_contacts_to_sheet(prospects: list[Prospect], *, worksheet=None) -> int:
    ws = worksheet if worksheet is not None else _open_worksheet("Contacts")
    keep = [p for p in prospects if p.status != "drop"]
    candidate_rows = [row for p in keep for row in build_contact_rows(p)]

    existing = ws.get_all_values()
    has_content = any(cell.strip() for row in existing for cell in row)
    data_rows = existing[1:] if has_content else []
    email_idx = CONTACT_COLUMNS.index("contact_email")
    linkedin_idx = CONTACT_COLUMNS.index("contact_linkedin")
    company_idx = CONTACT_COLUMNS.index("company")
    name_idx = CONTACT_COLUMNS.index("contact_name")
    existing_keys = set()
    for row in data_rows:
        if len(row) <= max(email_idx, linkedin_idx, company_idx, name_idx):
            continue
        existing_keys.add(_contact_dedupe_key({
            "contact_email": row[email_idx],
            "contact_linkedin": row[linkedin_idx],
            "company": row[company_idx],
            "contact_name": row[name_idx],
        }))

    new_rows, seen = [], set()
    for row in candidate_rows:
        key = _contact_dedupe_key(row)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        new_rows.append([row[col] for col in CONTACT_COLUMNS])

    n = len(new_rows)
    if n == 0:
        return 0
    if not has_content:
        new_rows.insert(0, list(CONTACT_COLUMNS))
    ws.append_rows(new_rows, value_input_option="RAW")
    return n
