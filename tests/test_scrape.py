"""S1 — scraper orchestration: preferred-first, auto-fallback, markdown quality gate."""
import pytest

from gtm.scrape import ScrapeError, scrape, scrape_firecrawl


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
        "scrapling": lambda u: calls.append("scrapling") or good(u),
    }
    scrape("https://tealdrones.com", preferred="scrapling", registry=registry)
    assert calls == ["scrapling"]


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

    assert FALLBACK_ORDER == ["crawl4ai", "firecrawl", "scrapling", "apify", "scrapegraphai"]
    assert set(FALLBACK_ORDER) <= set(SCRAPERS)


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
