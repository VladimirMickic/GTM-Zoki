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
from typing import NamedTuple

from gtm.schema import CONTACT_FIELD_SEP, SHEET_COLUMNS, DraftSet, Prospect, _trim


class SheetPush(NamedTuple):
    """What a push actually did. `updated` exists because a re-run after a bugfix
    must be able to correct a row it wrote earlier — see push_to_sheet."""

    added: int
    updated: int

    @property
    def total(self) -> int:
        return self.added + self.updated

    def __str__(self) -> str:
        return f"{self.added} new, {self.updated} updated"


SERVICE_ACCOUNT_FILE = "credentials/service_account.json"

# 2026-07-21 (user): the outreach_angle blob repeats on every contact row — cap it
# on the sheet so the cell stays scannable; full text stays in prospects.json.
_OUTREACH_ANGLE_MAX_CHARS = 220

CONTACT_COLUMNS = [
    "company",
    "website",
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
    # voice-guide.md locks the format at "one email, 2 versions" — v2 was computed
    # into DraftSet but had no column, so it never reached the sheet.
    "draft_initial_subject_alt",
    "draft_initial_body_alt",
    "needs_research",
    "qa_flag",
    "date_processed",
]


def by_fit_score(prospects: list[Prospect]) -> list[Prospect]:
    """Highest fit_score first; unscored (error/never-fit) rows sort last, in
    their original order among themselves — a reader scanning top to bottom
    sees the best prospects first without hunting through the fit_score column."""
    return sorted(prospects, key=lambda p: (p.fit_score is None, -(p.fit_score or 0)))


def write_csv(prospects: list[Prospect], path: str | Path, include_drops: bool = True) -> int:
    # 2026-07-21: main sheet is the full funnel (Tier 1/2/3) — drops included by
    # default, tagged tier "3" via the tier column. Pass include_drops=False to
    # get only the qualified (Tier 1/2) rows.
    keep = by_fit_score([p for p in prospects if include_drops or p.status != "drop"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SHEET_COLUMNS)
        for p in keep:
            w.writerow(p.to_sheet_row())
    return len(keep)


# No email cell for a contact at all — the emails stage never processed them.
# Distinct from "miss" on purpose: run us-drone-11 pushed every contact as "miss"
# with `python -m gtm.run emails` never invoked, so the sheet said "searched, found
# nothing" about a search that never happened.
NOT_RUN = "not_run"


def _parse_email_entry(entry: str) -> tuple[str, str]:
    """Splits one "email (status)" entry from Prospect.contact_emails into
    (email, status). Anything that isn't a well-formed "email (status)" entry —
    "-", blank, or malformed — is a miss: returns ("", "miss"), never dropped
    (unlike gtm/hubspot.py::_parse_email, which drops misses for its own
    CRM-push purposes; the Contacts tab must show every tracked person).

    "-" is the miss placeholder, never an address: "- (no-finder-key)" keeps its
    status but yields no email (a literal "-" in contact_email would also collide
    in _contact_dedupe_key, merging two emailless contacts into one row)."""
    entry = entry.strip()
    if entry.endswith(")") and " (" in entry:
        email, _, status = entry[:-1].partition(" (")
        email = email.strip()
        return ("" if email == "-" else email), status.strip()
    return "", "miss"


# Shared inboxes. The email waterfall's tier-3 AI hunt surfaces these when a personal
# mailbox can't be found (data/feedback.jsonl 2026-07-19: team@paladindrones.io returned
# for Maxwell Wang), and they verify clean, so nothing downstream noticed that a
# "Hi Maxwell" draft was addressed to whoever staffs the inbox.
ROLE_LOCAL_PARTS = frozenset(
    {
        "admin", "careers", "contact", "enquiries", "general", "hello", "help", "info",
        "inquiries", "jobs", "mail", "marketing", "office", "press", "sales", "service",
        "support", "team",
    }
)


def role_local_part(email: str) -> str:
    """The shared-inbox local part of `email`, or "" if it looks personal.

    Public because gtm/hubspot.py gates on it too — this repo's recurring bug is
    the same rule living in two places and only one of them getting fixed."""
    local = email.split("@", 1)[0].strip().lower()
    return local if local in ROLE_LOCAL_PARTS else ""


_DRAFT_ROW_FIELDS = (
    "draft_initial_subject",
    "draft_initial_body",
    "draft_initial_subject_alt",
    "draft_initial_body_alt",
)


def build_contact_rows(prospect: Prospect, *, config=None, run_mates=()) -> list[dict]:
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
    from gtm.render import build_render_context, load_outreach_config, render_tokens, unrendered_tokens

    config = config if config is not None else load_outreach_config()
    names = prospect.contact_name.split(CONTACT_FIELD_SEP) if prospect.contact_name else []
    titles = prospect.contact_title.split(CONTACT_FIELD_SEP) if prospect.contact_title else []
    linkedins = (
        prospect.contact_linkedin.split(CONTACT_FIELD_SEP) if prospect.contact_linkedin else []
    )
    emails = prospect.contact_emails.split(CONTACT_FIELD_SEP) if prospect.contact_emails else []
    verifieds = (
        prospect.contact_verified.split(CONTACT_FIELD_SEP) if prospect.contact_verified else []
    )

    rows = []
    for i, name in enumerate(names):
        email, status = _parse_email_entry(emails[i]) if i < len(emails) else ("", NOT_RUN)
        name = name.strip()
        first = name.split()[0] if name else ""
        title = titles[i].strip() if i < len(titles) else ""
        tier = classify_persona(title)
        draft = prospect.drafts_by_tier.get(tier) or prospect.drafts_by_tier.get("unknown") or DraftSet()

        # A draft is written once per company but addressed per contact, so the
        # context is rebuilt per row (first_name differs; everything else repeats).
        ctx = build_render_context(
            prospect, first_name=first, config=config, run_mates=run_mates
        )

        def merge(text: str) -> str:
            return render_tokens(text, ctx)

        row = {
            "company": prospect.company,
            "website": prospect.website,
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
            "draft_initial_subject_alt": merge(draft.initial_subject_alt),
            "draft_initial_body_alt": merge(draft.initial_body_alt),
            "needs_research": "yes" if draft.needs_research else "no",
            "qa_flag": draft.qa_flag,
            "date_processed": prospect.date_processed,
        }

        # Ship gate. A token that survived the render has no data behind it —
        # {{sender_name}} with an unfilled company/outreach.md, {{trigger_event}}
        # with nothing fresh to cite. Run test-batch-1 shipped exactly that to the
        # live Sheet and HubSpot. Blank the draft and say why, loudly.
        survivors = []
        for field in _DRAFT_ROW_FIELDS:
            survivors.extend(t for t in unrendered_tokens(row[field]) if t not in survivors)
        flags = []
        if survivors:
            for field in _DRAFT_ROW_FIELDS:
                row[field] = ""
            # Stays first: unrendered_summary() and cmd_output key off this prefix.
            flags.append(f"unrendered: {', '.join(survivors)}")
        # Second ship gate: the SERP never tied this person to this company. Run
        # us-drone-19 put two strangers on Cleo Robotics and one Darley employee on
        # Harris Aerial, all reading qa_flag="passed" on the live sheet. Blocks like
        # the token gate (copy blanked, row kept for review) because the person may
        # still be right — but nobody should be able to send to them by accident.
        # An empty cell means the run predates the check: no data, so no block.
        if i < len(verifieds) and verifieds[i].strip().lower() == "no":
            for field in _DRAFT_ROW_FIELDS:
                row[field] = ""
            flags.append(
                f"unverified-contact: nothing ties {name or 'this contact'} to "
                f"{prospect.company} — confirm before sending"
            )
        # Third ship gate: no draft was ever written for this contact's persona
        # tier. us-drone-19 re-ran contact discovery after the draft stage and
        # picked up Dan Lombino, whose tier had no DraftSet — his row shipped with
        # every copy cell blank and qa_flag="", which reads on the sheet exactly
        # like "we had nothing to say about him". A draft that is deliberately
        # blank carries its own explanation already (gtm/draft.py::NO_DRAFT_FLAG),
        # so only an unexplained blank is flagged.
        if not draft.initial_subject and not draft.initial_body and not draft.qa_flag:
            flags.append(
                f"no-draft: {name or 'this contact'}'s title classified persona tier "
                f"'{tier}' and the draft stage wrote none for it — re-run draft"
            )
        # A shared inbox is deliverable and sometimes the only way in, so this warns
        # rather than blanking the copy — whether to send a first-name email to a
        # staffed inbox is a human call, and the flag is how they get to make it.
        role = role_local_part(email) if email else ""
        if role:
            flags.append(f"role-address: {role}@ is a shared inbox, not {first or name}")
        if flags:
            row["qa_flag"] = " | ".join(flags + ([draft.qa_flag] if draft.qa_flag else []))

        rows.append(row)
    return rows


def unrendered_summary(prospects: list[Prospect], *, config=None) -> int:
    """How many contact rows this run refused to ship. cmd_output prints it — a
    silent gate is barely better than the silent literal-token delivery it fixes."""
    run_mates = [p.company for p in prospects]
    return sum(
        1
        for p in prospects
        if p.status != "drop"
        for row in build_contact_rows(p, config=config, run_mates=run_mates)
        if row["qa_flag"].startswith("unrendered:")
    )


def unverified_summary(prospects: list[Prospect], *, config=None) -> int:
    """How many contact rows this run blocked for unproven company membership.
    Counted separately from unrendered_summary: that one means "we had no data to
    render", this one means "we had data and do not trust who it is about"."""
    run_mates = [p.company for p in prospects]
    return sum(
        1
        for p in prospects
        if p.status != "drop"
        for row in build_contact_rows(p, config=config, run_mates=run_mates)
        if "unverified-contact:" in row["qa_flag"]
    )


def no_draft_summary(prospects: list[Prospect], *, config=None) -> int:
    """How many contact rows carry no email copy because their persona tier has no
    draft. Third of the three gate counters — the other two mean "we could not
    render it" and "we do not trust who it is about"; this one means the draft
    stage simply never ran for that tier."""
    run_mates = [p.company for p in prospects]
    return sum(
        1
        for p in prospects
        if p.status != "drop"
        for row in build_contact_rows(p, config=config, run_mates=run_mates)
        if "no-draft:" in row["qa_flag"]
    )


OUTREACH_TOKENS = ("{{sender_name}}", "{{reference_customer}}")


def blocked_row_tokens(prospects: list[Prospect], *, config=None) -> list[str]:
    """Which tokens actually blocked this run's rows, in order of first appearance.

    cmd_output used to blame company/outreach.md for every block. Run us-drone-13's
    only block was {{airframe_name}} — a missing drone model, nothing outreach.md can
    fix — so the message sent the reader to the wrong file."""
    run_mates = [p.company for p in prospects]
    tokens: list[str] = []
    for p in prospects:
        if p.status == "drop":
            continue
        for row in build_contact_rows(p, config=config, run_mates=run_mates):
            flag = row["qa_flag"]
            if not flag.startswith("unrendered:"):
                continue
            for token in flag.split("|")[0].removeprefix("unrendered:").split(","):
                token = token.strip()
                if token and token not in tokens:
                    tokens.append(token)
    return tokens


def write_contacts_csv(prospects: list[Prospect], path: str | Path) -> int:
    from gtm.render import load_outreach_config

    keep = [p for p in prospects if p.status != "drop"]
    # Every company in the run is a forbidden reference customer for every other
    # one (company/voice-guide.md's hard rule), so the whole list goes to each row.
    config, run_mates = load_outreach_config(), [p.company for p in prospects]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CONTACT_COLUMNS)
        for p in keep:
            for row in build_contact_rows(p, config=config, run_mates=run_mates):
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


def _contact_identity_keys(row: dict) -> list[str]:
    """Every identity this row can be recognized by, strongest first.

    A contact's strongest identity changes over time: rows pushed before the emails
    stage ran carry only a LinkedIn, and gain an email on the next push. Matching on
    the primary key alone made that same person append as a second row (runs
    us-drone-11/13, 2026-07-29), so both sides of the lookup use the full set."""
    keys = []
    if row["contact_email"]:
        keys.append(f"email:{row['contact_email'].lower()}")
    if row["contact_linkedin"]:
        keys.append(f"li:{row['contact_linkedin'].lower()}")
    if row["contact_name"]:
        keys.append(f"name:{row['company'].lower()}|{row['contact_name'].lower()}")
    return keys


def _contact_dedupe_key(row: dict) -> str:
    """The row's primary identity — email, else LinkedIn, else name+company (still
    better than always appending). Used to dedupe within one run."""
    keys = _contact_identity_keys(row)
    return keys[0] if keys else f"name:{row['company'].lower()}|"


def _open_worksheet(name: str = "Companies"):
    import gspread

    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    ss = gc.open_by_key(os.environ["GTM_SHEET_KEY"])
    try:
        return ss.worksheet(name)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=name, rows=1000, cols=len(CONTACT_COLUMNS) + 5)


def _flush(
    ws,
    updates: list[tuple[int, list]],
    appends: list[list],
    header: list[str] | None = None,
    *,
    rewrite_header: bool = False,
) -> SheetPush:
    """One batch_update for every in-place row refresh, one append_rows for the
    new ones — two API calls per tab regardless of row count (the Sheets free
    quota is per-request, see docs/tools/gspread.md).

    `header` goes onto an empty tab by being prepended to the append batch. On a
    tab that already has content, `rewrite_header` sends it as row 1 of the same
    batch_update instead — a rewrite, so a header written before a column was
    added to the column list stops labelling the wrong data (2026-08-10; the
    Companies tab's fix, see push_to_sheet). Either way the header is never
    counted in `added` or `updated`: it is not a contact.
    """
    batch = [{"range": f"A{row_no}", "values": [row]} for row_no, row in updates]
    if rewrite_header and header:
        batch.insert(0, {"range": "A1", "values": [list(header)]})
    if batch:
        # Only the column count can be short here: append_rows still grows the row
        # count on its own, but neither it nor batch_update grows columns, and the
        # header rewrite is the first write on this tab that can be wider than the
        # grid it lands in.
        _ensure_grid(ws, rows=1, cols=max(len(row) for item in batch for row in item["values"]))
        ws.batch_update(batch, value_input_option="RAW")
    added = len(appends)
    if appends:
        prepend = header and not rewrite_header
        ws.append_rows(
            ([list(header)] + appends) if prepend else appends, value_input_option="RAW"
        )
    return SheetPush(added=added, updated=len(updates))


_FIT_SCORE_IDX = SHEET_COLUMNS.index("fit_score")


def _row_fit_key(row: list[str]) -> tuple[bool, int]:
    """Sort key for one rendered sheet row: highest fit_score first, unscored last.

    Reads the rendered cell ("87/100", "42/80"), not a Prospect — rows already on
    the tab from earlier runs are strings and nothing else. Sorts on the NUMERATOR,
    the same number by_fit_score sorts on and the first thing a reader's eye lands
    on in the column; comparing 42/80 against 38/100 as percentages would order the
    column against how it reads. A blank, malformed, or missing cell sorts last —
    same rule by_fit_score applies to fit_score=None."""
    cell = row[_FIT_SCORE_IDX].strip() if len(row) > _FIT_SCORE_IDX else ""
    head = cell.split("/")[0].strip()
    try:
        return (False, -int(head))
    except ValueError:
        return (True, 0)


def _ensure_grid(ws, *, rows: int, cols: int) -> None:
    """Grow the tab's grid to hold a `rows` x `cols` rewrite, if it doesn't already.

    `append_rows` grew the sheet on its own; `values.batchUpdate` does NOT — it
    fails the whole write with "Range ... exceeds grid limits" the moment the
    merged block passes the tab's row or column count (1000 x 26 on a default
    tab). push_to_sheet stopped appending on 2026-08-05, so that ceiling became
    reachable for the first time. One resize call, only when short, and only for
    the dimension that's short — a tab with room costs nothing.
    """
    have_rows, have_cols = getattr(ws, "row_count", None), getattr(ws, "col_count", None)
    grow: dict[str, int] = {}
    if isinstance(have_rows, int) and have_rows < rows:
        grow["rows"] = rows
    if isinstance(have_cols, int) and have_cols < cols:
        grow["cols"] = cols
    if grow:
        ws.resize(**grow)


def push_to_sheet(prospects: list[Prospect], *, worksheet=None) -> SheetPush:
    # main sheet = full funnel: every tier, drops included (tagged tier "3").
    #
    # A domain already on the sheet is REFRESHED in place; only genuinely new
    # domains append. This supersedes the 2026-07-24 skip-if-present rule, which
    # kept the no-manual-clear property but made every row permanent: a company
    # pushed before a bugfix (Arcsky, live with 0 contacts) could never be
    # corrected by re-running. Refreshing keeps both properties — no clear
    # ritual, and a re-run is the fix.
    #
    # 2026-08-05 (user: "make sure that the scores are descending"): the whole tab
    # is re-sorted by fit_score on every push, not just this run's own rows.
    # by_fit_score ordered each payload correctly and then append_rows put it below
    # everything already there, so the live tab read 83, 68, 52, 65, 38, 78, 70, 42 —
    # eight runs each sorted internally, concatenated. Sorting only what we push
    # cannot fix that; the rows that are out of order are the OLD ones. So the merged
    # block (existing rows + this run's, refreshed) is sorted and rewritten whole, in
    # one batch_update. Rows this run knows nothing about are copied through
    # unchanged — a re-sort moves rows, it never edits or drops one — and the row
    # count only ever grows, so no stale tail is left behind by the rewrite.
    ws = worksheet if worksheet is not None else _open_worksheet()
    existing = ws.get_all_values()
    has_content = any(cell.strip() for row in existing for cell in row)
    website_idx = SHEET_COLUMNS.index("website")
    data_rows = [list(r) for r in existing[1:]] if has_content else []
    # The header is rewritten on every push, not just onto an empty tab. A tab
    # first written before a column was added to SHEET_COLUMNS keeps that stale
    # header forever otherwise, while its data rows go out at the current width —
    # every label past the added column then sits over the wrong data, and no
    # re-run can correct it. Cells the header has beyond SHEET_COLUMNS are kept:
    # they name manual columns someone added to the right of ours, which the
    # rows-padding below already preserves.
    old_header = list(existing[0]) if has_content and existing else []
    header = list(SHEET_COLUMNS) + old_header[len(SHEET_COLUMNS):]

    # First occurrence wins if the sheet somehow already holds a domain twice.
    row_by_domain: dict[str, int] = {}
    for i, row in enumerate(data_rows):
        if len(row) > website_idx:
            row_by_domain.setdefault(_normalize_domain(row[website_idx]), i)

    added = updated = 0
    for p in prospects:
        row = p.to_sheet_row()
        # Deliberately NOT registering the appended row's domain here: two prospects
        # in one push that share a website (a holding company and its brand) each get
        # their own row, exactly as before this function learned to sort. Merging them
        # would silently drop one company from the tab.
        i = row_by_domain.get(_normalize_domain(p.website))
        if i is None:
            data_rows.append(row)
            added += 1
        else:
            data_rows[i] = row
            updated += 1

    ordered = sorted(data_rows, key=_row_fit_key)  # stable: ties keep their tab order
    # A push that changes no row can still owe the tab a rewrite: the re-sort and the
    # header refresh above apply to rows this run never touched. Returning early on
    # `not added and not updated` meant the one command that fixes a mis-ordered tab
    # did nothing whenever the fix was all that was left to do. Skip the write only
    # when there is genuinely nothing to say — order already right, header already
    # right, or an empty tab with no prospects to put on it.
    if (
        not added
        and not updated
        and ordered == data_rows
        and (header == old_header or not has_content)
    ):
        return SheetPush(added=0, updated=0)
    if not ordered and not has_content:
        return SheetPush(added=0, updated=0)

    # Every row goes out the same width, or the rewrite leaves a tail of the row that
    # used to sit at that position: a short legacy row landing where a full one was
    # would blank nothing to its right, and the old cells would read as its own.
    width = max([len(header)] + [len(r) for r in ordered])
    body = [header] + ordered
    body = [r + [""] * (width - len(r)) for r in body]
    _ensure_grid(ws, rows=len(body), cols=width)
    ws.batch_update([{"range": "A1", "values": body}], value_input_option="RAW")
    return SheetPush(added=added, updated=updated)


def push_contacts_to_sheet(prospects: list[Prospect], *, worksheet=None) -> SheetPush:
    ws = worksheet if worksheet is not None else _open_worksheet("Contacts")
    from gtm.render import load_outreach_config

    keep = [p for p in prospects if p.status != "drop"]
    config, run_mates = load_outreach_config(), [p.company for p in prospects]
    candidate_rows = [
        row for p in keep for row in build_contact_rows(p, config=config, run_mates=run_mates)
    ]

    existing = ws.get_all_values()
    has_content = any(cell.strip() for row in existing for cell in row)
    data_rows = existing[1:] if has_content else []
    # The header is rewritten on every push, not just onto an empty tab — the same
    # fix the Companies tab got on 2026-08-10, which this tab did not. CONTACT_COLUMNS
    # has gained columns since a live tab was first written (2a70b3d inserted `website`
    # at index 1), and a tab that keeps its original header labels every column past
    # that point wrongly while its rows go out at the current width. No re-run could
    # correct it, because the header was only ever written onto an empty tab. Cells the
    # header has beyond CONTACT_COLUMNS are manual columns someone added to the right
    # of ours — kept, exactly as push_to_sheet keeps them.
    old_header = list(existing[0]) if has_content and existing else []
    header = list(CONTACT_COLUMNS) + old_header[len(CONTACT_COLUMNS):]
    email_idx = CONTACT_COLUMNS.index("contact_email")
    linkedin_idx = CONTACT_COLUMNS.index("contact_linkedin")
    company_idx = CONTACT_COLUMNS.index("company")
    name_idx = CONTACT_COLUMNS.index("contact_name")
    # Same refresh-don't-skip rule as the Companies tab: a contact already on the
    # tab gets their row rewritten, so a re-drafted email or a corrected title
    # actually reaches the sheet. +2 = header offset (see push_to_sheet).
    row_by_key: dict[str, int] = {}
    for i, row in enumerate(data_rows):
        if len(row) <= max(email_idx, linkedin_idx, company_idx, name_idx):
            continue
        for key in _contact_identity_keys({
            "contact_email": row[email_idx],
            "contact_linkedin": row[linkedin_idx],
            "company": row[company_idx],
            "contact_name": row[name_idx],
        }):
            row_by_key.setdefault(key, i + 2)

    updates: list[tuple[int, list]] = []
    appends: list[list] = []
    seen: set[str] = set()
    for row in candidate_rows:
        key = _contact_dedupe_key(row)
        if key in seen:  # same person twice within this run
            continue
        seen.add(key)
        values = [row[col] for col in CONTACT_COLUMNS]
        row_no = next(
            (row_by_key[k] for k in _contact_identity_keys(row) if k in row_by_key), None
        )
        if row_no is None:
            appends.append(values)
        else:
            updates.append((row_no, values))

    return _flush(ws, updates, appends, header=header, rewrite_header=has_content)
