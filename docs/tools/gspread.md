# gspread (Google Sheets, service account) — Reference

Docs: https://docs.gspread.org/en/latest/oauth2.html

## 1. Install

```bash
pip install gspread
```

## 2. Google Cloud setup (user does this once, at S6)

1. console.cloud.google.com → create/select project.
2. Enable **Google Sheets API** AND **Google Drive API** (both required).
3. APIs & Services → Credentials → Create credentials → Service account →
   Manage keys → ADD KEY → JSON. Download the JSON.
4. **Share the target spreadsheet with the `client_email` inside the JSON**
   (editor role) — without this every call 403s.

## 3. Our use: open sheet, append new rows, refresh existing ones

```python
import gspread

gc = gspread.service_account(filename="credentials/service_account.json")
sh = gc.open_by_key(sheet_key)      # key = the long id in the sheet URL
ws = sh.sheet1
ws.append_rows(rows, value_input_option="RAW")   # rows = list[list[str]]

# Rewrite rows already on the sheet (gtm/output.py::_flush). One call, any count.
ws.batch_update(
    [{"range": "A5", "values": [row]}, ...],     # "A5" = whole row 5 from col A
    value_input_option="RAW",
)
```

Row numbers: `ws.get_all_values()` is 0-based and row 1 is the header, so
`data_rows[i]` is sheet row `i + 2`.

Default JSON location if no filename passed: `~/.config/gspread/service_account.json`.

## 4. Scopes (gspread sets these itself for service_account())

`https://www.googleapis.com/auth/spreadsheets` + `https://www.googleapis.com/auth/drive`

## 5. Gotchas

- JSON = a private key. Keep in `credentials/` (already deny-listed in
  `.claude/settings.json` + .gitignore). Never print it.
- Forgetting to share the sheet with `client_email` → `SpreadsheetNotFound`/403.
- `open()` by title needs Drive API; `open_by_key()` is more reliable.
- Free Sheets API quota: 300 read + 300 write requests/min per project — one
  `append_rows` + one `batch_update` per tab per run keeps us far under it.
- gspread 6.x flipped `Worksheet.update`'s argument order to
  `update(values, range_name)`. We use `batch_update` instead, whose
  `{'range': ..., 'values': ...}` dicts are unambiguous across versions.
