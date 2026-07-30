"""S6 — output: CSV in SHEET_COLUMNS order + Sheet push (gspread faked)."""
import csv

from gtm.output import (
    CONTACT_COLUMNS,
    _open_worksheet,
    build_contact_rows,
    push_contacts_to_sheet,
    push_to_sheet,
    unrendered_summary,
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
            initial_body="{{first_name}} — saw Teal's SRR win.",
            initial_subject_alt="Teal 2 field kit?",
            initial_body_alt="{{first_name}} — SRR win puts more Teal 2s in the field.",
            qa_flag="passed",
        ),
        "ic": DraftSet(
            pain_points="Field gear takes a beating",
            talking_points="Foam insert sized to the Teal 2 | faster swap in the field",
            initial_subject="Field kit for the Teal 2?",
            initial_body="{{first_name}} — Teal's SRR win means more units in the field.",
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
        self.batched = []

    def get_all_values(self):
        return self.values

    def append_rows(self, rows, value_input_option="RAW"):
        self.appended.extend(rows)

    def batch_update(self, data, value_input_option="RAW"):
        self.batched.extend(data)


def test_push_to_sheet_writes_header_once_then_rows():
    ws = FakeWorksheet()
    res = push_to_sheet([TEAL], worksheet=ws)
    assert res.added == 1
    assert ws.appended[0] == SHEET_COLUMNS
    assert ws.appended[1][0] == "Teal Drones"

    ws2 = FakeWorksheet()
    ws2.values = [SHEET_COLUMNS]  # header already present
    push_to_sheet([TEAL], worksheet=ws2)
    assert ws2.appended[0][0] == "Teal Drones"  # no duplicate header


def test_push_to_sheet_includes_dropped_tier3_rows():
    ws = FakeWorksheet()
    dropped = TEAL.model_copy(update={"company": "BadCo", "status": "drop", "fit_score": 12})
    res = push_to_sheet([TEAL, dropped], worksheet=ws)
    assert res.added == 2
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


def test_push_to_sheet_updates_row_whose_domain_already_present():
    # 2026-07-27 (user): a domain already on the sheet is REFRESHED in place, not
    # skipped. Supersedes the 2026-07-24 skip rule: skipping meant any row pushed
    # before a bugfix stayed stale forever (Arcsky shipped with 0 contacts).
    ws = FakeWorksheet()
    stale = ["Teal Drones", "https://tealdrones.com"] + [""] * (len(SHEET_COLUMNS) - 2)
    ws.values = [SHEET_COLUMNS, stale]
    res = push_to_sheet([TEAL], worksheet=ws)
    assert (res.added, res.updated) == (0, 1)
    assert ws.appended == []
    assert ws.batched == [{"range": "A2", "values": [TEAL.to_sheet_row()]}]


def test_push_to_sheet_domain_dedupe_ignores_scheme_www_and_trailing_slash():
    ws = FakeWorksheet()
    ws.values = [SHEET_COLUMNS, ["Teal Drones", "www.tealdrones.com/"] + [""] * (len(SHEET_COLUMNS) - 2)]
    res = push_to_sheet([TEAL], worksheet=ws)
    assert (res.added, res.updated) == (0, 1)


def test_push_to_sheet_update_targets_the_matching_row_not_the_first():
    # off-by-one guard: data_rows is 0-based and the header occupies row 1, so the
    # nth data row is sheet row n+2. Updating the wrong row would silently
    # overwrite a different company.
    ws = FakeWorksheet()
    other = ["OtherCo", "https://otherco.com"] + [""] * (len(SHEET_COLUMNS) - 2)
    stale = ["Teal Drones", "https://tealdrones.com"] + [""] * (len(SHEET_COLUMNS) - 2)
    ws.values = [SHEET_COLUMNS, other, stale]
    push_to_sheet([TEAL], worksheet=ws)
    assert ws.batched == [{"range": "A3", "values": [TEAL.to_sheet_row()]}]


def test_push_to_sheet_appends_new_domains_and_updates_existing_ones():
    ws = FakeWorksheet()
    ws.values = [SHEET_COLUMNS, ["Teal Drones", "https://tealdrones.com"] + [""] * (len(SHEET_COLUMNS) - 2)]
    fresh = TEAL.model_copy(update={"company": "NewCo", "website": "https://newco.com"})
    res = push_to_sheet([TEAL, fresh], worksheet=ws)
    assert (res.added, res.updated) == (1, 1)
    assert ws.appended[0][SHEET_COLUMNS.index("company")] == "NewCo"
    assert ws.batched[0]["range"] == "A2"


def test_push_to_sheet_no_write_calls_when_nothing_to_push():
    ws = FakeWorksheet()
    ws.values = [SHEET_COLUMNS]
    res = push_to_sheet([], worksheet=ws)
    assert (res.added, res.updated) == (0, 0)
    assert ws.appended == [] and ws.batched == []


def test_push_contacts_to_sheet_updates_rows_with_existing_email():
    # 2026-07-27 (user): same rule as the Companies tab — a contact already on the
    # tab gets their row refreshed (re-drafted email, new title), not skipped.
    ws = FakeWorksheet()
    existing_row = [""] * len(CONTACT_COLUMNS)
    existing_row[CONTACT_COLUMNS.index("company")] = "Teal Drones"
    existing_row[CONTACT_COLUMNS.index("contact_email")] = "blake@tealdrones.com"
    ws.values = [CONTACT_COLUMNS, existing_row]
    res = push_contacts_to_sheet([MULTI], worksheet=ws)
    # Blake (email match) updated in place; Manoj + Steven appended as new
    assert (res.added, res.updated) == (2, 1)
    pushed_names = [r[CONTACT_COLUMNS.index("contact_name")] for r in ws.appended]
    assert "Blake Resnick" not in pushed_names
    assert "Manoj Mohan" in pushed_names
    assert ws.batched[0]["range"] == "A2"
    assert ws.batched[0]["values"][0][CONTACT_COLUMNS.index("contact_name")] == "Blake Resnick"


def test_push_contacts_to_sheet_matches_on_linkedin_when_email_is_a_miss():
    # Steven has no email ("-"), so his identity falls back to LinkedIn
    # (_contact_dedupe_key). He must still update, not duplicate.
    ws = FakeWorksheet()
    existing_row = [""] * len(CONTACT_COLUMNS)
    existing_row[CONTACT_COLUMNS.index("company")] = "Teal Drones"
    existing_row[CONTACT_COLUMNS.index("contact_linkedin")] = "https://linkedin.com/in/steven"
    ws.values = [CONTACT_COLUMNS, existing_row]
    res = push_contacts_to_sheet([MULTI], worksheet=ws)
    assert (res.added, res.updated) == (2, 1)
    assert ws.batched[0]["values"][0][CONTACT_COLUMNS.index("contact_name")] == "Steven Butler"


def test_push_contacts_to_sheet_matches_a_row_that_gained_an_email_later():
    # 2026-07-29: runs us-drone-11/13 were pushed BEFORE the emails stage ran, so
    # their sheet rows carry a LinkedIn and no email. Re-pushing after the waterfall
    # changes the contact's primary identity from LinkedIn to email — if the lookup
    # only tries the primary key, the same person appends as a second row.
    ws = FakeWorksheet()
    existing_row = [""] * len(CONTACT_COLUMNS)
    existing_row[CONTACT_COLUMNS.index("company")] = "Teal Drones"
    existing_row[CONTACT_COLUMNS.index("contact_name")] = "Blake Resnick"
    existing_row[CONTACT_COLUMNS.index("contact_linkedin")] = "https://linkedin.com/in/blake"
    ws.values = [CONTACT_COLUMNS, existing_row]
    res = push_contacts_to_sheet([MULTI], worksheet=ws)
    assert (res.added, res.updated) == (2, 1)
    updated = ws.batched[0]["values"][0]
    assert updated[CONTACT_COLUMNS.index("contact_name")] == "Blake Resnick"
    assert updated[CONTACT_COLUMNS.index("contact_email")] == "blake@tealdrones.com"


def test_push_contacts_to_sheet_matches_on_name_when_a_row_has_neither_id():
    # Rows pushed with no email and no LinkedIn (both scraped blank) still have a
    # name+company identity — the third key in _contact_dedupe_key.
    ws = FakeWorksheet()
    existing_row = [""] * len(CONTACT_COLUMNS)
    existing_row[CONTACT_COLUMNS.index("company")] = "Teal Drones"
    existing_row[CONTACT_COLUMNS.index("contact_name")] = "Manoj Mohan"
    ws.values = [CONTACT_COLUMNS, existing_row]
    res = push_contacts_to_sheet([MULTI], worksheet=ws)
    assert (res.added, res.updated) == (2, 1)
    assert ws.batched[0]["values"][0][CONTACT_COLUMNS.index("contact_name")] == "Manoj Mohan"


def test_contact_columns_locked_order():
    # 2026-07-21 (user layout): drafts live on the Contacts tab again; source/status
    # dropped. One row per contact; company-level cells (outreach_angle, drafts,
    # date_processed) repeat on every contact row.
    assert CONTACT_COLUMNS == [
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
        "draft_initial_subject_alt",
        "draft_initial_body_alt",
        "needs_research",
        "qa_flag",
        "date_processed",
    ]


def test_build_contact_rows_carries_both_email_versions():
    """voice-guide.md locks the format at "one email, 2 versions" and DraftSet stores
    both — but v2 had no column, so it never reached the sheet. The rep must be able
    to A/B the two subject lines."""
    rows = build_contact_rows(MULTI)
    assert rows[0]["draft_initial_subject_alt"] == "Teal 2 field kit?"
    assert rows[0]["draft_initial_body_alt"] == "Blake — SRR win puts more Teal 2s in the field."
    # {{first_name}} substitution applies to v2 exactly as it does to v1
    assert "{{first_name}}" not in rows[0]["draft_initial_body_alt"]


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


def test_email_status_not_run_when_emails_stage_never_ran():
    # 2026-07-29: runs us-drone-11/13 shipped every contact as "miss" without the
    # emails stage ever being invoked — "we looked and found nothing" and "we never
    # looked" read identically on the sheet. They are different facts.
    p = MULTI.model_copy(update={"contact_emails": ""})
    rows = build_contact_rows(p)
    assert [r["email_status"] for r in rows] == ["not_run"] * 3
    assert all(r["contact_email"] == "" for r in rows)


def test_role_address_is_flagged_so_a_first_name_draft_is_not_sent_to_a_shared_inbox():
    """data/feedback.jsonl 2026-07-19 (Paladin): tier-3 AI hunt returned
    team@paladindrones.io for Maxwell Wang. Deliverable, verified — and the row still
    shipped a "Hi Maxwell" draft to a shared inbox with nothing on the sheet saying so.
    """
    p = MULTI.model_copy(
        update={"contact_emails": "team@tealdrones.com (verified); manoj@tealdrones.com (valid); -"}
    )
    rows = build_contact_rows(p)
    assert "role-address" in rows[0]["qa_flag"]
    assert "team@" in rows[0]["qa_flag"]
    assert "role-address" not in rows[1]["qa_flag"]  # a personal mailbox is not flagged
    assert "role-address" not in rows[2]["qa_flag"]  # nor is a miss


def test_role_address_flag_does_not_blank_the_draft():
    """A shared inbox is still deliverable and sometimes the only route in — this is a
    human review call, not a broken render, so the copy stays and the flag explains."""
    p = MULTI.model_copy(update={"contact_emails": "info@tealdrones.com (verified); -; -"})
    row = build_contact_rows(p)[0]
    assert row["draft_initial_body"]
    assert row["contact_email"] == "info@tealdrones.com"


def test_role_address_flag_composes_behind_the_unrendered_gate():
    """unrendered_summary() keys off the "unrendered:" prefix, so the ship-gate flag has
    to stay first when a row trips both."""
    p = MULTI.model_copy(
        update={
            "contact_emails": "sales@tealdrones.com (verified); -; -",
            "drafts_by_tier": {
                "c-suite": DraftSet(
                    initial_subject="s", initial_body="Hi {{nickname}}",
                    initial_subject_alt="s2", initial_body_alt="b2",
                )
            },
        }
    )
    row = build_contact_rows(p)[0]
    assert row["qa_flag"].startswith("unrendered:")
    assert "role-address" in row["qa_flag"]
    # both c-suite contacts share that draft, so both rows are gated — the point is
    # that the role-address flag didn't hide either of them from the count
    assert unrendered_summary([p]) == 2


def test_role_address_check_only_looks_at_the_local_part():
    # a personal mailbox on a domain that merely contains a role word is not a role box
    p = MULTI.model_copy(update={"contact_emails": "blake@teamdrones.com (verified); -; -"})
    assert "role-address" not in build_contact_rows(p)[0]["qa_flag"]


def test_email_status_miss_survives_when_waterfall_ran_and_found_nothing():
    p = MULTI.model_copy(update={"contact_emails": "-; -; -"})
    assert [r["email_status"] for r in build_contact_rows(p)] == ["miss"] * 3


def test_email_status_not_run_for_contacts_added_after_the_waterfall():
    # A contact with no parallel email cell at all was never searched, even when
    # earlier indexes were.
    p = MULTI.model_copy(update={"contact_emails": "blake@tealdrones.com (verified)"})
    assert [r["email_status"] for r in build_contact_rows(p)] == [
        "verified", "not_run", "not_run",
    ]


def test_no_finder_key_placeholder_is_not_treated_as_an_email():
    # emails_for_prospect writes "- (no-finder-key)" (gtm/run.py). The "-" is a
    # placeholder, not an address: it must not land in contact_email, and two such
    # contacts must not collapse into one row via the email dedupe key.
    from gtm.output import _contact_dedupe_key

    p = MULTI.model_copy(update={"contact_emails": "- (no-finder-key); - (no-finder-key); -"})
    rows = build_contact_rows(p)
    assert [r["contact_email"] for r in rows] == ["", "", ""]
    assert [r["email_status"] for r in rows] == ["no-finder-key", "no-finder-key", "miss"]
    assert _contact_dedupe_key(rows[0]) != _contact_dedupe_key(rows[1])


def test_build_contact_rows_company_level_fields_repeat_on_every_row():
    # 2026-07-21 (user layout): company-level fields (company, outreach_angle,
    # the four draft cells, date_processed) repeat on every contact row so each
    # row is self-contained. source/status are no longer on this tab.
    rows = build_contact_rows(MULTI)
    for r in rows:
        assert r["company"] == "Teal Drones"
        assert r["website"] == "https://tealdrones.com"
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
        "drafts_by_tier": {"unknown": DraftSet(initial_subject="Generic subject", initial_body="Hi {{first_name}}.")},
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
    # 2026-07-21 (user): {{first_name}} must never ship literal — merge each
    # contact's own first name into their (tier-matched) draft body.
    rows = build_contact_rows(MULTI)
    assert rows[0]["draft_initial_body"] == "Blake — saw Teal's SRR win."
    assert rows[1]["draft_initial_body"] == "Manoj — saw Teal's SRR win."
    assert rows[2]["draft_initial_body"] == "Steven — Teal's SRR win means more units in the field."
    for r in rows:
        assert "{{first_name}}" not in r["draft_initial_body"]


def test_build_contact_rows_merges_company_variable():
    p = MULTI.model_copy(update={
        "drafts_by_tier": {
            **MULTI.drafts_by_tier,
            "c-suite": MULTI.drafts_by_tier["c-suite"].model_copy(
                update={"initial_body": "Hi {{first_name}}, {{company_name}} ships tough."}
            ),
        }
    })
    rows = build_contact_rows(p)
    assert rows[0]["draft_initial_body"] == "Hi Blake, Teal Drones ships tough."


def test_build_contact_rows_blank_name_falls_back_to_there():
    p = MULTI.model_copy(update={"contact_name": "; Manoj Mohan; Steven Butler"})
    rows = build_contact_rows(p)
    # Capitalized: the fill lands at the start of the body (render_tokens, 2026-07-29).
    assert rows[0]["draft_initial_body"] == "There — saw Teal's SRR win."


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
    res = push_contacts_to_sheet([MULTI], worksheet=ws)
    assert res.added == 3
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


# --- 2026-07-28: ship gate. Run test-batch-1 pushed literal {{tokens}} to the live
# Sheet and HubSpot because output.py's substitution used a vocabulary no prompt emits.


def test_build_contact_rows_blanks_and_flags_a_row_with_an_unfillable_token():
    from gtm.render import OutreachConfig

    p = Prospect(
        company="Red Cat", website="https://redcatholdings.com", status="priority",
        contact_name="Jeff Thompson", contact_title="CEO",
        contact_emails="jeff@redcatholdings.com (verified)",
        drafts_by_tier={"c-suite": DraftSet(
            initial_subject="Case for the Black Widow?",
            initial_body="{{first_name}} — nice work.\n\n{{sender_name}}",
            initial_subject_alt="alt",
            initial_body_alt="alt body",
            qa_flag="passed",
        )},
    )
    rows = build_contact_rows(p, config=OutreachConfig(), run_mates=[])
    row = rows[0]
    assert row["draft_initial_body"] == ""       # blanked, not shipped half-filled
    assert row["draft_initial_subject"] == ""
    assert row["draft_initial_body_alt"] == ""
    assert row["draft_initial_subject_alt"] == ""
    assert row["qa_flag"].startswith("unrendered: {{sender_name}}")


def test_build_contact_rows_ships_when_every_token_resolves():
    from gtm.render import OutreachConfig

    cfg = OutreachConfig(sender_name="Vladimir Mickic", fallback_reference="defense sUAS makers we work with")
    p = Prospect(
        company="Red Cat", website="https://redcatholdings.com", status="priority",
        contact_name="Jeff Thompson", contact_title="CEO",
        contact_emails="jeff@redcatholdings.com (verified)",
        drone_models=["Black Widow"], best_case_line="AV-Field",
        drafts_by_tier={"c-suite": DraftSet(
            initial_subject="Case for the {{airframe_name}}?",
            initial_body="{{first_name}} — {{reference_customer}} runs our {{case_line}} line.\n\n{{sender_name}}",
            qa_flag="passed",
        )},
    )
    row = build_contact_rows(p, config=cfg, run_mates=[])[0]
    assert row["draft_initial_subject"] == "Case for the Black Widow?"
    assert row["draft_initial_body"] == (
        "Jeff — defense sUAS makers we work with runs our AV-Field line.\n\nVladimir Mickic"
    )
    assert row["qa_flag"] == "passed"


def test_build_contact_rows_never_names_a_run_mate_as_the_reference():
    from gtm.render import OutreachConfig

    cfg = OutreachConfig(sender_name="V M", reference_customers=["Easy Aerial"],
                         fallback_reference="a defense sUAS maker we work with")
    p = Prospect(
        company="Red Cat", website="https://redcatholdings.com", status="priority",
        contact_name="Jeff Thompson", contact_title="CEO",
        drafts_by_tier={"c-suite": DraftSet(initial_body="{{reference_customer}} likes it. {{sender_name}}")},
    )
    row = build_contact_rows(p, config=cfg, run_mates=["Easy Aerial", "Red Cat"])[0]
    assert "Easy Aerial" not in row["draft_initial_body"]
    # Sentence-initial, so the lowercase fallback is capitalized on the way in.
    assert row["draft_initial_body"].startswith("A defense sUAS maker we work with likes it.")


def test_write_contacts_csv_gates_every_run_mate_together(tmp_path):
    # The reference filter needs the whole run, not one prospect at a time.
    a = Prospect(company="Easy Aerial", website="https://easyaerial.com", status="priority",
                 contact_name="Ido Gur", contact_title="CEO",
                 drafts_by_tier={"c-suite": DraftSet(initial_body="{{reference_customer}} ships ours.")})
    b = Prospect(company="Red Cat", website="https://redcatholdings.com", status="priority",
                 contact_name="Jeff Thompson", contact_title="CEO",
                 drafts_by_tier={"c-suite": DraftSet(initial_body="{{reference_customer}} ships ours.")})
    path = tmp_path / "contacts.csv"
    write_contacts_csv([a, b], path)
    text = path.read_text()
    assert "Easy Aerial ships ours" not in text
    assert "Red Cat ships ours" not in text


def test_unrendered_summary_counts_blocked_rows():
    from gtm.output import unrendered_summary
    from gtm.render import OutreachConfig

    blocked = Prospect(company="Red Cat", website="https://redcatholdings.com", status="priority",
                       contact_name="Jeff Thompson", contact_title="CEO",
                       drafts_by_tier={"c-suite": DraftSet(initial_body="hi {{sender_name}}")})
    clean = Prospect(company="Skydio", website="https://skydio.com", status="priority",
                     contact_name="Adam Bry", contact_title="CEO",
                     drafts_by_tier={"c-suite": DraftSet(initial_body="hi there")})
    assert unrendered_summary([blocked, clean], config=OutreachConfig()) == 1


def test_blocked_row_tokens_names_the_tokens_that_actually_blocked():
    # 2026-07-29: us-drone-13's only block was {{airframe_name}} (no drone model on
    # the prospect) but cmd_output told the reader to fill company/outreach.md.
    from gtm.output import OUTREACH_TOKENS, blocked_row_tokens
    from gtm.render import OutreachConfig

    airframe = Prospect(company="Hylio", website="https://hyl.io", status="priority",
                        contact_name="Joseph Kana", contact_title="CEO",
                        drafts_by_tier={"c-suite": DraftSet(
                            initial_body="hi — the {{airframe_name}}", qa_flag="passed")})
    sender = Prospect(company="Red Cat", website="https://redcatholdings.com", status="priority",
                      contact_name="Jeff Thompson", contact_title="CEO",
                      drafts_by_tier={"c-suite": DraftSet(initial_body="hi {{sender_name}}")})
    filled = OutreachConfig(sender_name="Vladimir Mickic", fallback_reference="defense sUAS makers")

    assert blocked_row_tokens([airframe], config=filled) == ["{{airframe_name}}"]
    assert not any(t in OUTREACH_TOKENS for t in blocked_row_tokens([airframe], config=filled))
    assert blocked_row_tokens([sender], config=OutreachConfig()) == ["{{sender_name}}"]
    assert blocked_row_tokens([], config=filled) == []


# --- 2026-07-30 (us-drone-19 live-sheet audit) -------------------------------
# Contacts who do not work at the target company reached the send-ready Contacts
# tab with qa_flag="passed". gtm/contacts.py now records whether the SERP actually
# tied each person to the company; this is the gate that acts on it.


def test_unverified_contact_is_blocked_and_says_why():
    p = MULTI.model_copy(update={"contact_verified": "yes; no; yes"})
    rows = build_contact_rows(p)
    assert "unverified-contact" in rows[1]["qa_flag"]
    assert "Manoj Mohan" in rows[1]["qa_flag"]
    assert "Teal Drones" in rows[1]["qa_flag"]
    # blocked means the copy does not ship, same gate as an unrendered token
    assert rows[1]["draft_initial_subject"] == ""
    assert rows[1]["draft_initial_body"] == ""
    assert rows[1]["draft_initial_subject_alt"] == ""
    assert rows[1]["draft_initial_body_alt"] == ""
    # the person is still on the sheet to be reviewed, not silently deleted
    assert rows[1]["contact_name"] == "Manoj Mohan"
    assert rows[1]["contact_linkedin"] == "https://linkedin.com/in/manoj"


def test_verified_contacts_ship_normally():
    p = MULTI.model_copy(update={"contact_verified": "yes; no; yes"})
    rows = build_contact_rows(p)
    assert "unverified-contact" not in rows[0]["qa_flag"]
    assert rows[0]["draft_initial_body"]
    assert "unverified-contact" not in rows[2]["qa_flag"]


def test_missing_verification_data_does_not_block_anything():
    """Runs enriched before this check exists have an empty contact_verified. Absent
    evidence is not negative evidence — blocking them all would wipe historical runs."""
    rows = build_contact_rows(MULTI)  # no contact_verified set
    assert all("unverified-contact" not in r["qa_flag"] for r in rows)
    assert rows[0]["draft_initial_body"]


def test_unverified_flag_composes_with_the_unrendered_gate():
    p = MULTI.model_copy(
        update={
            "contact_verified": "no; yes; yes",
            "drafts_by_tier": {
                "c-suite": DraftSet(
                    initial_subject="s", initial_body="Hi {{nickname}}",
                    initial_subject_alt="s2", initial_body_alt="b2",
                )
            },
        }
    )
    row = build_contact_rows(p)[0]
    # unrendered_summary() keys off this prefix — it stays first
    assert row["qa_flag"].startswith("unrendered:")
    assert "unverified-contact" in row["qa_flag"]


def test_unverified_summary_counts_the_blocked_rows():
    from gtm.output import unverified_summary

    p = MULTI.model_copy(update={"contact_verified": "yes; no; no"})
    assert unverified_summary([p]) == 2
    assert unverified_summary([MULTI]) == 0
