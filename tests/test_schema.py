"""S0: Prospect schema — the contract every stage reads/writes."""
from gtm.schema import DraftSet, Prospect, SHEET_COLUMNS


def test_new_prospect_needs_only_company_and_website():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com")
    assert p.company == "Teal Drones"
    assert p.fit_score is None          # not scored yet
    assert p.drone_models == []          # not extracted yet
    assert p.status == ""                # feedback empty until user grades


def test_sheet_row_matches_locked_column_order():
    assert SHEET_COLUMNS[:3] == ["company", "website", "description"]
    # 2026-07-21: main sheet ends at community_signals — outreach/drafts/qa/source/
    # date/status all moved to the Contacts tab (gtm/output.py::CONTACT_COLUMNS).
    assert SHEET_COLUMNS[-1] == "community_signals"
    # tier sits right after fit_score (its band): score, then the 1/2/3 bucket
    assert SHEET_COLUMNS[SHEET_COLUMNS.index("fit_score") + 1] == "tier"
    p = Prospect(
        company="Teal Drones",
        website="https://tealdrones.com",
        drone_models=["Black Widow", "Hellcat"],
        fit_score=87,
        # 87 is an assembled 0-100 score, so the fixture carries the "Budget & procurement"
        # line apply_budget_scores stamps in — the marker fit_denominator reads.
        fit_reason="Budget & procurement 15/20 — [field: headcount] headcount 7000.",
        source="manual",
    )
    row = p.to_sheet_row()
    assert len(row) == len(SHEET_COLUMNS)
    assert row[0] == "Teal Drones"
    assert row[SHEET_COLUMNS.index("fit_score")] == "87/100"
    # lists are joined for the sheet, not dumped as python repr
    assert row[SHEET_COLUMNS.index("drone_models")] == "Black Widow; Hellcat"


def test_tier_derives_from_status_and_renders_on_sheet():
    # 2026-07-21: explicit tier column, derived from status so it never drifts.
    # priority=Tier 1, keep=Tier 2, drop=Tier 3; error/unscored blank.
    assert Prospect(company="X", website="https://x.com", status="priority").tier == "1"
    assert Prospect(company="X", website="https://x.com", status="keep").tier == "2"
    assert Prospect(company="X", website="https://x.com", status="drop").tier == "3"
    assert Prospect(company="X", website="https://x.com", status="error").tier == ""
    assert Prospect(company="X", website="https://x.com").tier == ""
    p = Prospect(company="X", website="https://x.com", fit_score=45, status="keep")
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("tier")] == "2"


def test_why_fit_summarizes_company_in_one_line():
    # 2026-07-21 (user): one-line scannable summary column on the Companies tab.
    p = Prospect(
        company="AeroVironment", website="https://avinc.com", fit_score=78, status="priority",
        best_case_line="AV-Field",
        buying_signals=["Pentagon awarded an $80.5M task order (defensescoop.com, 2026-07-06) — a production ramp"],
    )
    wf = p.why_fit
    # provisional (no "Budget & procurement" line in fit_reason yet) — /80, not /100
    assert wf.startswith("Strong fit (78/80)")
    assert "AV-Field case" in wf
    assert "Pentagon awarded an $80.5M task order" in wf
    assert " — " not in wf and "(defensescoop" not in wf  # rationale/source trimmed off
    # renders on the sheet, right after tier
    row = p.to_sheet_row()
    assert SHEET_COLUMNS[SHEET_COLUMNS.index("tier") + 1] == "why_fit"
    assert row[SHEET_COLUMNS.index("why_fit")] == wf


def test_why_fit_bands_and_unscored():
    # provisional (no fit_reason at all here) — /80, not /100
    assert Prospect(company="X", website="https://x.com", status="drop", fit_score=12).why_fit.startswith("Dropped (12/80)")
    assert Prospect(company="X", website="https://x.com").why_fit == "Unscored"


def test_why_fit_renders_slash_80_when_provisional_pre_enrich():
    # 2026-07-31: fit_score is only the 0-80 scrape-phase score until
    # gtm/run.py::apply_budget_scores folds in the deterministic 20 and stamps a
    # "Budget & procurement" line — rendering "/100" before that overstates a
    # perfect scrape-phase score as if it were the assembled total.
    p = Prospect(
        company="X", website="https://x.com", status="keep", fit_score=48,
        fit_reason="Physical fit 8/35 — [field: none found] no airframe identified.",
    )
    assert p.why_fit.startswith("Possible fit (48/80)")
    # both renderers read fit_denominator, so the two cells can never disagree
    assert p.to_sheet_row()[SHEET_COLUMNS.index("fit_score")] == "48/80"


def test_why_fit_renders_slash_100_once_budget_has_been_folded_in():
    p = Prospect(
        company="X", website="https://x.com", status="priority", fit_score=70,
        fit_reason=(
            "Physical fit 8/35 — [field: none found] no airframe identified.\n"
            "Budget & procurement 15/20 — [field: headcount] headcount 7000."
        ),
    )
    assert p.why_fit.startswith("Strong fit (70/100)")
    assert p.to_sheet_row()[SHEET_COLUMNS.index("fit_score")] == "70/100"


# --- 2026-07-29 (user, live-Sheet review): "why_fit / fit_reason / buying_signals /
# key_news feel weak and vague". Root cause was not the analysis — it was this file
# trimming the decisive part out of every one of those cells on the way to the Sheet.


def test_buying_signal_trim_keeps_source_and_recency_marker():
    # THE bug. _trim_keep_source only protected a trailing "(source)" when the string
    # ended with ")". Every buying signal ends with a "[stale]"/"[undated]" recency
    # marker instead, so the guard never fired and plain _trim ate the source, the
    # date AND the marker — the three tokens a reader actually decides on.
    from gtm.schema import _trim_keep_source

    s = (
        "Awarded a $2.5M contract by the US Army's RCCTO (Rapid Capabilities and Critical "
        "Technologies Office) to deliver prototype Tactical Dronut drones — real defense "
        "procurement, not a proposal (dronelife, 2022-12-14) [stale]"
    )
    # Explicit budget, not _ENTRY_MAX_CHARS: this test is about the source/marker guard,
    # and it has to keep exercising the trim path when that cap moves. It did move —
    # 180 -> 400 on 2026-08-03 — which put this 251-char string under the cap and left
    # the test asserting an ellipsis on a string nothing had trimmed.
    out = _trim_keep_source(s, 180)
    assert out.endswith("(dronelife, 2022-12-14) [stale]")
    assert "…" in out  # still trimmed, just not through the source
    assert out.startswith("Awarded a $2.5M contract")


def test_short_signal_with_marker_is_untouched():
    from gtm.schema import _ENTRY_MAX_CHARS, _trim_keep_source

    s = "Joined the DIU Blue UAS Cleared List (Instagram/harris_aerial) [undated]"
    assert _trim_keep_source(s, _ENTRY_MAX_CHARS) == s


def test_plain_entry_without_source_or_marker_trims_as_before():
    from gtm.schema import _trim_keep_source

    assert _trim_keep_source("alpha bravo charlie delta", 12) == "alpha bravo…"


def test_fit_reason_keeps_every_rubric_line_on_the_sheet():
    # The old whole-string 400-char cap cut from the END, and Displacement is the
    # LAST rubric line — the one the entire outreach angle is built on. Cleo's live
    # cell stopped at "commercial product line ex…", hiding both Procurement and
    # Displacement. Trim per line instead: every dimension and its score survives.
    reason = (
        "Physical fit 28/30 — published dims (7.5in diameter x 4.5in H, 520g), comfortably inside AV-Micro (13x9x6in)\n"
        "Field-deployed 18/25 — confined-space/industrial inspection (pipes, tanks, disaster sites), real field use but indoor-only, not tactical/outdoor\n"
        "Volume/price 6/15 — commercial product line exists, no funding or unit-volume evidence found\n"
        "Procurement & compliance 13/15 — us_made_ndaa true (stated \"manufactured in the USA\")\n"
        "Displacement 14/15 — in-house enclosure: \"ships in a case built by the manufacturer itself\""
    )
    p = Prospect(company="Cleo", website="https://c.com", fit_score=79, status="priority", fit_reason=reason)
    cell = p.to_sheet_row()[SHEET_COLUMNS.index("fit_reason")]
    for dimension in ("Physical fit 28/30", "Field-deployed 18/25", "Volume/price 6/15",
                      "Procurement & compliance 13/15", "Displacement 14/15"):
        assert dimension in cell, f"{dimension} missing from the sheet cell"
    assert len(cell.splitlines()) == 5


def test_fit_reason_still_trims_a_runaway_line():
    p = Prospect(company="X", website="https://x.com", fit_reason="Physical fit 28/30 — " + "word " * 80)
    cell = p.to_sheet_row()[SHEET_COLUMNS.index("fit_reason")]
    assert cell.startswith("Physical fit 28/30 —")
    assert cell.endswith("…")


def test_why_fit_leads_with_the_airframe_and_the_displacement_finding():
    # why_fit used to be band + case line + a verbatim copy of buying_signals[0] —
    # i.e. the score column restated, plus a duplicate of a cell two columns right.
    # It never named the airframe it was sized against or why we can displace.
    p = Prospect(
        company="Cleo Robotics", website="https://cleorobotics.com", fit_score=79, status="priority",
        drone_models=["Dronut DD1", "Dronut X1 Pro"],
        drone_dimensions=["Dronut DD1: 7.5 in diameter x 4.5 in H"],
        best_case_line="AV-Micro",
        inhouse_case="OEM-built case",
        buying_signals=["Awarded a $2.5M contract by the US Army's RCCTO — real procurement (dronelife, 2022-12-14) [stale]"],
    )
    wf = p.why_fit
    # provisional (no "Budget & procurement" line in fit_reason yet) — /80, not /100
    assert wf.startswith("Strong fit (79/80)")
    assert "Dronut DD1: 7.5 in diameter x 4.5 in H" in wf
    assert "AV-Micro" in wf
    assert "builds own case" in wf         # displacement beats the news headline
    assert "OEM-built" not in wf           # the label's attribution isn't said twice
    assert "size unconfirmed" not in wf    # dims ARE published here
    assert "RCCTO" not in wf               # no longer duplicates the buying_signals cell


def test_why_fit_falls_back_to_the_top_signal_without_displacement_evidence():
    p = Prospect(
        company="Harris Aerial", website="https://harrisaerial.com", fit_score=62, status="keep",
        drone_models=["Carrier HX8"], best_case_line="AV-Convoy",
        buying_signals=["Officially joined the DIU's Blue UAS Cleared List — DoD certification (Instagram) [undated]"],
    )
    wf = p.why_fit
    assert "Carrier HX8" in wf             # model name even with no published dims
    assert "AV-Convoy" in wf
    # ...but flagged: Harris scored Physical fit 8/30 and best_case_line is a guess.
    # Without this a rep reads the arrow as a measured match and names the wrong line.
    assert "AV-Convoy (size unconfirmed)" in wf
    assert "Officially joined the DIU's Blue UAS Cleared List" in wf


def test_why_fit_names_a_competitor_when_there_is_one():
    p = Prospect(
        company="X", website="https://x.com", fit_score=70, status="priority",
        best_case_line="AV-Ops", competitor="Pelican 1520",
    )
    assert "Pelican 1520" in p.why_fit


def test_us_made_ndaa_unknown_is_not_a_blank_cell():
    # A blank cell reads "nobody checked". Asylon WAS checked; the answer was unknown.
    # Those are different states and the Sheet must not collapse them.
    unknown = Prospect(company="Asylon", website="https://a.com")
    assert unknown.to_sheet_row()[SHEET_COLUMNS.index("us_made_ndaa")] == "unknown"
    yes = Prospect(company="X", website="https://x.com", us_made_ndaa=True)
    assert yes.to_sheet_row()[SHEET_COLUMNS.index("us_made_ndaa")] == "yes"
    no = Prospect(company="Y", website="https://y.com", us_made_ndaa=False)
    assert no.to_sheet_row()[SHEET_COLUMNS.index("us_made_ndaa")] == "no"


def test_unscored_fit_renders_blank_not_slash_100():
    p = Prospect(company="X", website="https://x.com")
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("fit_score")] == ""


def test_roundtrips_through_json():
    p = Prospect(company="X", website="https://x.com", fit_score=55)
    again = Prospect.model_validate_json(p.model_dump_json())
    assert again == p


def test_schema_splits_dimensions_and_weights():
    # feedback 2026-07-18: dims (L×W×H) drive foam fit; weights alone aren't enough
    assert "drone_sizes" not in SHEET_COLUMNS
    i = SHEET_COLUMNS.index("drone_dimensions")
    assert SHEET_COLUMNS[i + 1] == "drone_weights"
    p = Prospect(
        company="X", website="https://x.com",
        drone_dimensions=["13.7 x 9.8 x 3.5 in folded"],
        drone_weights=["4.26 lbs (1.93 kg)"],
    )
    row = p.to_sheet_row()
    assert row[i] == "13.7 x 9.8 x 3.5 in folded"
    assert row[i + 1] == "4.26 lbs (1.93 kg)"


def test_news_and_signals_render_one_per_line():
    # feedback 2026-07-18: one line per point in the sheet, not run-on "; " strings
    p = Prospect(
        company="X", website="https://x.com",
        key_news=["A — a (url1)", "B — b (url2)"],
        buying_signals=["Signal one — why (src)", "Signal two — why (src)"],
        community_signals=["Reddit thread — hot take (url3)", "X post — reveal (url4)"],
    )
    row = p.to_sheet_row()
    assert row[SHEET_COLUMNS.index("key_news")] == "A — a (url1)\nB — b (url2)"
    assert row[SHEET_COLUMNS.index("buying_signals")] == "Signal one — why (src)\nSignal two — why (src)"
    assert row[SHEET_COLUMNS.index("community_signals")] == "Reddit thread — hot take (url3)\nX post — reveal (url4)"


def test_long_sheet_cells_are_trimmed():
    # 2026-07-21 (user): keep the Companies tab scannable — cap long cells.
    # 2026-07-31: cap raised 3 -> 5 (find_news already caps at MAX_NEWS = 5), so
    # this needs more than 5 source entries to still exercise the item cap itself.
    # 2026-08-03: per-entry cap raised 180 -> 400, so the entries here had to grow
    # past 400 too — at 280 chars they stopped being trimmed at all and this test
    # was asserting a cap that no longer bit.
    p = Prospect(
        company="X", website="https://x.com",
        fit_reason="word " * 200,  # ~1000 chars
        buying_signals=[f"signal {i} " + "detail " * 80 for i in range(7)],  # ~560 chars
    )
    row = p.to_sheet_row()
    assert len(row[SHEET_COLUMNS.index("fit_reason")]) <= 401  # 400 + ellipsis
    assert row[SHEET_COLUMNS.index("fit_reason")].endswith("…")
    signals_cell = row[SHEET_COLUMNS.index("buying_signals")]
    assert signals_cell.count("\n") == 4  # only top-5 of 7 entries kept
    assert all(len(line) <= 401 for line in signals_cell.split("\n"))  # each entry trimmed
    assert all(line.endswith("…") for line in signals_cell.split("\n"))
    # full detail is untouched on the model itself (only the sheet render is capped)
    assert len(p.fit_reason) > 400


def test_long_sheet_cell_trim_preserves_trailing_source_link():
    # feedback 2026-07-24: community-signals cell trim was eating the trailing
    # "(url)" — user saw signals as "vague with no sources".
    long_title = "word " * 40  # long enough that a flat 180-char trim would cut the URL
    p = Prospect(
        company="X", website="https://x.com",
        community_signals=[f"{long_title}— some snippet (https://reddit.com/r/drones/some/long/thread/path)"],
    )
    row = p.to_sheet_row()
    cell = row[SHEET_COLUMNS.index("community_signals")]
    assert cell.endswith("(https://reddit.com/r/drones/some/long/thread/path)")


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


def test_segment_field_is_state_only_not_on_sheet():
    assert "segment" not in SHEET_COLUMNS
    p = Prospect(company="X", website="https://x.com", segment="procurement-compliance-win")
    assert p.segment == "procurement-compliance-win"


def test_outreach_drafts_qa_status_are_state_only_not_on_main_sheet():
    # 2026-07-21: main sheet = company…community_signals only. outreach_angle,
    # competitor/competitor_weaknesses, drafts_by_tier, source, date_processed,
    # and status all live on the Contacts tab (gtm/output.py) or in local state,
    # never on the main row.
    for col in (
        "outreach_angle", "competitor", "competitor_weaknesses",
        "drafts_by_tier", "source", "date_processed", "status",
    ):
        assert col not in SHEET_COLUMNS

    p = Prospect(
        company="X", website="https://x.com",
        outreach_angle="the hook",
        competitor="Pelican 1520",
        competitor_weaknesses=["too heavy — reddit thread"],
        drafts_by_tier={"c-suite": DraftSet(initial_subject="Case built for the Teal 2?", qa_flag="unsupported claim")},
        status="priority",
    )
    row = p.to_sheet_row()
    assert "Case built for the Teal 2?" not in row
    assert "Pelican 1520" not in row
    # fields still exist on the model for draft.py / hubspot.py / the Contacts tab
    assert p.drafts_by_tier["c-suite"].initial_subject == "Case built for the Teal 2?"
    assert p.drafts_by_tier["c-suite"].qa_flag == "unsupported claim"
    assert p.competitor == "Pelican 1520"
    assert p.status == "priority"


def test_draft_set_defaults_all_blank():
    d = DraftSet()
    assert d.initial_subject == ""
    assert d.qa_flag == ""


def test_prospect_drafts_by_tier_defaults_empty_dict():
    p = Prospect(company="X", website="https://x.com")
    assert p.drafts_by_tier == {}


def test_drafts_by_tier_roundtrips_through_json():
    p = Prospect(
        company="X", website="https://x.com",
        drafts_by_tier={"director": DraftSet(initial_subject="Subj")},
    )
    again = Prospect.model_validate_json(p.model_dump_json())
    assert again.drafts_by_tier["director"].initial_subject == "Subj"


def test_prospect_carries_an_inhouse_case_label():
    p = Prospect(company="X", website="https://x.com", inhouse_case="docking station")
    assert p.inhouse_case == "docking station"
    assert Prospect(company="Y", website="https://y.com").inhouse_case == ""


def test_trim_keeps_source_when_a_full_stop_follows_the_parenthetical():
    from gtm.schema import _trim_keep_source

    signal = (
        "Army awarded Anduril an $87M counter-drone task order, the first task order "
        "under a new $20B Army contract vehicle — a real dollar award (not the "
        "vehicle's ceiling), evidence of an active, well-funded gov relationship "
        "(breakingdefense.com, 2026-03)."
    )
    out = _trim_keep_source(signal, 180)
    assert "breakingdefense.com, 2026-03" in out
    assert "…" in out


def test_trim_keeps_marker_when_a_full_stop_follows_it():
    from gtm.schema import _trim_keep_source

    signal = (
        "Air Force awarded Anduril a production contract for autonomous fighter "
        "aircraft (CCA — Collaborative Combat Aircraft), with the line capable of "
        "delivering up to 150 aircraft/year — signals major sustained gov demand and "
        "production scale-up (airandspaceforces.com, jpost.com) [undated]."
    )
    out = _trim_keep_source(signal, 180)
    assert out.rstrip().endswith("[undated]")
    assert "airandspaceforces.com" in out


def test_trim_still_handles_the_no_trailing_punctuation_case():
    from gtm.schema import _trim_keep_source

    signal = "Raised a $110M Series B to scale production (govconwire.com, 2026-02)"
    out = _trim_keep_source(signal, 180)
    assert out == signal  # short enough, untouched


def test_news_entry_budget_excludes_the_url():
    from gtm.schema import _trim_news_entry

    line = (
        "Army awards Anduril counter-drone task order as first in new $20B contract "
        "vehicle — WASHINGTON — The Army-run counter-drone task force has selected "
        "Anduril's Lattice software as the command and control backbone in an $87 "
        "million award announced Friday "
        "(https://breakingdefense.com/2026/03/army-awards-anduril-counter-drone-task-"
        "order-as-first-in-new-20b-contract-vehicle/) [date: 2026-03]"
    )
    out = _trim_news_entry(line, 180)
    assert out.endswith("[date: 2026-03]")
    assert "breakingdefense.com/2026/03/army-awards" in out
    # 180 chars of actual prose survive, not 77.
    prose = out.split(" (http", 1)[0]
    assert len(prose) >= 170, prose
