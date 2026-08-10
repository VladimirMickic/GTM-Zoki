"""S1 — scraper orchestration: preferred-first, auto-fallback, markdown quality gate."""
import json
import subprocess

import pytest

from gtm.scrape import (
    ScrapeError,
    scrape,
    scrape_apify,
    scrape_deep,
    scrape_firecrawl,
    scrape_scrapegraphai,
    sitemap_urls,
)


def good(url):
    return "# Teal Drones\n\n" + "Rugged UAS for defense. " * 20


def bad(url):
    raise ScrapeError("boom")


def junk(url):
    return "403"  # too short to be a real page


def test_uses_preferred_scraper_first():
    calls = []
    registry = {
        "crawl4ai": lambda u: calls.append("crawl4ai") or good(u),
        "firecrawl": lambda u: calls.append("firecrawl") or good(u),
    }
    md = scrape("https://tealdrones.com", preferred="crawl4ai", registry=registry)
    assert md.startswith("# Teal Drones")
    assert calls == ["crawl4ai"]


def test_falls_back_when_preferred_fails():
    registry = {"crawl4ai": bad, "firecrawl": good}
    md = scrape("https://tealdrones.com", preferred="crawl4ai", registry=registry)
    assert "Rugged UAS" in md


def test_falls_back_on_junk_markdown():
    registry = {"crawl4ai": junk, "firecrawl": good}
    md = scrape("https://tealdrones.com", preferred="crawl4ai", registry=registry)
    assert "Rugged UAS" in md


def test_raises_when_all_scrapers_fail():
    registry = {"crawl4ai": bad, "firecrawl": junk}
    with pytest.raises(ScrapeError, match="all scrapers failed"):
        scrape("https://tealdrones.com", preferred="crawl4ai", registry=registry)


def test_preferred_can_be_any_scraper_in_chain():
    calls = []
    registry = {
        "crawl4ai": lambda u: calls.append("crawl4ai") or good(u),
        "firecrawl": lambda u: calls.append("firecrawl") or good(u),
    }
    scrape("https://tealdrones.com", preferred="firecrawl", registry=registry)
    assert calls == ["firecrawl"]


def test_pick_product_links_prefers_keyword_paths():
    from gtm.scrape import pick_product_links

    hrefs = [
        "https://tealdrones.com/blog/post",
        "https://tealdrones.com/products/black-widow/",
        "https://other.com/products/x",  # external — skipped
        "https://tealdrones.com/drones/hellcat",
        "https://tealdrones.com/products/fang",  # over the cap of 2
    ]
    picked = pick_product_links(hrefs, "https://tealdrones.com/")
    assert picked == [
        "https://tealdrones.com/products/black-widow/",
        "https://tealdrones.com/drones/hellcat",
    ]


def test_pick_product_links_falls_back_to_shallow_non_boilerplate_paths():
    from gtm.scrape import pick_product_links

    # real tealdrones.com shape: no /products/ URLs at all
    hrefs = [
        "https://tealdrones.com/company/about",
        "https://tealdrones.com/contact",
        "https://tealdrones.com/black-widow",
        "https://tealdrones.com/use-cases/defense",
        "https://tealdrones.com/hellcat",
        "https://tealdrones.com/privacy",
    ]
    picked = pick_product_links(hrefs, "https://tealdrones.com/")
    assert picked == ["https://tealdrones.com/black-widow", "https://tealdrones.com/hellcat"]


def test_pick_product_links_rejects_team_media_and_download_pages():
    from gtm.scrape import pick_product_links

    # real neros.tech shape: no product page exists at all, specs are gated behind
    # /protected-downloads. Every candidate here is boilerplate — picking any of them
    # burns a crawl and pads the extraction prompt with junk.
    hrefs = [
        "https://www.neros.tech/media",
        "https://www.neros.tech/teams",
        "https://www.neros.tech/news",
        "https://www.neros.tech/protected-downloads",
        "https://www.neros.tech/legal/privacy-policy",
        "https://www.neros.tech/articles/neros-launches-uk-subsidiary-with-investment",
    ]
    assert pick_product_links(hrefs, "https://www.neros.tech/") == []


def test_pick_product_links_ranks_model_like_paths_above_bare_nouns():
    """Live skyfront.com run took /magniphy (a payload) over /perimeter-8 (the drone)
    purely on nav order. Model pages carry a digit or a hyphenated name; nav pages are
    bare nouns."""
    from gtm.scrape import pick_product_links

    hrefs = [
        "https://skyfront.com/accessories",
        "https://skyfront.com/integration",
        "https://skyfront.com/magniphy",
        "https://skyfront.com/perimeter-8",
        "https://skyfront.com/radios",
    ]
    picked = pick_product_links(hrefs, "https://skyfront.com/")
    assert picked[0] == "https://skyfront.com/perimeter-8"


def test_pick_product_links_ranking_is_stable_within_a_tier():
    """Ranking only promotes model-like paths — ties keep nav order, which is still the
    best relevance signal we have.

    Known limit: a single-word model name (/hellcat) is indistinguishable from a nav
    noun and gets demoted below hyphenated siblings. Only bites when 3+ candidates
    compete for the 2 slots; both tiers are still real candidates, so the cost is
    picking a different product page, never a junk one.
    """
    from gtm.scrape import pick_product_links

    hrefs = [
        "https://tealdrones.com/black-widow",
        "https://tealdrones.com/hellcat",
        "https://tealdrones.com/golden-eagle",
    ]
    picked = pick_product_links(hrefs, "https://tealdrones.com/")
    assert picked == ["https://tealdrones.com/black-widow", "https://tealdrones.com/golden-eagle"]


def test_pick_product_links_ranking_never_outranks_a_keyword_path():
    """An explicit /products/ or /drones/ path beats a model-like guess every time.

    It out*ranks* it — it no longer excludes it (see the top-up test below).
    """
    from gtm.scrape import pick_product_links

    hrefs = ["https://t.com/perimeter-8", "https://t.com/products/hawk"]
    picked = pick_product_links(hrefs, "https://t.com/")
    assert picked[0] == "https://t.com/products/hawk"


def test_pick_product_links_tops_up_spare_slots_with_shallow_candidates():
    """Live hyl.io run (2026-07-29) burned only 1 of 2 crawl slots: the single keyword
    path /hardware suppressed the shallow tier entirely, so the named model pages
    (/pegasus, /ares) were never fetched and extraction found no airframe names, which
    blocked {{airframe_name}} at the ship gate. A keyword hit should rank first, not
    veto the leftover slot.
    """
    from gtm.scrape import pick_product_links

    hrefs = [
        "https://hyl.io/hardware",
        "https://hyl.io/about",
        "https://hyl.io/pegasus",
        "https://hyl.io/ares",
    ]
    picked = pick_product_links(hrefs, "https://hyl.io/")
    assert picked == ["https://hyl.io/hardware", "https://hyl.io/pegasus"]


def test_pick_product_links_keyword_tier_promotes_the_model_page_over_the_index():
    """/products is the catalog landing page, /products/black-widow has the specs. Both
    are keyword hits; the one named after an aircraft is worth more."""
    from gtm.scrape import pick_product_links

    hrefs = [
        "https://t.com/products",
        "https://t.com/products/black-widow",
    ]
    picked = pick_product_links(hrefs, "https://t.com/")
    assert picked[0] == "https://t.com/products/black-widow"


def test_pick_product_links_top_up_never_duplicates_or_exceeds_the_cap():
    from gtm.scrape import pick_product_links

    hrefs = ["https://t.com/products/hawk", "https://t.com/drones/owl", "https://t.com/pegasus"]
    picked = pick_product_links(hrefs, "https://t.com/")
    assert picked == ["https://t.com/products/hawk", "https://t.com/drones/owl"]
    assert len(picked) == len(set(picked))


def test_pick_product_links_keyword_only_still_excludes_the_shallow_tier():
    """scrape_deep's sitemap pass is keyword_only — a sitemap has no nav order, so a
    shallow guess from it ranks nothing and must not be topped up."""
    from gtm.scrape import pick_product_links

    hrefs = ["https://hyl.io/hardware", "https://hyl.io/pegasus"]
    picked = pick_product_links(hrefs, "https://hyl.io/", keyword_only=True)
    assert picked == ["https://hyl.io/hardware"]


def test_scrape_deep_skips_subpage_crawls_when_nothing_worth_fetching():
    from gtm.scrape import scrape_deep

    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return "HOME " * 60, ["https://n.tech/teams", "https://n.tech/media"]

    md = scrape_deep("https://n.tech/", fetch=fake_fetch, sitemap_fn=lambda u: [])
    assert fetched == ["https://n.tech/"]  # homepage only, no wasted crawls
    assert "HOME" in md


def test_scrape_deep_prefers_sitemap_product_pages_over_homepage_links():
    from gtm.scrape import scrape_deep

    def fake_fetch(url):
        if url == "https://t.com/":
            return "HOME " * 60, ["https://t.com/about-us-story"]
        return f"PAGE:{url} " * 40, []

    md = scrape_deep(
        "https://t.com/",
        fetch=fake_fetch,
        sitemap_fn=lambda u: ["https://t.com/blog/x", "https://t.com/products/hawk"],
    )
    assert "PAGE:https://t.com/products/hawk" in md


def test_scrape_deep_ignores_sitemap_without_product_paths():
    """A sitemap in site-map order (not nav order) is a worse ranking signal than the
    homepage's own links — only its explicit product-path hits are trusted."""
    from gtm.scrape import scrape_deep

    def fake_fetch(url):
        if url == "https://t.com/":
            return "HOME " * 60, ["https://t.com/perimeter-8"]
        return f"PAGE:{url} " * 40, []

    md = scrape_deep(
        "https://t.com/",
        fetch=fake_fetch,
        sitemap_fn=lambda u: ["https://t.com/learn", "https://t.com/image-license"],
    )
    assert "PAGE:https://t.com/perimeter-8" in md
    assert "learn" not in md


def test_sitemap_urls_parses_loc_entries(monkeypatch):
    import gtm.scrape as scrape_mod
    from gtm.scrape import sitemap_urls

    class Resp:
        ok = True
        text = (
            '<?xml version="1.0"?><urlset><url><loc>https://s.com/perimeter-8</loc></url>'
            "<url><loc>https://s.com/payloads</loc></url></urlset>"
        )

    monkeypatch.setattr(scrape_mod.requests, "get", lambda *a, **k: Resp())
    assert sitemap_urls("https://s.com/") == ["https://s.com/perimeter-8", "https://s.com/payloads"]


def test_sitemap_urls_returns_empty_when_missing(monkeypatch):
    """neros.tech has no sitemap.xml — a 404 or a network error is normal, never fatal."""
    import gtm.scrape as scrape_mod
    from gtm.scrape import sitemap_urls

    def boom(*a, **k):
        raise scrape_mod.requests.RequestException("no route")

    monkeypatch.setattr(scrape_mod.requests, "get", boom)
    assert sitemap_urls("https://www.neros.tech/") == []


def test_scrape_deep_appends_product_pages():
    from gtm.scrape import scrape_deep

    def fake_fetch(url):
        if url == "https://t.com/":
            return "HOME " * 60, ["https://t.com/products/a", "https://t.com/blog/x"]
        return f"PAGE:{url} " * 40, []

    md = scrape_deep("https://t.com/", fetch=fake_fetch)
    assert "HOME" in md
    assert "PAGE:https://t.com/products/a" in md


def test_scrape_deep_falls_back_to_plain_scrape_on_fetch_failure():
    from gtm.scrape import scrape_deep

    def broken_fetch(url):
        raise ScrapeError("crawl4ai down")

    md = scrape_deep("https://t.com/", fetch=broken_fetch, fallback=lambda u, preferred: good(u))
    assert "Rugged UAS" in md


def test_default_registry_has_full_fallback_chain():
    from gtm.scrape import FALLBACK_ORDER, SCRAPERS

    assert FALLBACK_ORDER == ["crawl4ai", "firecrawl", "scrapegraphai", "apify"]
    assert set(FALLBACK_ORDER) <= set(SCRAPERS)


def test_social_host_routes_to_apify_first():
    calls = []
    registry = {
        "apify": lambda u: calls.append("apify") or good(u),
        "crawl4ai": lambda u: calls.append("crawl4ai") or good(u),
    }
    md = scrape("https://www.linkedin.com/company/teal", registry=registry)
    assert md.startswith("# Teal Drones")
    assert calls == ["apify"]
    assert "crawl4ai" not in calls


def test_non_social_host_does_not_route_to_apify():
    calls = []
    registry = {
        "crawl4ai": lambda u: calls.append("crawl4ai") or good(u),
        "apify": lambda u: calls.append("apify") or good(u),
    }
    md = scrape("https://tealdrones.com", registry=registry)
    assert md.startswith("# Teal Drones")
    assert calls == ["crawl4ai"]


def test_social_host_subdomain_routes_to_apify():
    calls = []
    registry = {
        "apify": lambda u: calls.append("apify") or good(u),
        "crawl4ai": lambda u: calls.append("crawl4ai") or good(u),
    }
    md = scrape("https://m.facebook.com/tealdrones", registry=registry)
    assert md.startswith("# Teal Drones")
    assert calls == ["apify"]


class _FakeResponse:
    def __init__(self, json_data, status_code=200, ok=True):
        self._json_data = json_data
        self.status_code = status_code
        self.ok = ok

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if not self.ok:
            raise Exception(f"HTTP {self.status_code}")


def test_scrape_firecrawl_returns_markdown_on_success(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")

    markdown = "# Teal Drones\n\n" + "Rugged UAS for defense. " * 20

    def fake_post(url, headers=None, json=None, **kwargs):
        assert url == "https://api.firecrawl.dev/v2/scrape"
        assert headers["Authorization"] == "Bearer fc-test-key"
        assert json["url"] == "https://tealdrones.com"
        assert json["formats"] == ["markdown"]
        return _FakeResponse({"success": True, "data": {"markdown": markdown}})

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    result = scrape_firecrawl("https://tealdrones.com")
    assert result == markdown


def test_scrape_firecrawl_raises_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    with pytest.raises(ScrapeError):
        scrape_firecrawl("https://tealdrones.com")


def test_scrape_firecrawl_raises_on_failed_response(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")

    def fake_post(url, headers=None, json=None, **kwargs):
        return _FakeResponse({"success": False}, status_code=401, ok=False)

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    with pytest.raises(ScrapeError):
        scrape_firecrawl("https://tealdrones.com")


def test_scrape_scrapegraphai_returns_markdown_on_success(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("SGAI_API_KEY", "sgai-test-key")

    markdown = "# Teal Drones\n\n" + "Rugged UAS for defense. " * 20

    def fake_post(url, headers=None, json=None, **kwargs):
        assert url == "https://v2-api.scrapegraphai.com/api/scrape"
        assert headers["SGAI-APIKEY"] == "sgai-test-key"
        assert headers["Content-Type"] == "application/json"
        assert json["url"] == "https://tealdrones.com"
        assert json["formats"] == [{"type": "markdown"}]
        return _FakeResponse({"request_id": "abc", "status": "completed", "result": markdown})

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    result = scrape_scrapegraphai("https://tealdrones.com")
    assert result == markdown


def test_scrape_scrapegraphai_raises_when_no_api_key(monkeypatch):
    monkeypatch.delenv("SGAI_API_KEY", raising=False)
    monkeypatch.delenv("SCRAPEGRAPHAI_API_KEY", raising=False)

    with pytest.raises(ScrapeError):
        scrape_scrapegraphai("https://tealdrones.com")


def test_scrape_scrapegraphai_accepts_the_env_name_this_repo_actually_uses(monkeypatch):
    """.env spells the key SCRAPEGRAPHAI_API_KEY, the vendor spells it SGAI_API_KEY.
    Reading only the vendor name left a configured key unread and the fallback dead."""
    import gtm.scrape as scrape_mod

    monkeypatch.delenv("SGAI_API_KEY", raising=False)
    monkeypatch.setenv("SCRAPEGRAPHAI_API_KEY", "sgai-dotenv-key")

    markdown = "# Teal Drones\n\n" + "Rugged UAS for defense. " * 20
    seen = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        seen["key"] = headers["SGAI-APIKEY"]
        return _FakeResponse({"status": "completed", "result": markdown})

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    assert scrape_scrapegraphai("https://tealdrones.com") == markdown
    assert seen["key"] == "sgai-dotenv-key"


def test_scrape_scrapegraphai_prefers_the_vendor_env_name(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("SGAI_API_KEY", "sgai-vendor-key")
    monkeypatch.setenv("SCRAPEGRAPHAI_API_KEY", "sgai-dotenv-key")

    markdown = "# Teal Drones\n\n" + "Rugged UAS for defense. " * 20
    seen = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        seen["key"] = headers["SGAI-APIKEY"]
        return _FakeResponse({"status": "completed", "result": markdown})

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    scrape_scrapegraphai("https://tealdrones.com")
    assert seen["key"] == "sgai-vendor-key"


def test_scrape_scrapegraphai_reads_the_real_v2_response_shape(monkeypatch):
    """Live-confirmed 2026-07-30: V2 /api/scrape returns results.markdown.data as a LIST
    of chunks. Every earlier guess assumed a single string, so real 200s were reported as
    'no markdown in response'."""
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("SGAI_API_KEY", "sgai-test-key")

    chunks = ["# Teal Drones", "Rugged UAS for defense. " * 20]

    def fake_post(url, headers=None, json=None, **kwargs):
        return _FakeResponse(
            {
                "id": "01f01dd3",
                "results": {"markdown": {"data": chunks}},
                "metadata": {"contentType": "text/html"},
            }
        )

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    assert scrape_scrapegraphai("https://tealdrones.com") == "\n\n".join(chunks)


def test_scrape_scrapegraphai_accepts_an_unwrapped_markdown_chunk(monkeypatch):
    """A bare string where the list is expected must not be joined character-by-character."""
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("SGAI_API_KEY", "sgai-test-key")
    markdown = "# Teal Drones\n\n" + "Rugged UAS for defense. " * 20

    def fake_post(url, headers=None, json=None, **kwargs):
        return _FakeResponse({"results": {"markdown": {"data": markdown}}})

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    assert scrape_scrapegraphai("https://tealdrones.com") == markdown


def test_scrape_scrapegraphai_raises_when_no_markdown_key_found(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("SGAI_API_KEY", "sgai-test-key")

    def fake_post(url, headers=None, json=None, **kwargs):
        return _FakeResponse({"request_id": "abc", "status": "completed"})

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    with pytest.raises(ScrapeError):
        scrape_scrapegraphai("https://tealdrones.com")


def test_scrape_scrapegraphai_raises_on_failed_response(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setenv("SGAI_API_KEY", "sgai-test-key")

    def fake_post(url, headers=None, json=None, **kwargs):
        return _FakeResponse({"error": "unauthorized"}, status_code=401, ok=False)

    monkeypatch.setattr(scrape_mod.requests, "post", fake_post)

    with pytest.raises(ScrapeError):
        scrape_scrapegraphai("https://tealdrones.com")


def test_scrape_apify_returns_markdown_on_success(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    markdown = "# Something\n\n" + "enough text to pass the length gate. " * 10
    calls = []

    def fake_run(args, capture_output=None, text=None, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps([{"markdown": markdown}]), stderr="")

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    result = scrape_apify("https://tealdrones.com")
    assert result == markdown
    assert len(calls) == 1
    argv = calls[0]
    assert "apify" in argv
    assert "call" in argv
    assert "apify/website-content-crawler" in argv
    assert "--output-dataset" in argv
    # apify-cli 1.7.1: -i is INLINE JSON, a file path must go through -f/--input-file.
    assert "-i" not in argv
    assert argv[argv.index("-f") + 1].endswith(".json")
    # Without --silent the actor's run logs land on stdout and the JSON parse dies.
    assert "--silent" in argv


def test_scrape_apify_bounds_the_call_with_a_timeout(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    seen = {}

    def fake_run(args, capture_output=None, text=None, timeout=None, **kwargs):
        seen["timeout"] = timeout
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps([{"markdown": "x " * 200}]), stderr=""
        )

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    scrape_apify("https://tealdrones.com")
    assert seen["timeout"] == scrape_mod.APIFY_TIMEOUT_SECONDS


def test_scrape_apify_uses_a_dataset_printed_before_the_timeout(monkeypatch):
    """The CLI can linger long after printing the dataset — if the JSON is already
    there the scrape succeeded, and throwing it away would waste the actor run."""
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    markdown = "# Something\n\n" + "enough text to pass the length gate. " * 10

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(
            args, 180, output=json.dumps([{"markdown": markdown}]), stderr=""
        )

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    assert scrape_apify("https://tealdrones.com") == markdown


def test_scrape_apify_raises_when_it_times_out_with_no_output(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 180, output="", stderr="")

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    with pytest.raises(ScrapeError, match="timed out"):
        scrape_apify("https://tealdrones.com")


def test_scrape_apify_handles_bytes_output_on_timeout(monkeypatch):
    """TimeoutExpired.stdout is bytes unless text=True reached the child — decode it
    rather than crashing with a TypeError outside the ScrapeError contract."""
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    markdown = "# Something\n\n" + "enough text to pass the length gate. " * 10

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(
            args, 180, output=json.dumps([{"markdown": markdown}]).encode(), stderr=b""
        )

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    assert scrape_apify("https://tealdrones.com") == markdown


def test_scrape_apify_raises_when_cli_not_installed(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: None)

    called = []
    monkeypatch.setattr(scrape_mod.subprocess, "run", lambda *a, **kw: called.append(1))

    with pytest.raises(ScrapeError):
        scrape_apify("https://tealdrones.com")
    assert called == []


def test_scrape_apify_raises_on_nonzero_exit(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    def fake_run(args, capture_output=None, text=None, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="not logged in")

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    with pytest.raises(ScrapeError):
        scrape_apify("https://tealdrones.com")


def test_scrape_apify_raises_on_empty_dataset(monkeypatch):
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    def fake_run(args, capture_output=None, text=None, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    with pytest.raises(ScrapeError, match="empty dataset"):
        scrape_apify("https://tealdrones.com")


def test_scrape_apify_raises_scrape_error_on_non_dict_dataset_items(monkeypatch):
    """Non-dict items (bad actor config, future CLI version, stray log line mixed into
    the dataset) must not escape as AttributeError — only ScrapeError may leave
    scrape_apify (log & skip contract in scrape())."""
    import gtm.scrape as scrape_mod

    monkeypatch.setattr(scrape_mod.shutil, "which", lambda name: "/usr/local/bin/apify")

    def fake_run(args, capture_output=None, text=None, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(["not a dict", {"markdown": ""}, None]), stderr=""
        )

    monkeypatch.setattr(scrape_mod.subprocess, "run", fake_run)

    with pytest.raises(ScrapeError):
        scrape_apify("https://tealdrones.com")


# 2026-08-10, Strix run gtm-helper_eea7 (CWE-918): scrape targets come from the brief and
# from discovery, so the scrapers themselves refuse a non-public destination — the fetch
# must not happen at all, not merely be discarded afterwards.


def test_scrape_refuses_a_loopback_target_before_calling_any_scraper():
    registry = {"crawl4ai": lambda u: pytest.fail("must not fetch a blocked target")}
    with pytest.raises(ScrapeError, match="blocked target"):
        scrape("http://127.0.0.1:8080/admin", registry=registry, lookup=lambda h: "127.0.0.1")


def test_scrape_deep_refuses_a_private_target_before_fetching():
    def fetch(url):
        pytest.fail("must not fetch a blocked target")

    with pytest.raises(ScrapeError, match="blocked target"):
        scrape_deep("https://intranet.example/", fetch=fetch, lookup=lambda h: "10.0.0.5")


def test_sitemap_urls_returns_nothing_for_a_blocked_target(monkeypatch):
    def boom(*a, **kw):
        pytest.fail("must not request a blocked target")

    monkeypatch.setattr("gtm.scrape.requests.get", boom)
    assert sitemap_urls("http://169.254.169.254/", lookup=lambda h: "169.254.169.254") == []


def test_scrape_still_runs_for_a_public_target():
    registry = {"crawl4ai": good}
    md = scrape("https://tealdrones.com", registry=registry, lookup=lambda h: "93.184.216.34")
    assert "Rugged UAS" in md
