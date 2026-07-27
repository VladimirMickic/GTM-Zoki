# Contacts Sheet Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each tracked contact their own row in a new "Contacts" Google Sheet tab + parallel CSV, instead of packing up to 3 people into one company row.

**Architecture:** `gtm/output.py` gains a pure reconstruction function (`build_contact_rows`) that splits the existing `"; "`-joined `Prospect` contact fields by index — keeping every contact including email misses — plus a parallel CSV writer and Sheet-push function targeting a generalized, auto-creating second worksheet. `gtm/run.py::cmd_output` wires both in alongside the existing company-row output. The 4 packed contact columns are dropped from the main `SHEET_COLUMNS`/CSV/Sheet output (the `Prospect` fields themselves are untouched — `gtm/draft.py` and `gtm/hubspot.py` keep reading them directly).

**Tech Stack:** Python 3, Pydantic (`gtm/schema.py`), `csv` stdlib, `gspread` (Google Sheets), `pytest`.

## Global Constraints

- Work directly on `main` (no feature branches) — established project convention.
- Git identity for every commit: `Vladimir Mickic <mickicvladimir98@gmail.com>`. No `Co-Authored-By` trailer.
- Never push to the remote — commits stay local until the user explicitly asks.
- TDD: write the failing test first, confirm the specific failure reason, implement, confirm it passes, run the full suite for regressions, then commit.
- Log-and-skip: no new code in this plan performs I/O that can fail mid-pipeline (`build_contact_rows`/`write_contacts_csv` are pure functions over already-loaded `Prospect` data) — no new error-handling is needed beyond what already exists in `push_to_sheet`'s caller (`cmd_output`'s existing `credentials.../writes_enabled` gate).
- `Prospect.contact_name`, `contact_title`, `contact_linkedin`, `contact_emails` stay exactly as they are today (still consumed by `gtm/draft.py` and `gtm/hubspot.py`) — this plan only changes what's in `SHEET_COLUMNS`/`to_sheet_row` and adds new output-side functions. Do not touch `gtm/draft.py` or `gtm/hubspot.py`.
- Baseline before this plan: 212 tests passing (`python -m pytest -q`).

---

### Task 1: Drop packed contact columns from the main sheet/CSV

**Files:**
- Modify: `gtm/schema.py:9-37` (`SHEET_COLUMNS`), `gtm/schema.py:56-60` (comment only)
- Test: `tests/test_schema.py:72-92`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SHEET_COLUMNS` (list, in `gtm/schema.py`) drops `"contact_name"`, `"contact_title"`, `"contact_linkedin"`, `"contact_emails"`. `Prospect.to_sheet_row()` unchanged in logic (it iterates `SHEET_COLUMNS`, so the 4 columns simply stop appearing). `Prospect` model fields `contact_name`/`contact_title`/`contact_linkedin`/`contact_emails` are unchanged — Task 2 reads them directly by attribute, not via `SHEET_COLUMNS`.

- [ ] **Step 1: Write the failing test**

Replace the test at `tests/test_schema.py:72-76` (`test_contact_emails_column_follows_contact_linkedin`, which asserts a sheet-column adjacency that will no longer exist) with:

```python
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
```

Also update `test_draft_v1_fields_surface_on_sheet_v2_alt_fields_do_not` at `tests/test_schema.py:90-92` — the line `assert SHEET_COLUMNS[i + 5] == "contact_name"` must become `assert SHEET_COLUMNS[i + 5] == "qa_flag"` (once the 4 contact columns are removed, `qa_flag` immediately follows the draft fields):

```python
    i = SHEET_COLUMNS.index("outreach_angle")
    assert SHEET_COLUMNS[i + 1] == "draft_initial_subject"
    assert SHEET_COLUMNS[i + 5] == "qa_flag"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_schema.py -v`
Expected: `test_contact_fields_are_state_only_not_on_sheet` FAILs with `AssertionError` (`"contact_name" not in SHEET_COLUMNS` is currently False — the column is still there) and `test_draft_v1_fields_surface_on_sheet_v2_alt_fields_do_not` FAILs on the `SHEET_COLUMNS[i + 5] == "qa_flag"` line (currently `"contact_name"`).

- [ ] **Step 3: Remove the 4 columns from `SHEET_COLUMNS`**

In `gtm/schema.py`, delete these 4 lines from the `SHEET_COLUMNS` list (currently lines 29-32, immediately after `"draft_followup_body"` and before `"qa_flag"`):

```python
    "contact_name",
    "contact_title",
    "contact_linkedin",
    "contact_emails",
```

`SHEET_COLUMNS` must read, in order:

```python
SHEET_COLUMNS = [
    "company",
    "website",
    "description",
    "drone_models",
    "drone_dimensions",
    "drone_weights",
    "best_case_line",
    "us_made_ndaa",
    "fit_score",
    "fit_reason",
    "buying_signals",
    "key_news",
    "linkedin",
    "community_signals",
    "outreach_angle",
    "draft_initial_subject",
    "draft_initial_body",
    "draft_followup_subject",
    "draft_followup_body",
    "qa_flag",
    "source",
    "date_processed",
    "status",
]
```

Also update the comment above the (unchanged) `Prospect` field block, currently:

```python
    # stage 5 — contacts + enrich
    contact_name: str = ""
    contact_title: str = ""
    contact_linkedin: str = ""
    contact_emails: str = ""  # "email (status)" per contact, parallel to contact_name; "-" = miss
```

to:

```python
    # stage 5 — contacts + enrich (state only; not in SHEET_COLUMNS — read by
    # gtm/draft.py and gtm/hubspot.py directly, and reconstructed into the
    # Contacts tab/CSV by gtm/output.py::build_contact_rows)
    contact_name: str = ""
    contact_title: str = ""
    contact_linkedin: str = ""
    contact_emails: str = ""  # "email (status)" per contact, parallel to contact_name; "-" = miss
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_schema.py -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Run the full suite for regressions**

Run: `python -m pytest -q`
Expected: `212 passed` (no count change — one test replaced, one test's assertion updated; check no other test references the removed columns before treating this as clean).

- [ ] **Step 6: Commit**

```bash
git add gtm/schema.py tests/test_schema.py
git commit -m "refactor: drop packed contact columns from main sheet/CSV output"
```

---

### Task 2: `gtm/output.py` — contact row reconstruction + parallel CSV/Sheet output

**Files:**
- Modify: `gtm/output.py` (whole file — add `CONTACT_COLUMNS`, `build_contact_rows`, `write_contacts_csv`, generalize `_open_worksheet`, add `push_contacts_to_sheet`)
- Test: `tests/test_output.py`

**Interfaces:**
- Consumes: `Prospect.contact_name`/`contact_title`/`contact_linkedin`/`contact_emails` (unchanged parallel `"; "`-joined strings, per Task 1's Global Constraint), `Prospect.outreach_angle`/`draft_initial_subject`/`draft_initial_body`/`draft_followup_subject`/`draft_followup_body`.
- Produces:
  - `CONTACT_COLUMNS: list[str]` — the Contacts tab/CSV column order.
  - `build_contact_rows(prospect: Prospect) -> list[dict]` — one dict per tracked contact, keys matching `CONTACT_COLUMNS`.
  - `write_contacts_csv(prospects: list[Prospect], path: str | Path) -> int` — returns the number of contact rows written.
  - `_open_worksheet(name: str = "Sheet1")` — now takes a worksheet name, auto-creates via `add_worksheet` if missing.
  - `push_contacts_to_sheet(prospects: list[Prospect], *, worksheet=None) -> int` — returns the number of contact rows pushed (not counting the header).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_output.py`, after the existing `TEAL` constant and before `def test_write_csv_header_and_row`:

```python
MULTI = Prospect(
    company="Teal Drones",
    website="https://tealdrones.com",
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
```

Update the import line at the top of `tests/test_output.py` from:

```python
from gtm.output import push_to_sheet, write_csv
```

to:

```python
from gtm.output import (
    CONTACT_COLUMNS,
    build_contact_rows,
    push_contacts_to_sheet,
    push_to_sheet,
    write_contacts_csv,
    write_csv,
)
```

Append these tests to the end of `tests/test_output.py` (after the existing `test_push_to_sheet_writes_header_on_blank_but_nonempty_values`):

```python
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


def test_build_contact_rows_drafts_only_on_top_contact():
    rows = build_contact_rows(MULTI)
    assert rows[0]["outreach_angle"] == MULTI.outreach_angle
    assert rows[0]["draft_initial_subject"] == "Case built for the Teal 2?"
    assert rows[0]["draft_followup_body"] == "Just circling back."
    for r in rows[1:]:
        assert r["outreach_angle"] == ""
        assert r["draft_initial_subject"] == ""
        assert r["draft_initial_body"] == ""
        assert r["draft_followup_subject"] == ""
        assert r["draft_followup_body"] == ""


def test_build_contact_rows_zero_contacts_returns_empty_list():
    p = Prospect(company="X", website="https://x.com", status="priority")
    assert build_contact_rows(p) == []


def test_build_contact_rows_single_contact_carries_drafts():
    p = Prospect(
        company="X", website="https://x.com", status="priority",
        contact_name="Jane Doe", contact_title="VP Ops",
        contact_linkedin="https://linkedin.com/in/jane",
        contact_emails="jane@x.com (verified)",
        outreach_angle="angle text",
    )
    rows = build_contact_rows(p)
    assert len(rows) == 1
    assert rows[0]["contact_title"] == "VP Ops"
    assert rows[0]["outreach_angle"] == "angle text"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_output.py -v`
Expected: FAIL with `ImportError: cannot import name 'CONTACT_COLUMNS' from 'gtm.output'` (the new tests can't even collect yet).

- [ ] **Step 3: Implement `gtm/output.py`**

Replace the full contents of `gtm/output.py` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_output.py -v`
Expected: all tests PASS (existing + 8 new).

- [ ] **Step 5: Run the full suite for regressions**

Run: `python -m pytest -q`
Expected: `220 passed` (212 baseline + 8 new tests from this task).

- [ ] **Step 6: Commit**

```bash
git add gtm/output.py tests/test_output.py
git commit -m "feat: reconstruct per-contact rows for a parallel Contacts CSV/Sheet tab"
```

---

### Task 3: Wire the Contacts output into `cmd_output`

**Files:**
- Modify: `gtm/run.py:366-396` (`cmd_output`)
- Test: `tests/test_run.py:312-348` (`_setup_output_run` fixture + its two consumer tests)

**Interfaces:**
- Consumes: `gtm.output.write_contacts_csv`, `gtm.output.push_contacts_to_sheet` (from Task 2).
- Produces: `cmd_output` now also writes `<run_dir>/prospects_contacts.csv` (always) and pushes to the "Contacts" tab whenever it pushes to the main Sheet (same `Path(SERVICE_ACCOUNT_FILE).exists() and writes_enabled(...)` gate as the existing Sheet push).

- [ ] **Step 1: Write the failing tests**

Replace `_setup_output_run` in `tests/test_run.py` (currently lines 312-330) with:

```python
def _setup_output_run(monkeypatch, tmp_path):
    """Shared fixture: a run dir with one priority prospect, and a fake
    'credentials exist' service-account file so cmd_output takes the push branch."""
    import gtm.output as output_mod
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", fit_score=87, status="priority")]
    save_state(prospects, tmp_path)

    fake_creds = tmp_path / "service_account.json"
    fake_creds.write_text("{}")
    monkeypatch.setattr(output_mod, "SERVICE_ACCOUNT_FILE", str(fake_creds))

    calls = {"push": 0, "push_contacts": 0}
    monkeypatch.setattr(
        output_mod, "push_to_sheet", lambda *a, **k: calls.__setitem__("push", calls["push"] + 1)
    )
    monkeypatch.setattr(
        output_mod, "push_contacts_to_sheet",
        lambda *a, **k: calls.__setitem__("push_contacts", calls["push_contacts"] + 1),
    )
    return calls
```

Replace the two tests that consume it (currently lines 333-348) with:

```python
def test_cmd_output_dry_run_skips_sheet_push_but_writes_csv(monkeypatch, tmp_path):
    calls = _setup_output_run(monkeypatch, tmp_path)

    cmd_output("ignored", dry_run=True)

    assert calls["push"] == 0
    assert calls["push_contacts"] == 0
    assert (tmp_path / "prospects.csv").exists()
    assert (tmp_path / "prospects_contacts.csv").exists()


def test_cmd_output_live_still_pushes_to_sheet(monkeypatch, tmp_path):
    calls = _setup_output_run(monkeypatch, tmp_path)

    cmd_output("ignored")

    assert calls["push"] == 1
    assert calls["push_contacts"] == 1
    assert (tmp_path / "prospects.csv").exists()
    assert (tmp_path / "prospects_contacts.csv").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run.py -v -k test_cmd_output`
Expected: FAIL — `calls["push_contacts"]` KeyError or assertion `0 == 0`/`1 == 1` never reached because `prospects_contacts.csv` doesn't exist yet (`cmd_output` doesn't call `write_contacts_csv`).

- [ ] **Step 3: Wire the new functions into `cmd_output`**

Replace `cmd_output` in `gtm/run.py` (currently lines 366-396) with:

```python
def cmd_output(run: str, dry_run: bool = False) -> None:
    import os

    from gtm.hubspot import push_to_hubspot
    from gtm.output import (
        SERVICE_ACCOUNT_FILE,
        push_contacts_to_sheet,
        push_to_sheet,
        write_contacts_csv,
        write_csv,
    )

    with _track_stage(run, "output"):
        prospects = load_state(run_dir(run))
        today = time.strftime("%Y-%m-%d")
        for p in prospects:
            p.date_processed = today
        save_state(prospects, run_dir(run))
        csv_path = run_dir(run) / "prospects.csv"
        contacts_csv_path = run_dir(run) / "prospects_contacts.csv"
        n = write_csv(prospects, csv_path)
        nc = write_contacts_csv(prospects, contacts_csv_path)
        print(f"wrote {n} prospects → {csv_path}")
        print(f"wrote {nc} contacts → {contacts_csv_path}")
        if Path(SERVICE_ACCOUNT_FILE).exists() and writes_enabled(not dry_run):
            pushed = push_to_sheet(prospects)
            pushed_contacts = push_contacts_to_sheet(prospects)
            print(f"pushed {pushed} rows to Google Sheet")
            print(f"pushed {pushed_contacts} rows to Contacts tab")
        elif dry_run:
            print("--dry-run — skipped Sheet push (CSV is ready)")
        else:
            print("no credentials/service_account.json — skipped Sheet push (CSV is ready)")

        if os.environ.get("HUBSPOT_SERVICE_KEY") and writes_enabled(not dry_run):
            to_hubspot = [p for p in prospects if p.status in ("priority", "keep")]
            pushed = push_to_hubspot(to_hubspot)
            print(f"pushed {pushed} companies to HubSpot")
        elif dry_run:
            print("--dry-run — skipped HubSpot push (CSV is ready)")
        else:
            print("no HUBSPOT_SERVICE_KEY — skipped HubSpot push (CSV is ready)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_run.py -v -k test_cmd_output`
Expected: all matched tests PASS.

- [ ] **Step 5: Run the full suite for regressions**

Run: `python -m pytest -q`
Expected: `220 passed` (no new tests in this task — two existing tests updated).

- [ ] **Step 6: Commit**

```bash
git add gtm/run.py tests/test_run.py
git commit -m "feat: write and push the Contacts tab/CSV from cmd_output"
```

---

### Task 4: Docs pass

**Files:**
- Modify: `docs/PLAN.md:38-41`, `docs/data-flow.html:246-261`

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: nothing consumed by later tasks (this is the last task).

- [ ] **Step 1: Update `docs/PLAN.md`'s Sheet columns section**

Replace lines 38-41 (currently):

```markdown
## Sheet columns
company · website · description · drone_models · drone_dimensions · drone_weights · best_case_line · us_made/NDAA ·
fit_score · fit_reason · buying_signals · key_news · linkedin · community_signals · outreach_angle ·
contact_name · contact_title · contact_linkedin (top-3, '; '-joined) · source · date_processed · status(feedback)
```

with:

```markdown
## Sheet columns
company · website · description · drone_models · drone_dimensions · drone_weights · best_case_line · us_made/NDAA ·
fit_score · fit_reason · buying_signals · key_news · linkedin · community_signals · outreach_angle ·
draft_initial_subject · draft_initial_body · draft_followup_subject · draft_followup_body ·
qa_flag · source · date_processed · status(feedback)

Contacts get their own tab/CSV (one row per person, not packed into the company row):
company · contact_name · contact_title · contact_linkedin · contact_email · email_status ·
outreach_angle · draft_initial_subject · draft_initial_body · draft_followup_subject · draft_followup_body
(outreach_angle + draft_* populated only on the top-ranked contact's row — see
`gtm/output.py::build_contact_rows`).
```

- [ ] **Step 2: Update `docs/data-flow.html`'s stage-06 card**

Replace lines 246-261 (currently):

```html
      <li class="stage out">
        <div class="rail"><span class="node">06</span></div>
        <div class="card">
          <div class="card-top">
            <h2>Output</h2>
            <span class="chip">▢ gspread</span>
          </div>
          <p>The finished record lands as one row in your Google Sheet, top prospects first — ready for you to work, and to grade.</p>
          <div class="sheet-scroll">
            <div class="sheet">
              <div class="sheet-row head"><span>company</span><span>fit</span><span>best_case</span><span>contact</span><span>status</span></div>
              <div class="sheet-row"><span><b>Teal Drones</b></span><span>87</span><span>AV-Field</span><span>VP, Gov Sales</span><span class="ok">▢ you grade</span></div>
            </div>
          </div>
        </div>
      </li>
```

with:

```html
      <li class="stage out">
        <div class="rail"><span class="node">06</span></div>
        <div class="card">
          <div class="card-top">
            <h2>Output</h2>
            <span class="chip">▢ gspread</span>
          </div>
          <p>The finished record lands as one row in your Google Sheet, top prospects first — ready for you to work, and to grade. Contacts land on their own <b>Contacts</b> tab, one row per person.</p>
          <div class="sheet-scroll">
            <div class="sheet">
              <div class="sheet-row head"><span>company</span><span>fit</span><span>best_case</span><span>status</span></div>
              <div class="sheet-row"><span><b>Teal Drones</b></span><span>87</span><span>AV-Field</span><span class="ok">▢ you grade</span></div>
            </div>
          </div>
        </div>
      </li>
```

- [ ] **Step 3: Run the full suite for regressions**

Run: `python -m pytest -q`
Expected: `220 passed` (docs-only task, no test impact).

- [ ] **Step 4: Commit**

```bash
git add docs/PLAN.md docs/data-flow.html
git commit -m "docs: contacts sheet tab — sheet columns + data-flow diagram"
```
