"""S7b — orchestrator: state, per-company log&skip, fit/signal merges."""
import json

import pytest

from gtm.brief import load_frozen
from gtm.control import CheckpointPending
from gtm.extract import DroneExtraction
from gtm.fit import FitResult
from gtm.run import (
    cmd_enrich,
    cmd_fit,
    cmd_output,
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
from gtm.schema import Prospect


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
    merge_signals(ps, {"A": {"buying_signals": ["won contract"], "outreach_angle": "case for new drone"}})
    assert ps[0].buying_signals == ["won contract"]
    assert ps[0].outreach_angle == "case for new drone"


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
            "draft_initial": {
                "v1": {"subject": "Case built for the Teal 2?", "body": "hook v1"},
                "v2": {"subject": "US-made case, Teal-sized", "body": "hook v2"},
            },
            "draft_followup": {
                "v1": {"subject": "Following up", "body": "follow v1"},
                "v2": {"subject": "One more try", "body": "follow v2"},
            },
        }
    }
    merge_drafts(prospects, raw)
    p = prospects[0]
    assert p.draft_initial_subject == "Case built for the Teal 2?"
    assert p.draft_initial_body == "hook v1"
    assert p.draft_initial_subject_alt == "US-made case, Teal-sized"
    assert p.draft_initial_body_alt == "hook v2"
    assert p.draft_followup_subject == "Following up"
    assert p.draft_followup_body_alt == "follow v2"


def test_merge_drafts_skips_companies_not_in_raw():
    prospects = [Prospect(company="Untouched Co", website="https://x.com", status="priority")]
    merge_drafts(prospects, {})
    assert prospects[0].draft_initial_subject == ""


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
    emails_for_prospect(p, waterfall_fn=lambda name, domain: results[name])
    assert p.contact_emails == "blake@brincdrones.com (verified); -"


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

    calls = {"push": 0}
    monkeypatch.setattr(
        output_mod, "push_to_sheet", lambda *a, **k: calls.__setitem__("push", calls["push"] + 1)
    )
    return calls


def test_cmd_output_dry_run_skips_sheet_push_but_writes_csv(monkeypatch, tmp_path):
    calls = _setup_output_run(monkeypatch, tmp_path)

    cmd_output("ignored", dry_run=True)

    assert calls["push"] == 0
    assert (tmp_path / "prospects.csv").exists()


def test_cmd_output_live_still_pushes_to_sheet(monkeypatch, tmp_path):
    calls = _setup_output_run(monkeypatch, tmp_path)

    cmd_output("ignored")

    assert calls["push"] == 1
    assert (tmp_path / "prospects.csv").exists()


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
    assert saved[0].segment == "defense-ndaa-win"  # assigned before the checkpoint fired


def test_cmd_segment_no_checkpoint_when_no_priority_or_keep(monkeypatch, tmp_path):
    import gtm.run as run_mod

    monkeypatch.setattr(run_mod, "run_dir", lambda run: tmp_path)
    prospects = [Prospect(company="Dropped Co", website="https://x.com", status="drop")]
    save_state(prospects, tmp_path)

    cmd_segment("teal-demo-9")  # must NOT raise — nothing needs a draft prompt


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
