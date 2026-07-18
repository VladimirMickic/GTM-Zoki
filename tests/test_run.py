"""S7b — orchestrator: state, per-company log&skip, fit/signal merges."""
from gtm.extract import DroneExtraction
from gtm.fit import FitResult
from gtm.run import company_from_url, load_state, merge_fit, merge_signals, process_company, save_state
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
