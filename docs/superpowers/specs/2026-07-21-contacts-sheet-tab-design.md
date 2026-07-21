# Contacts Sheet Tab — design

## Problem

Contacts are currently packed into 4 parallel `"; "`-joined string columns
(`contact_name`, `contact_title`, `contact_linkedin`, `contact_emails`) on the
company's single row in the main output (CSV + Google Sheet). This is hard to
read/filter/sort in a spreadsheet and collapses up to 3 people into one cell.
Goal: one row per tracked contact, in its own tab/CSV.

## Scope

- New `Contacts` output (Sheet tab + parallel CSV), one row per contact,
  reconstructed from the existing packed `Prospect` fields.
- Drop the 4 packed columns from the main sheet/CSV output
  (`SHEET_COLUMNS`/`to_sheet_row`) — the Contacts output becomes the only
  place a human reads contact data.
- **Out of scope:** the underlying `Prospect` fields (`contact_name`,
  `contact_title`, `contact_linkedin`, `contact_emails`) stay unchanged and
  keep being read directly by `gtm/draft.py` (persona tailoring) and
  `gtm/hubspot.py` (its own HubSpot push). Those two subsystems are not
  touched by this project.

## Architecture

**Reconstruction — `gtm/output.py::build_contact_rows(prospect) -> list[dict]`**

New function, colocated with `write_csv`/`push_to_sheet` since this is
output-shaping logic and the only consumer. Splits the 4 packed fields by
index the same way `gtm/hubspot.py::_split_contacts` does, but with
different miss handling: **every index is kept**, including contacts whose
email lookup missed (`hubspot.py` drops those; this must not, contacts with
no resolved email are still real people to reach some other way).

For a `"email (status)"` / `"-"` entry (the encoding `gtm/run.py`'s
`emails_for_prospect` already writes into `contact_emails`): `"-"` means
`contact_email=""`, `email_status="miss"`; otherwise split on `" ("` for
`contact_email` and the trailing `status)"` for `email_status`.

Index 0 (the top-ranked contact — same one `build_draft_prompt` addresses)
additionally carries `outreach_angle` and the 4 draft fields from the
`Prospect`. Indices 1+ leave those 5 fields blank — a draft is written for
one specific person, not force-multiplied across their coworkers'
otherwise-unrelated rows.

A prospect with zero contacts (`contact_name == ""`) produces zero rows —
never a blank placeholder row.

**Worksheet targeting — `gtm/output.py`**

`_open_worksheet` gains a `name: str = "Sheet1"` parameter (default preserves
today's behavior for the main sheet) and auto-creates the worksheet on
`gspread.WorksheetNotFound`:

```python
def _open_worksheet(name: str = "Sheet1"):
    import gspread

    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    ss = gc.open_by_key(os.environ["GTM_SHEET_KEY"])
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=name, rows=1000, cols=20)
```

**New `push_contacts_to_sheet(prospects, *, worksheet=None) -> int`** mirrors
`push_to_sheet`: default-opens `_open_worksheet("Contacts")`, filters to
non-drop prospects, flattens `build_contact_rows` across all of them, and
reuses the same "insert header only if sheet is empty" logic as
`push_to_sheet` (including the blank-but-nonempty-cells edge case already
covered by `test_push_to_sheet_writes_header_on_blank_but_nonempty_values`).

**New `write_contacts_csv(prospects, path) -> int`** mirrors `write_csv`:
same non-drop filter, same header-row + one-row-per-contact shape, always
written regardless of service-account presence (same as `prospects.csv`
today) — parallel file at `prospects_contacts.csv`.

**Wiring — `gtm/run.py::cmd_output`**

```python
csv_path = run_dir(run) / "prospects.csv"
contacts_csv_path = run_dir(run) / "prospects_contacts.csv"
n = write_csv(prospects, csv_path)
nc = write_contacts_csv(prospects, contacts_csv_path)
print(f"wrote {n} prospects -> {csv_path}")
print(f"wrote {nc} contacts -> {contacts_csv_path}")
if Path(SERVICE_ACCOUNT_FILE).exists() and writes_enabled(not dry_run):
    pushed = push_to_sheet(prospects)
    pushed_contacts = push_contacts_to_sheet(prospects)
    print(f"pushed {pushed} rows to Google Sheet")
    print(f"pushed {pushed_contacts} rows to Contacts tab")
```

## Column set (Contacts tab + CSV)

```
company, contact_name, contact_title, contact_linkedin, contact_email,
email_status, outreach_angle, draft_initial_subject, draft_initial_body,
draft_followup_subject, draft_followup_body
```

`email_status` values: `verified | risky | unverified | reject | miss`
(the first four already exist as `_VERDICTS` values in `gtm/emails.py`;
`miss` is new, for the `"-"` case).

## Schema change

`gtm/schema.py`: remove `contact_name`, `contact_title`, `contact_linkedin`,
`contact_emails` from `SHEET_COLUMNS` and from `to_sheet_row`'s output (the
`Prospect` model fields themselves are untouched, per Scope above — only the
sheet-column list and row-rendering change).

## Error handling

- Same log-and-skip convention as the rest of the pipeline: nothing new here,
  `build_contact_rows`/`write_contacts_csv`/`push_contacts_to_sheet` are pure
  functions over already-validated `Prospect` data, no new external calls.
- Contacts tab auto-create means a first-ever run against a fresh Sheet needs
  no manual setup — consistent with how the main sheet already
  self-initializes its header row.

## Testing

`tests/test_output.py` (existing file, has a `FakeWorksheet` double already
usable for the new push function):
- `build_contact_rows`: multi-contact case (3 contacts, mixed email
  statuses), email-miss-is-kept-not-dropped, single-contact (draft fields
  present on the only row), zero-contacts (empty list, no placeholder row),
  draft fields blank on index 1+.
- `write_contacts_csv`: header + rows, drop-status prospects excluded.
- `push_contacts_to_sheet`: header-once-then-rows, blank-but-nonempty
  existing values (reuse the same edge case `push_to_sheet` already covers).

`tests/test_schema.py`: update/remove assertions that reference the 4
removed `SHEET_COLUMNS` entries (see existing
`test_contact_emails_column_follows_contact_linkedin` and the index-offset
assertion in the column-order test).

`tests/test_output.py`'s existing `write_csv`/`push_to_sheet` tests: no
change needed beyond whatever column-count/order assertions implicitly rely
on the removed columns (check `SHEET_COLUMNS` length/order assumptions).

Docs: `docs/PLAN.md` stage-6 description, `docs/data-flow.html` if it
enumerates sheet columns.
