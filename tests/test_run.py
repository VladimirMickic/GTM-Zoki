"""S7b — orchestrator: state, per-company log&skip, fit/signal merges."""
import json

import pytest

from gtm.brief import load_frozen
from gtm.control import CheckpointPending
from gtm.extract import DroneExtraction
from gtm.fit import FitResult
from gtm.run import (
    cmd_draft,
    cmd_enrich,
    cmd_fit,
    cmd_output,
    cmd_redraft,
    cmd_segment,
    cmd_signals,
    cmd_start,
    company_from_url,
    load_state,
    main,
    merge_drafts,
    merge_fit,
    merge_signals,
    process_company,
    run_dir,
    save_state,
)
from gtm.schema import DraftSet, Prospect


def test_company_name_from_url():
    assert company_from_url("https://www.tealdrones.com/") == "Tealdrones"
    assert company_from_url("https://skydio.com/products") == "Skydio"


def test_state_roundtrip(tmp_path):
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", fit_score=87)]
    save_state(prospects, tmp_path / "r1")
    back = load_state(tmp_path / "r1")
    assert back[0].company == "Teal Drones"
    assert back[0].fit_score == 87


def test_process_company_success():
    p = Prospect(company="Teal Drones", website="https://tealdrones.com")
    ex = DroneExtraction(company_description="sUAS maker", drone_models=["Teal 2"])
    done = process_company(p, scrape_fn=lambda u, preferred="crawl4ai": "# md " * 100, extract_fn=lambda md, **kw: ex)
    assert done.description == "sUAS maker"
    assert done.drone_models == ["Teal 2"]
    assert done.status == ""  # not dropped


def test_process_company_fixes_url_derived_name():
    p = Prospect(company="Tealdrones", website="https://tealdrones.com")
    ex = DroneExtraction(company_name="Teal Drones", company_description="sUAS maker")
    process_company(p, scrape_fn=lambda u, preferred="crawl4ai": "md " * 100, extract_fn=lambda md, **kw: ex)
    assert p.company == "Teal Drones"


def test_process_company_rejects_extracted_name_off_site_domain(tmp_path):
    """A listicle/aggregator page hosted on a real manufacturer's own domain (e.g. a
    ModalAI blog post listing other makers) can pass discover()'s manufacturer filter
    on ModalAI's name, then extract() reads a DIFFERENT company's name ("Teal Drones")
    out of the page body. Trusting that blindly assigns Teal Drones' name to ModalAI's
    URL — wrong website on the sheet, and the email waterfall then guesses patterns
    against the wrong domain. Same class of guard discover.py already applies to
    candidates, applied here to what extraction actually found on the page."""
    errlog = tmp_path / "errors.log"
    ex = DroneExtraction(company_name="Teal Drones", company_description="sUAS maker", drone_models=["Black Widow"])
    p = process_company(
        Prospect(company="ModalAI", website="https://www.modalai.com/pages/2026-us-drone-manufacturers-list"),
        scrape_fn=lambda u, preferred="crawl4ai": "md " * 100,
        extract_fn=lambda md, **kw: ex,
        error_log=errlog,
    )
    assert p.status == "error"
    assert p.company == "ModalAI"  # not overwritten with the mismatched name
    assert p.drone_models == []  # extracted fields discarded, they describe the wrong company
    assert "ModalAI" in errlog.read_text()
    assert "Teal Drones" in errlog.read_text()


def test_process_company_scrape_failure_logs_and_skips(tmp_path):
    errlog = tmp_path / "errors.log"

    def boom(u, preferred="crawl4ai"):
        raise RuntimeError("net down")

    p = process_company(
        Prospect(company="Ghost", website="https://ghost.com"),
        scrape_fn=boom,
        extract_fn=lambda md, **kw: DroneExtraction(),
        error_log=errlog,
    )
    assert p.status == "error"
    assert "Ghost" in errlog.read_text()
    assert "net down" in errlog.read_text()


def test_process_company_toy_drone_auto_dropped():
    ex = DroneExtraction(drone_models=["Nano"], drone_weights=["120 g"])
    p = process_company(
        Prospect(company="ToyCo", website="https://toy.co"),
        scrape_fn=lambda u, preferred="crawl4ai": "md " * 100,
        extract_fn=lambda md, **kw: ex,
    )
    assert p.status == "drop"
    assert "toy/hobby" in p.fit_reason


def test_merge_fit_by_company():
    ps = [Prospect(company="A", website="https://a.com"), Prospect(company="B", website="https://b.com")]
    fits = {"A": FitResult(fit_score=80, fit_reason="good", best_case_line="AV-Field")}
    merge_fit(ps, fits)
    assert ps[0].status == "priority"
    assert ps[1].fit_score is None  # untouched


def test_merge_signals_by_company():
    ps = [Prospect(company="A", website="https://a.com")]
    merge_signals(ps, {"A": {
        "buying_signals": ["won contract"], "outreach_angle": "case for new drone",
        "competitor_weaknesses": ["too heavy"],
    }})
    assert ps[0].buying_signals == ["won contract"]
    assert ps[0].outreach_angle == "case for new drone"
    assert ps[0].competitor_weaknesses == ["too heavy"]


def test_merge_signals_omitting_competitor_weaknesses_preserves_existing_value():
    # cmd_enrich prints the signal prompt and the displacement prompt as two
    # separate blocks — if only the signal prompt gets answered, the
    # signals.json entry for this company won't include competitor_weaknesses
    # at all. That must NOT wipe out ammo already set by displacement research.
    ps = [Prospect(company="A", website="https://a.com", competitor="Pelican 1520",
                    competitor_weaknesses=["too heavy for field carry"])]
    merge_signals(ps, {"A": {"buying_signals": ["won contract"], "outreach_angle": "new angle"}})
    assert ps[0].competitor_weaknesses == ["too heavy for field carry"]


def test_merge_signals_explicit_empty_competitor_weaknesses_still_clears_it():
    ps = [Prospect(company="A", website="https://a.com", competitor="Pelican 1520",
                    competitor_weaknesses=["too heavy for field carry"])]
    merge_signals(ps, {"A": {"buying_signals": [], "outreach_angle": "", "competitor_weaknesses": []}})
    assert ps[0].competitor_weaknesses == []


def test_merge_signals_explicit_new_competitor_weaknesses_overrides_existing():
    ps = [Prospect(company="A", website="https://a.com", competitor="Pelican 1520",
                    competitor_weaknesses=["too heavy for field carry"])]
    merge_signals(ps, {"A": {"competitor_weaknesses": ["cracks in cold weather"]}})
    assert ps[0].competitor_weaknesses == ["cracks in cold weather"]


def test_merge_signals_applies_claudes_reviewed_community_signals():
    # gpt-4o-mini's pain/satisfied judgment (Gate 2) proved unreliable live
    # (2026-07-27/28) — Claude now re-judges the candidates in the same
    # signals.json round trip and the result overwrites the candidate list.
    ps = [Prospect(company="A", website="https://a.com",
                    community_signals=['"unfiltered candidate quote" (reddit.com)'])]
    merge_signals(ps, {"A": {"community_signals": ['"genuine pain quote" (reddit.com)']}})
    assert ps[0].community_signals == ['"genuine pain quote" (reddit.com)']


def test_merge_signals_omitting_community_signals_preserves_candidates():
    # Same missing-key-must-not-wipe-ammo rule as competitor_weaknesses above:
    # an entry that only answers buying_signals/outreach_angle must not erase
    # candidates cmd_enrich already wrote pending Claude's review.
    ps = [Prospect(company="A", website="https://a.com",
                    community_signals=['"unfiltered candidate quote" (reddit.com)'])]
    merge_signals(ps, {"A": {"buying_signals": ["won contract"]}})
    assert ps[0].community_signals == ['"unfiltered candidate quote" (reddit.com)']


# 2026-07-29: 2 of 3 companies in us-drone-19 came out of signals with an empty
# trigger_phrase and nothing said so. A missing phrase is not harmless — it leaves
# {{trigger_event}} unrendered at output, which blocks the whole contact row. The
# signals stage is where it is still cheap to fix, so it has to be loud there.


def test_missing_trigger_phrase_reports_passers_with_signals_but_no_phrase():
    from gtm.run import missing_trigger_phrase

    ps = [
        Prospect(company="Cleo", website="https://c.com", status="priority",
                 buying_signals=["won an award"], trigger_phrase=""),
        Prospect(company="Asylon", website="https://a.com", status="keep",
                 buying_signals=["won an award"], trigger_phrase="Air Force Phase Three award"),
    ]
    assert missing_trigger_phrase(ps) == ["Cleo"]


def test_missing_trigger_phrase_ignores_drops_and_companies_with_no_signals():
    from gtm.run import missing_trigger_phrase

    ps = [
        # dropped: never drafted, so the empty phrase costs nothing
        Prospect(company="Dropped", website="https://d.com", status="drop",
                 buying_signals=["won an award"], trigger_phrase=""),
        # no signals at all: there is nothing to build a trigger phrase FROM, so
        # this is an honest empty, not a silent miss
        Prospect(company="NoSignals", website="https://n.com", status="priority",
                 buying_signals=[], trigger_phrase=""),
    ]
    assert missing_trigger_phrase(ps) == []


def test_known_domains_scans_prior_runs_excluding_current(tmp_path):
    # discover-3 2026-07-18: Teal rediscovered -> would duplicate its sheet row
    from gtm.run import known_domains, save_state

    save_state(
        [Prospect(company="Teal Drones", website="https://tealdrones.com/", status="priority")],
        tmp_path / "teal-demo",
    )
    save_state(
        [
            Prospect(company="BRINC", website="https://brincdrones.com/", status="priority"),
            Prospect(company="Advexure", website="https://advexure.com/x", status="drop"),
            Prospect(company="Red Cat", website="https://redcat.red/", status="error"),
        ],
        tmp_path / "discover-3",
    )
    known = known_domains(runs_root=tmp_path, exclude_run="discover-3")
    # drops and errors were never pushed to the sheet — only pushed statuses count
    assert known == {"tealdrones.com"}
    # excluding the current run lets a brief be safely re-run
    assert known_domains(runs_root=tmp_path, exclude_run="teal-demo") == {"brincdrones.com"}


def test_filter_known_splits_new_from_already_pushed():
    from gtm.run import filter_known

    ps = [
        Prospect(company="Teal Drones", website="https://www.tealdrones.com/"),
        Prospect(company="Skydio", website="https://skydio.com/"),
    ]
    kept, skipped = filter_known(ps, {"tealdrones.com"})
    assert [p.company for p in kept] == ["Skydio"]
    assert [p.company for p in skipped] == ["Teal Drones"]


def test_merge_drafts_writes_v1_to_surfaced_fields_v2_to_alt_fields():
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    raw = {
        "Teal Drones": {
            "c-suite": {
                "pain_points": "damaged units eat into margin",
                "talking_points": "MIL-STD-810H drop rating",
                "draft_initial": {
                    "v1": {"subject": "Case built for the Teal 2?", "body": _QA_BODY},
                    "v2": {"subject": "US-made case, Teal-sized", "body": _QA_BODY_ALT},
                },
            }
        }
    }
    merge_drafts(prospects, raw)
    draft = prospects[0].drafts_by_tier["c-suite"]
    assert draft.pain_points == "damaged units eat into margin"
    assert draft.talking_points == "MIL-STD-810H drop rating"
    assert draft.initial_subject == "Case built for the Teal 2?"
    assert draft.initial_body == _QA_BODY
    assert draft.initial_subject_alt == "US-made case, Teal-sized"
    assert draft.initial_body_alt == _QA_BODY_ALT
    assert draft.needs_research is False


def test_merge_drafts_flags_needs_research_when_no_draft_present():
    # thin-signal tier: prompt was told SKIP, draft_initial comes back {}
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    raw = {
        "Teal Drones": {
            "manager": {
                "pain_points": "team fighting broken gear",
                "talking_points": "smoother logistics",
                "draft_initial": {},
            }
        }
    }
    merge_drafts(prospects, raw)
    draft = prospects[0].drafts_by_tier["manager"]
    assert draft.needs_research is True
    assert draft.initial_subject == ""


def test_merge_drafts_skips_companies_not_in_raw():
    prospects = [Prospect(company="Untouched Co", website="https://x.com", status="priority")]
    merge_drafts(prospects, {})
    assert prospects[0].drafts_by_tier == {}


def test_merge_drafts_multiple_tiers_land_in_separate_draft_sets():
    prospects = [Prospect(company="AeroVironment", website="https://avinc.com", status="priority")]
    raw = {
        "AeroVironment": {
            "c-suite": {"draft_initial": {"v1": {"subject": "C-suite subject", "body": _QA_BODY}}},
            "director": {"draft_initial": {"v1": {"subject": "Director subject", "body": _QA_BODY}}},
        }
    }
    merge_drafts(prospects, raw)
    assert prospects[0].drafts_by_tier["c-suite"].initial_subject == "C-suite subject"
    assert prospects[0].drafts_by_tier["director"].initial_subject == "Director subject"


def test_merge_drafts_preserves_qa_flag_on_existing_tier_content_update():
    # Redraft round-trip: re-merging new content for an already-flagged tier must
    # NOT reset its qa_flag — cmd_redraft's "already checked" skip logic depends
    # on the flag surviving until its own QA loop overwrites it.
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    merge_drafts(prospects, {"Teal Drones": {"c-suite": {"draft_initial": {"v1": {"subject": "Old", "body": _QA_BODY}}}}})
    prospects[0].drafts_by_tier["c-suite"].qa_flag = "unsupported claim"

    merge_drafts(prospects, {"Teal Drones": {"c-suite": {"draft_initial": {"v1": {"subject": "Fixed", "body": _QA_BODY_ALT}}}}})

    draft = prospects[0].drafts_by_tier["c-suite"]
    assert draft.initial_subject == "Fixed"
    assert draft.qa_flag == "unsupported claim"  # untouched by content-only merge


def test_process_company_hunts_missing_specs_and_fills_only_gaps():
    from gtm.spechunt import SpecFindings

    ex = DroneExtraction(drone_models=["X10"], drone_weights=["4.66 lbs"])  # dims+case missing
    findings = SpecFindings(
        drone_dimensions=["X10: 13.7 x 9.8 x 4.6 in folded"],
        drone_weights=["SHOULD NOT OVERWRITE"],
        case_evidence="ships with soft backpack",
    )
    hunted = []

    def fake_hunt(company, models, **kw):
        hunted.append((company, models))
        return findings

    p = process_company(
        Prospect(company="Skydio", website="https://skydio.com"),
        scrape_fn=lambda u, preferred="crawl4ai": "md " * 100,
        extract_fn=lambda md, **kw: ex,
        hunt_fn=fake_hunt,
    )
    assert hunted == [("Skydio", ["X10"])]
    assert p.drone_dimensions == ["X10: 13.7 x 9.8 x 4.6 in folded"]
    assert p.drone_weights == ["4.66 lbs"]          # site data wins; hunt fills gaps only
    assert p.case_evidence == "ships with soft backpack"


def test_process_company_skips_hunt_when_site_had_everything():
    ex = DroneExtraction(
        drone_models=["Teal 2"],
        drone_dimensions=["10 x 8 x 3 in folded"],
        drone_weights=["1.25 kg"],
        case_evidence="ships in a branded hard case",
    )

    def explode(company, models, **kw):
        raise AssertionError("hunt must not run when nothing is missing")

    p = process_company(
        Prospect(company="Teal Drones", website="https://tealdrones.com"),
        scrape_fn=lambda u, preferred="crawl4ai": "md " * 100,
        extract_fn=lambda md, **kw: ex,
        hunt_fn=explode,
    )
    assert p.case_evidence == "ships in a branded hard case"


def test_emails_for_prospect_runs_waterfall_per_contact_parallel_order():
    from gtm.emails import EmailResult
    from gtm.run import emails_for_prospect

    p = Prospect(
        company="BRINC", website="https://brincdrones.com/",
        contact_name="Blake Resnick; Manoj Mohan", status="priority",
    )
    results = {
        "Blake Resnick": EmailResult(email="blake@brincdrones.com", tier="pattern", status="verified", score=98),
        "Manoj Mohan": EmailResult(),  # total miss
    }
    emails_for_prospect(p, waterfall_fn=lambda name, domain, **kw: results[name])
    assert p.contact_emails == "blake@brincdrones.com (verified); -"


def test_emails_for_prospect_isolates_a_failing_contact_from_the_rest(tmp_path, monkeypatch):
    """One contact's waterfall blowing up must not zero out the whole company's emails."""
    import gtm.run as run_mod
    from gtm.emails import EmailResult
    from gtm.run import emails_for_prospect

    log = tmp_path / "errors.log"  # keep the real data/errors.log clean
    monkeypatch.setattr(run_mod, "ERROR_LOG", log)

    p = Prospect(
        company="BRINC", website="https://brincdrones.com/",
        contact_name="Blake Resnick; Manoj Mohan", status="priority",
    )

    def flaky(name, domain, **kw):
        if name == "Blake Resnick":
            raise TimeoutError("provider timed out")
        return EmailResult(email="manoj@brincdrones.com", tier="pattern", status="verified")

    emails_for_prospect(p, waterfall_fn=flaky)
    assert p.contact_emails == "-; manoj@brincdrones.com (verified)"
    assert "emails/Blake Resnick" in log.read_text()  # skipped, but logged


def test_cmd_start_freezes_brief_immune_to_later_edits(tmp_path, monkeypatch):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "DATA", tmp_path)
    monkeypatch.setattr(run_mod, "COSTS", tmp_path / "costs.jsonl")
    monkeypatch.setattr(run_mod, "known_domains", lambda **kw: set())

    def fake_process_company(p, **kw):
        p.description = "sUAS maker"
        p.drone_models = ["Teal 2"]
        return p

    monkeypatch.setattr(run_mod, "process_company", fake_process_company)

    brief_path = tmp_path / "brief.md"
    brief_path.write_text(
        "---\nrun: teal-demo\nurls:\n  - https://tealdrones.com\n---\n"
    )

    with pytest.raises(CheckpointPending):
        cmd_start(str(brief_path))

    # mid-run edit to brief.md must NOT change what the run considers true
    brief_path.write_text(
        "---\nrun: teal-demo\nurls:\n  - https://evil.example.com\n---\n"
    )

    frozen = load_frozen(run_dir("teal-demo"))
    assert frozen.urls == ["https://tealdrones.com"]


def test_cmd_start_raises_checkpoint_pending_when_fit_needed(tmp_path, monkeypatch):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "DATA", tmp_path)
    monkeypatch.setattr(run_mod, "COSTS", tmp_path / "costs.jsonl")
    monkeypatch.setattr(run_mod, "known_domains", lambda **kw: set())

    def fake_process_company(p, **kw):
        p.description = "sUAS maker"
        p.drone_models = ["Teal 2"]
        return p

    monkeypatch.setattr(run_mod, "process_company", fake_process_company)

    brief_path = tmp_path / "brief.md"
    brief_path.write_text(
        "---\nrun: teal-demo-2\nurls:\n  - https://tealdrones.com\n---\n"
    )

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_start(str(brief_path))

    cp = exc_info.value
    assert cp.file == "fit.json"
    assert cp.action == "score prospects"
    assert "teal-demo-2" in cp.resume
    assert "fit.json" in cp.resume


def test_cmd_start_no_checkpoint_when_nothing_needs_fit(tmp_path, monkeypatch):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "DATA", tmp_path)
    monkeypatch.setattr(run_mod, "COSTS", tmp_path / "costs.jsonl")
    monkeypatch.setattr(run_mod, "known_domains", lambda **kw: set())

    def fake_process_company_errors(p, **kw):
        p.status = "error"
        return p

    monkeypatch.setattr(run_mod, "process_company", fake_process_company_errors)

    brief_path = tmp_path / "brief.md"
    brief_path.write_text(
        "---\nrun: teal-demo-3\nurls:\n  - https://tealdrones.com\n---\n"
    )

    cmd_start(str(brief_path))  # must NOT raise — nothing needs fit scoring


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

    def _count(key):
        # both pushers return a SheetPush (added/updated) that cmd_output prints
        def stub(*a, **k):
            calls[key] += 1
            return output_mod.SheetPush(added=1, updated=0)

        return stub

    monkeypatch.setattr(output_mod, "push_to_sheet", _count("push"))
    monkeypatch.setattr(output_mod, "push_contacts_to_sheet", _count("push_contacts"))
    return calls


def test_cmd_output_dry_run_skips_sheet_push_but_writes_csv(monkeypatch, tmp_path):
    calls = _setup_output_run(monkeypatch, tmp_path)

    cmd_output("ignored", dry_run=True)

    assert calls["push"] == 0
    assert calls["push_contacts"] == 0
    assert (tmp_path / "prospects.csv").exists()
    assert (tmp_path / "prospects_contacts.csv").exists()


def test_cmd_output_prints_bucketed_cost_summary(monkeypatch, tmp_path, capsys):
    # user 2026-07-21: end of run shows spend bucketed by provider —
    # openai in dollars, serper in credits.
    from gtm.costlog import CostLog

    _setup_output_run(monkeypatch, tmp_path)
    cl = CostLog(tmp_path / "costs.jsonl")
    cl.record(stage="extract", model="gpt-4o-mini", tokens_in=1000, tokens_out=200, cost_usd=0.04)
    cl.record_serper(stage="enrich", credits=15)

    cmd_output("ignored", dry_run=True)

    out = capsys.readouterr().out
    assert "openai:$0.0400" in out
    assert "serper:15 credits" in out


def test_cmd_output_live_still_pushes_to_sheet(monkeypatch, tmp_path):
    calls = _setup_output_run(monkeypatch, tmp_path)

    cmd_output("ignored")

    assert calls["push"] == 1
    assert calls["push_contacts"] == 1
    assert (tmp_path / "prospects.csv").exists()
    assert (tmp_path / "prospects_contacts.csv").exists()


def _setup_hubspot_run(monkeypatch, tmp_path):
    """Shared fixture: a run dir with priority/keep/drop/error prospects, Sheet
    push inert (no creds file), and push_to_hubspot mocked to record its args."""
    import gtm.hubspot as hubspot_mod
    import gtm.output as output_mod
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [
        Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority"),
        Prospect(company="Skydio", website="https://skydio.com", status="keep"),
        Prospect(company="ToyCo", website="https://toy.co", status="drop"),
        Prospect(company="Ghost", website="https://ghost.com", status="error"),
    ]
    save_state(prospects, tmp_path)

    # No Sheet creds — the Sheet branch stays inert so these tests isolate HubSpot.
    monkeypatch.setattr(output_mod, "SERVICE_ACCOUNT_FILE", str(tmp_path / "no_such_creds.json"))

    calls = {"prospects": None}

    def fake_push_to_hubspot(ps, **kw):
        calls["prospects"] = ps
        return len(ps)

    monkeypatch.setattr(hubspot_mod, "push_to_hubspot", fake_push_to_hubspot)
    return calls


def test_cmd_output_pushes_priority_and_keep_to_hubspot_when_key_set(monkeypatch, tmp_path, capsys):
    calls = _setup_hubspot_run(monkeypatch, tmp_path)
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "fake-key")

    cmd_output("ignored")

    assert [p.company for p in calls["prospects"]] == ["Teal Drones", "Skydio"]
    assert "pushed 2" in capsys.readouterr().out


def test_cmd_output_skips_hubspot_push_without_key(monkeypatch, tmp_path):
    calls = _setup_hubspot_run(monkeypatch, tmp_path)
    monkeypatch.delenv("HUBSPOT_SERVICE_KEY", raising=False)

    cmd_output("ignored")

    assert calls["prospects"] is None


def test_cmd_output_dry_run_skips_hubspot_push_even_with_key(monkeypatch, tmp_path):
    calls = _setup_hubspot_run(monkeypatch, tmp_path)
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "fake-key")

    cmd_output("ignored", dry_run=True)

    assert calls["prospects"] is None


def _stub_enrich_deps(monkeypatch):
    import gtm.contacts as contacts_mod
    import gtm.enrich as enrich_mod

    monkeypatch.setattr(enrich_mod, "enrich", lambda p, **kw: p)
    monkeypatch.setattr(contacts_mod, "find_contacts", lambda company, **kw: [])


def test_cmd_enrich_raises_checkpoint_pending_when_signals_needed(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", fit_score=87, status="priority")]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_enrich("teal-demo-4")

    cp = exc_info.value
    assert cp.file == "signals.json"
    assert cp.action == "answer signal prompts"
    assert "teal-demo-4" in cp.resume
    assert "signals.json" in cp.resume


def test_cmd_enrich_no_checkpoint_when_no_priority_or_keep(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", fit_score=20, status="drop")]
    save_state(prospects, tmp_path)

    cmd_enrich("teal-demo-5")  # must NOT raise — nothing needs a signal prompt


def test_cmd_segment_assigns_and_raises_checkpoint_for_draft_prompts(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", us_made_ndaa=True, status="priority")]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_segment("teal-demo-8")

    cp = exc_info.value
    assert cp.file == "drafts.json"
    assert cp.action == "draft emails"
    assert "teal-demo-8" in cp.resume
    assert "drafts.json" in cp.resume

    saved = load_state(tmp_path)
    assert saved[0].segment == "procurement-compliance-win"  # assigned before the checkpoint fired


def test_cmd_segment_prints_one_draft_prompt_block_per_distinct_tier(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="AeroVironment", website="https://avinc.com", status="priority",
        contact_title="Vice President and Chief Technologist; Senior Director International Sales",
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_segment("teal-demo-tiers")

    out = capsys.readouterr().out
    assert "[c-suite]" in out
    assert "[director]" in out


def test_cmd_segment_no_checkpoint_when_no_priority_or_keep(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Dropped Co", website="https://x.com", status="drop")]
    save_state(prospects, tmp_path)

    cmd_segment("teal-demo-9")  # must NOT raise — nothing needs a draft prompt


def test_cmd_draft_flags_unsupported_claim_and_raises_redraft_checkpoint(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority", segment="defense-ndaa-win")]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "Case built for the Teal 2?", "body": _QA_BODY}, "v2": {"subject": "s2", "body": _QA_BODY_ALT}},
            }
        }
    }))

    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "unsupported $1M claim")

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_draft("teal-demo-10", str(drafts_path))

    cp = exc_info.value
    assert cp.file == "drafts.json"
    assert "redraft" in cp.action
    assert "teal-demo-10" in cp.resume
    assert "redraft" in cp.resume

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].initial_subject == "Case built for the Teal 2?"
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "unsupported $1M claim"  # pending retry, not finalized

    out = capsys.readouterr().out
    assert "REDRAFT" in out
    assert "unsupported $1M claim" in out


def test_cmd_draft_qa_failure_logs_and_skips_not_crashes(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    monkeypatch.setattr(run_mod, "ERROR_LOG", tmp_path / "errors.log")
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", status="priority")]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "s", "body": _QA_BODY}, "v2": {"subject": "s2", "body": _QA_BODY_ALT}},
            }
        }
    }))

    def _raise(p, draft, **kw):
        raise RuntimeError("API down")

    monkeypatch.setattr(run_mod, "qa_check", _raise)

    cmd_draft("teal-demo-11", str(drafts_path))  # must NOT raise

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == ""  # left blank, not blocked
    assert (tmp_path / "errors.log").exists()


def test_cmd_redraft_merges_and_finalizes_qa_passed(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Teal Drones", website="https://tealdrones.com", status="priority",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="old subject", qa_flag="unsupported $1M claim")},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "Fixed subject", "body": _QA_BODY}, "v2": {"subject": "s2", "body": _QA_BODY_ALT}},
            }
        }
    }))
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "")

    cmd_redraft("teal-demo-13", str(drafts_path))  # must NOT raise — single retry cap

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].initial_subject == "Fixed subject"
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "passed"


def test_cmd_redraft_keeps_flag_text_if_still_failing_after_retry(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Teal Drones", website="https://tealdrones.com", status="priority",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="old subject", qa_flag="unsupported $1M claim")},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "c-suite": {
                "draft_initial": {"v1": {"subject": "Still bad", "body": _QA_BODY}, "v2": {"subject": "s2", "body": _QA_BODY_ALT}},
            }
        }
    }))
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "still references unsupported claim")

    cmd_redraft("teal-demo-14", str(drafts_path))  # must NOT raise — no infinite retry loop

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "still references unsupported claim"


def test_cmd_redraft_does_not_recheck_already_passed_prospects(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Already Fine Co", website="https://x.com", status="priority",
        drafts_by_tier={"c-suite": DraftSet(initial_subject="Fine subject", qa_flag="passed")},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({}))  # nothing to merge — this company wasn't flagged

    def _fail(p, draft, **kw):
        raise AssertionError("qa_check must not be called for an already-passed prospect")

    monkeypatch.setattr(run_mod, "qa_check", _fail)

    cmd_redraft("teal-demo-15", str(drafts_path))  # must NOT raise / must NOT call qa_check

    saved = load_state(tmp_path)
    assert saved[0].drafts_by_tier["c-suite"].qa_flag == "passed"


def test_cmd_start_then_cmd_fit_resumes_cleanly(tmp_path, monkeypatch):
    """The second half of the checkpoint contract: feeding fit.json to cmd_fit
    (literally what the printed resume command invokes) must complete without
    raising, and the merged FitResult must land in state via the existing
    apply_fit path (status derived from fit_score threshold)."""
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "DATA", tmp_path)
    monkeypatch.setattr(run_mod, "COSTS", tmp_path / "costs.jsonl")
    monkeypatch.setattr(run_mod, "known_domains", lambda **kw: set())

    def fake_process_company(p, **kw):
        p.description = "sUAS maker"
        p.drone_models = ["Teal 2"]
        return p

    monkeypatch.setattr(run_mod, "process_company", fake_process_company)

    brief_path = tmp_path / "brief.md"
    brief_path.write_text(
        "---\nrun: teal-demo-6\nurls:\n  - https://tealdrones.com\n---\n"
    )

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_start(str(brief_path))

    cp = exc_info.value
    assert "teal-demo-6" in cp.resume
    assert cp.file == "fit.json"

    fit_json_path = tmp_path / "fit.json"
    fit_json_path.write_text(json.dumps({
        "Tealdrones": {
            "fit_score": 85,
            "fit_reason": "strong match",
            "best_case_line": "AV-Field",
            "disqualified": False,
        }
    }))

    cmd_fit("teal-demo-6", str(fit_json_path))  # exactly what the resume command runs

    prospects = load_state(run_dir("teal-demo-6"))
    assert len(prospects) == 1
    p = prospects[0]
    assert p.fit_score == 85
    assert p.best_case_line == "AV-Field"
    assert p.status == "priority"  # apply_fit: score >= 70 -> priority


def test_cmd_enrich_then_cmd_signals_resumes_cleanly(monkeypatch, tmp_path):
    """The second half of the checkpoint contract for the signals checkpoint:
    feeding signals.json to cmd_signals must complete without raising, and the
    merged buying_signals/outreach_angle must land in state."""
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", fit_score=87, status="priority")]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_enrich("teal-demo-7")

    cp = exc_info.value
    assert "teal-demo-7" in cp.resume
    assert cp.file == "signals.json"

    signals_json_path = tmp_path / "signals.json"
    signals_json_path.write_text(json.dumps({
        "Teal Drones": {
            "buying_signals": ["won new DoD contract"],
            "outreach_angle": "custom foam for the new fleet",
        }
    }))

    cmd_signals("teal-demo-7", str(signals_json_path))  # exactly what the resume command runs

    # run_dir is monkeypatched on the gtm.run module attribute (a lambda ignoring
    # the run name), so cmd_signals wrote to tmp_path directly; load from there
    # rather than through this file's own (unpatched) imported `run_dir` name.
    prospects_after = load_state(tmp_path)
    assert len(prospects_after) == 1
    p = prospects_after[0]
    assert p.buying_signals == ["won new DoD contract"]
    assert p.outreach_angle == "custom foam for the new fleet"


def test_cmd_segment_then_cmd_draft_resumes_cleanly(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "")
    prospects = [Prospect(company="Teal Drones", website="https://tealdrones.com", us_made_ndaa=True, status="priority")]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_segment("teal-demo-12")

    cp = exc_info.value
    assert "teal-demo-12" in cp.resume
    assert cp.file == "drafts.json"

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Teal Drones": {
            "unknown": {
                "draft_initial": {"v1": {"subject": "Case built for the Teal 2?", "body": _QA_BODY}, "v2": {"subject": "s2", "body": _QA_BODY_ALT}},
            }
        }
    }))

    cmd_draft("teal-demo-12", str(drafts_path))  # exactly what the resume command runs

    saved = load_state(tmp_path)
    assert len(saved) == 1
    p = saved[0]
    assert p.segment == "procurement-compliance-win"  # survived the round-trip from cmd_segment
    assert p.drafts_by_tier["unknown"].initial_subject == "Case built for the Teal 2?"
    assert p.drafts_by_tier["unknown"].qa_flag == "passed"


def test_main_exits_5_and_prints_resume_when_start_checkpoints(monkeypatch, capsys):
    import gtm.run as run_mod
    from gtm.control import CheckpointPending

    def fake_cmd_start(brief_path):
        raise CheckpointPending(
            file="fit.json", action="score prospects",
            resume="python -m gtm.run fit teal-demo fit.json",
        )

    monkeypatch.setattr(run_mod, "cmd_start", fake_cmd_start)
    monkeypatch.setattr("sys.argv", ["gtm.run", "start", "data/runs/teal-demo/brief.md"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 5
    out = capsys.readouterr().out
    assert "fit.json" in out
    assert "python -m gtm.run fit teal-demo fit.json" in out


def test_main_exits_5_and_prints_resume_when_enrich_checkpoints(monkeypatch, capsys):
    import gtm.run as run_mod
    from gtm.control import CheckpointPending

    def fake_cmd_enrich(run):
        raise CheckpointPending(
            file="signals.json", action="answer signal prompts",
            resume="python -m gtm.run signals teal-demo signals.json",
        )

    monkeypatch.setattr(run_mod, "cmd_enrich", fake_cmd_enrich)
    monkeypatch.setattr("sys.argv", ["gtm.run", "enrich", "teal-demo"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 5
    out = capsys.readouterr().out
    assert "signals.json" in out
    assert "python -m gtm.run signals teal-demo signals.json" in out


# ---------------------------------------------------------- Task 6.2: GitHub tracking


class FakeGithubState:
    """Records calls in shape matching gtm/github_state.py's real signatures.
    Injected in place of the gtm.run module's `github_state` import."""

    def __init__(self, issue=42):
        self.issue = issue
        self.calls = []

    def open_run_issue(self, run, run_dir, *, stage="input", status="running", error_log=None):
        self.calls.append(("open_run_issue", run, stage, status))
        return self.issue

    def set_stage_labels(self, issue, run, stage, status, *, error_log=None):
        self.calls.append(("set_stage_labels", issue, run, stage, status))
        return [f"run:{run}", f"stage:{stage}", f"status:{status}"]

    def post_checkpoint_comment(self, issue, file, action, resume, *, error_log=None):
        self.calls.append(("post_checkpoint_comment", issue, file, action, resume))
        return True


def test_stage_transition_labels_running_then_complete_on_success(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    fake = FakeGithubState()
    monkeypatch.setattr(run_mod, "github_state", fake)

    prospects = [Prospect(company="A", website="https://a.com")]
    save_state(prospects, tmp_path)

    signals_json_path = tmp_path / "signals.json"
    signals_json_path.write_text(json.dumps({"A": {"buying_signals": [], "outreach_angle": "x"}}))

    cmd_signals("teal-demo", str(signals_json_path))

    label_calls = [c for c in fake.calls if c[0] == "set_stage_labels"]
    statuses = [c[4] for c in label_calls]
    assert statuses == ["running", "complete"]
    assert all(c[2] == "teal-demo" and c[3] == "signals" for c in label_calls)


def test_checkpoint_pending_sets_checkpoint_label_and_posts_comment_then_reraises(
    monkeypatch, tmp_path
):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    fake = FakeGithubState()
    monkeypatch.setattr(run_mod, "github_state", fake)

    prospects = [
        Prospect(company="Teal Drones", website="https://tealdrones.com", fit_score=87, status="priority")
    ]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending) as exc_info:
        cmd_enrich("teal-demo-cp")

    cp = exc_info.value
    label_calls = [c for c in fake.calls if c[0] == "set_stage_labels"]
    assert label_calls[-1] == ("set_stage_labels", fake.issue, "teal-demo-cp", "enrich", "checkpoint")

    comment_calls = [c for c in fake.calls if c[0] == "post_checkpoint_comment"]
    assert len(comment_calls) == 1
    assert comment_calls[0] == ("post_checkpoint_comment", fake.issue, cp.file, cp.action, cp.resume)


def test_stage_exception_sets_failed_label_then_reraises(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    fake = FakeGithubState()
    monkeypatch.setattr(run_mod, "github_state", fake)

    prospects = [Prospect(company="A", website="https://a.com")]
    save_state(prospects, tmp_path)

    bad_signals_json = tmp_path / "signals.json"
    bad_signals_json.write_text("not valid json {{{")

    with pytest.raises(json.JSONDecodeError):
        cmd_signals("teal-demo-fail", str(bad_signals_json))

    label_calls = [c for c in fake.calls if c[0] == "set_stage_labels"]
    statuses = [c[4] for c in label_calls]
    assert statuses == ["running", "failed"]


def test_track_stage_rejects_invalid_stage_name(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    fake = FakeGithubState()
    monkeypatch.setattr(run_mod, "github_state", fake)

    with pytest.raises(ValueError):
        with run_mod._track_stage("teal-demo", "not-a-real-stage"):
            pass

    assert fake.calls == []  # rejected before any GitHub call was attempted


def test_track_stage_rejects_invalid_status_name():
    import gtm.run as run_mod

    with pytest.raises(ValueError):
        run_mod._validate_stage_status("fit", "not-a-real-status")


def test_cmd_enrich_prints_displacement_prompt_when_competitor_detected(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(
        company="AeroVironment", website="https://avinc.com", fit_score=87, status="priority",
        case_evidence="ships in a Pelican 1520 case",
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_enrich("teal-demo-displace")

    out = capsys.readouterr().out
    assert "displacement: Pelican 1520" in out
    assert "Pelican 1520" in out

    saved = load_state(tmp_path)
    assert saved[0].competitor == "Pelican 1520"


def test_cmd_enrich_no_displacement_prompt_when_no_competitor(monkeypatch, tmp_path, capsys):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(
        company="Teal Drones", website="https://tealdrones.com", fit_score=87, status="priority",
        case_evidence="ships in a soft backpack",
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_enrich("teal-demo-nodisplace")


def test_cmd_enrich_never_derives_competitor_from_community_signals(monkeypatch, tmp_path, capsys):
    """competitor means "what THIS company ships in today" — draft.py asserts it
    verbatim ("{company} currently ships in a {competitor} case"). community_signals
    cannot support that claim: gtm/enrich.py::_COMPETITOR_QUERY is category-wide with
    no company name in it, so a brand there is generic chatter, and free-form quote
    text also feeds detect_competitor stray digits it reads as model numbers
    ("cracked after 2 flights" -> "Pelican 2")."""
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(
        company="Teal Drones", website="https://tealdrones.com", fit_score=87, status="priority",
        case_evidence="ships in a soft backpack",  # no named brand — the common case
        community_signals=[
            '"Pelican case felt heavy, our drone cracked after 2 flights" (reddit.com)',
            '"SKB foam is fine" (rcgroups.com)',
        ],
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_enrich("teal-demo-no-signal-competitor")

    assert load_state(tmp_path)[0].competitor == ""
    assert "displacement" not in capsys.readouterr().out

    out = capsys.readouterr().out
    assert "displacement" not in out


_QA_BODY = (
    "{{first_name}},\n\nSaw {{company_name}}'s {{trigger_event}} — congrats.\n\n"
    "We build transport cases with foam cut to one airframe, so the aircraft, controller "
    "and batteries each seat in their own cavity. {{reference_customer}} runs our "
    "{{case_line}} line across their lineup.\n\nBad idea to spend 15 minutes on it?\n\n"
    "{{sender_name}}"
)
_QA_BODY_ALT = (
    "{{first_name}},\n\nCurious what {{company_name}} ships {{airframe_name}} in today.\n\n"
    "We're AeroVault — US-made, foam-fit transport cases built around one airframe at a "
    "time, so a tech opens the case and everything sits where it should.\n\n"
    "Worth a short call to see if it is relevant?\n\n{{sender_name}}"
)


_FABRICATED_BODY = (
    "{{first_name}},\n\nSaw {{company_name}}'s launch — congrats.\n\n"
    "{{airframe_name}} travels in a tough portable box today — which surfaces later as a "
    "cracked arm or a gimbal out of true.\n\n{{sender_name}}"
)


def test_cmd_draft_flags_fabricated_pain_before_paying_for_qa(monkeypatch, tmp_path, capsys):
    # The guard is free and qa_check is not, so a fabricated-pain draft must never reach the
    # paid call. cold-0727/Arcsky shipped qa_flag="passed" because nothing checked this.
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Arcsky", website="https://arcsky.com", status="priority",
        buying_signals=["Launched the Xplorer"],
        case_evidence="packs nicely into one tough portable box",
        community_signals=[], competitor_weaknesses=[],
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Arcsky": {
            "c-suite": {
                "draft_initial": {
                    "v1": {"subject": "transport for the new Xplorer", "body": _FABRICATED_BODY},
                    "v2": {"subject": "s2", "body": _QA_BODY_ALT},
                },
            }
        }
    }))

    called = []
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: called.append(1) or "")

    with pytest.raises(CheckpointPending):
        cmd_draft("arcsky-pain-1", str(drafts_path))

    saved = load_state(tmp_path)
    assert "asserts a consequence" in saved[0].drafts_by_tier["c-suite"].qa_flag
    assert called == []  # short-circuited before the paid qa_check

    assert "REDRAFT" in capsys.readouterr().out


def test_cmd_redraft_rechecks_pain_grounding(monkeypatch, tmp_path):
    # Same guard chain in the retry path — a redraft that reintroduces the claim is caught.
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Arcsky", website="https://arcsky.com", status="priority",
        buying_signals=["Launched the Xplorer"],
        case_evidence="packs nicely into one tough portable box",
        community_signals=[], competitor_weaknesses=[],
        drafts_by_tier={"c-suite": DraftSet(
            initial_subject="old subject", qa_flag="asserts a consequence (cracked)",
        )},
    )]
    save_state(prospects, tmp_path)

    drafts_path = tmp_path / "drafts.json"
    drafts_path.write_text(json.dumps({
        "Arcsky": {
            "c-suite": {
                "draft_initial": {
                    "v1": {"subject": "transport for the new Xplorer", "body": _FABRICATED_BODY},
                    "v2": {"subject": "s2", "body": _QA_BODY_ALT},
                },
            }
        }
    }))
    monkeypatch.setattr(run_mod, "qa_check", lambda p, draft, **kw: "")

    cmd_redraft("arcsky-pain-2", str(drafts_path))  # must NOT raise

    saved = load_state(tmp_path)
    assert "asserts a consequence" in saved[0].drafts_by_tier["c-suite"].qa_flag


def test_cmd_enrich_prints_inhouse_displacement_prompt_for_an_oem_enclosure(monkeypatch, tmp_path, capsys):
    # run test-batch-1: Easy Aerial builds its own Drone-in-a-Box housing and got no
    # displacement prompt at all, because only third-party brands were detectable.
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    _stub_enrich_deps(monkeypatch)
    prospects = [Prospect(
        company="Easy Aerial", website="https://easyaerial.com", fit_score=84, status="priority",
        case_evidence="The Sparrow deploys from a weatherproof Drone-in-a-Box enclosure",
    )]
    save_state(prospects, tmp_path)

    with pytest.raises(CheckpointPending):
        cmd_enrich("teal-demo-inhouse")

    out = capsys.readouterr().out
    assert "displacement: drone-in-a-box enclosure" in out
    assert "tooling" in out.lower()

    saved = load_state(tmp_path)
    assert saved[0].inhouse_case == "drone-in-a-box enclosure"
    assert saved[0].competitor == ""  # an OEM build is not a named third-party incumbent


def test_emails_for_prospect_passes_alias_domains_to_the_waterfall():
    # run test-batch-1: Red Cat got 0/3 because only redcatholdings.com was tried,
    # while their press domain is redcat.red.
    from gtm.emails import EmailResult
    from gtm.run import emails_for_prospect

    seen = {}

    def spy(name, domain, **kw):
        seen["domain"] = domain
        seen["domains"] = kw.get("domains")
        return EmailResult(email="j@redcat.red", tier="hunter", status="verified")

    p = Prospect(
        company="Red Cat Holdings", website="https://redcatholdings.com",
        contact_name="Jeff Thompson", status="priority",
        key_news=["Red Cat press release — (https://news.redcat.red/pr/12)"],
    )
    emails_for_prospect(p, waterfall_fn=spy)
    assert seen["domain"] == "redcatholdings.com"
    assert "redcat.red" in seen["domains"]


def test_emails_for_prospect_shows_a_config_gap_instead_of_a_bare_miss():
    from gtm.emails import EmailResult
    from gtm.run import emails_for_prospect

    p = Prospect(company="Red Cat", website="https://redcatholdings.com",
                 contact_name="Jeff Thompson", status="priority")
    emails_for_prospect(p, waterfall_fn=lambda name, domain, **kw: EmailResult(status="no-finder-key"))
    assert p.contact_emails == "- (no-finder-key)"


def test_cmd_output_reports_rows_blocked_by_the_render_gate(monkeypatch, tmp_path, capsys):
    # Run test-batch-1 pushed literal {{tokens}} to the live Sheet with no warning.
    # The gate now blanks those rows — and must say it did.
    import gtm.run as run_mod
    from gtm.schema import DraftSet

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(
        company="Red Cat", website="https://redcatholdings.com", fit_score=87, status="priority",
        contact_name="Jeff Thompson", contact_title="CEO",
        # {{trigger_event}}, not {{sender_name}}: this prospect has no fresh signal,
        # so the token is unfillable from the prospect's own data — the assertion no
        # longer depends on whether the live company/outreach.md happens to be filled.
        drafts_by_tier={"c-suite": DraftSet(initial_body="Hi {{first_name}} — {{trigger_event}}")},
    )]
    save_state(prospects, tmp_path)

    cmd_output("ignored", dry_run=True)

    out = capsys.readouterr().out
    assert "1 contact row blocked" in out
    assert "{{trigger_event}}" in out
    # Only outreach.md's own tokens send the reader to outreach.md (see
    # gtm/output.py::blocked_row_tokens) — a stale signal is not fixable there.
    assert "company/outreach.md" not in out


def test_cmd_output_says_nothing_about_the_gate_when_every_row_renders(monkeypatch, tmp_path, capsys):
    calls = _setup_output_run(monkeypatch, tmp_path)  # noqa: F841 — fixture side effects

    cmd_output("ignored", dry_run=True)

    assert "blocked" not in capsys.readouterr().out
