"""S1 — scrape a URL to clean markdown. crawl4ai primary, auto-fallback chain.

Every scraper is `(url) -> markdown str` or raises ScrapeError. Extraction happens
elsewhere (S2) — this module never returns structured data.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

MIN_MARKDOWN_CHARS = 200  # anything shorter is a block page / error page, not content

FALLBACK_ORDER = ["crawl4ai", "firecrawl", "scrapegraphai", "apify"]

SOCIAL_HOSTS = {"linkedin.com", "twitter.com", "x.com", "instagram.com", "facebook.com"}


def _is_social_host(url: str) -> bool:
    host = urlparse(url).netloc.removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)


class ScrapeError(Exception):
    pass


def scrape_crawl4ai(url: str) -> str:
    import asyncio

    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.content_filter_strategy import PruningContentFilter
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    async def _run() -> str:
        md_generator = DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.45, threshold_type="dynamic", min_word_threshold=5)
        )
        config = CrawlerRunConfig(markdown_generator=md_generator)
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
            if not result.success:
                raise ScrapeError(f"crawl4ai failed: {result.error_message}")
            return result.markdown.fit_markdown or result.markdown.raw_markdown or ""

    return asyncio.run(_run())


def scrape_with_links(url: str) -> tuple[str, list[str]]:
    """crawl4ai only: (fit markdown, internal link hrefs). fit_markdown strips link
    syntax, so CrawlResult.links is the only way to discover subpages."""
    import asyncio

    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.content_filter_strategy import PruningContentFilter
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    async def _run() -> tuple[str, list[str]]:
        md_generator = DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(threshold=0.45, threshold_type="dynamic", min_word_threshold=5)
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=CrawlerRunConfig(markdown_generator=md_generator))
            if not result.success:
                raise ScrapeError(f"crawl4ai failed: {result.error_message}")
            md = result.markdown.fit_markdown or result.markdown.raw_markdown or ""
            hrefs = [l.get("href", "") for l in (result.links or {}).get("internal", []) if l.get("href")]
            return md, hrefs

    return asyncio.run(_run())


PRODUCT_PATH = re.compile(r"/(products?|drones?|uas|systems?|hardware|fleet|aircraft)(/|$)", re.I)
# nav/footer boilerplate that never holds product specs
BOILERPLATE_PATH = re.compile(
    r"/(about|company|contact|press|news|blog|events|careers|support|privacy|terms|legal"
    r"|login|cart|account|use-cases|resources|faq)([-_/]|$)",
    re.I,
)


def pick_product_links(hrefs: list[str], base_url: str, limit: int = 2) -> list[str]:
    base = urlparse(base_url).netloc.removeprefix("www.")

    def internal(h: str) -> bool:
        n = urlparse(h).netloc
        return not n or n.removeprefix("www.") == base

    keyword, shallow = [], []
    for h in hrefs:
        if not internal(h):
            continue
        path = urlparse(h).path
        if PRODUCT_PATH.search(path) and h not in keyword:
            keyword.append(h)
        elif (
            path.strip("/")
            and len(path.strip("/").split("/")) <= 2
            and not BOILERPLATE_PATH.search(path)
            and h not in shallow
        ):
            shallow.append(h)
    return (keyword or shallow)[:limit]


def scrape_deep(url: str, preferred: str = "crawl4ai", *, fetch=scrape_with_links, fallback=None) -> str:
    """Homepage + up to 2 product pages, concatenated. Falls back to plain scrape()."""
    fallback = fallback if fallback is not None else scrape
    try:
        md, hrefs = fetch(url)
    except ScrapeError:
        return fallback(url, preferred=preferred)
    parts = [md]
    for link in pick_product_links(hrefs, url):
        try:
            parts.append(fetch(link)[0])
        except ScrapeError as e:
            log.warning("deep scrape of %s failed: %s", link, e)
    combined = "\n\n".join(parts)
    if len(combined.strip()) < MIN_MARKDOWN_CHARS:
        return fallback(url, preferred=preferred)
    return combined


def scrape_firecrawl(url: str) -> str:
    """Fallback #1: Firecrawl managed scrape API. Handles anti-bot/Cloudflare that
    crawl4ai can't (see docs/tools/firecrawl.md — Red Cat got Cloudflare-blocked)."""
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise ScrapeError("firecrawl: no API key configured (optional fallback)")

    try:
        response = requests.post(
            "https://api.firecrawl.dev/v2/scrape",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"url": url, "formats": ["markdown"]},
        )
    except requests.RequestException as e:
        raise ScrapeError(f"firecrawl: request failed: {e}") from e

    if not response.ok:
        raise ScrapeError(f"firecrawl: HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as e:
        raise ScrapeError(f"firecrawl: invalid JSON response: {e}") from e

    if not payload.get("success"):
        raise ScrapeError(f"firecrawl: success=false ({payload})")

    try:
        return payload["data"]["markdown"]
    except (KeyError, TypeError) as e:
        raise ScrapeError(f"firecrawl: missing data.markdown in response: {e}") from e


def _extract_scrapegraphai_markdown(payload: dict) -> str | None:
    """Try each candidate key path in order, return the first non-empty str found.

    UNCONFIRMED: ScrapeGraphAI's V2 `/api/scrape` response shape wasn't visible in the
    primary docs fetch (docs.scrapegraphai.com 404'd on the endpoint pages this session) —
    see docs/tools/scrapegraphai.md. This candidate list is our best guess pending Task 3.5's
    live smoke test, which should confirm/prune it against a real response.
    """
    candidates = [
        lambda p: p["result"] if isinstance(p.get("result"), str) else None,
        lambda p: p["markdown"],
        lambda p: p["data"]["markdown"],
        lambda p: p["result"]["markdown"],
        lambda p: p["content"],
    ]
    for candidate in candidates:
        try:
            value = candidate(payload)
        except (KeyError, TypeError):
            continue
        if isinstance(value, str) and value.strip():
            return value
    return None


def scrape_scrapegraphai(url: str) -> str:
    """Fallback #2: ScrapeGraphAI managed scrape API — last generic resort in the chain
    (see docs/tools/scrapegraphai.md). V2 `/api/scrape` with formats=[{"type": "markdown"}];
    do NOT use the deprecated V1 `markdownify` endpoint."""
    api_key = os.environ.get("SGAI_API_KEY")
    if not api_key:
        raise ScrapeError("scrapegraphai: no API key configured")

    try:
        response = requests.post(
            "https://v2-api.scrapegraphai.com/api/scrape",
            headers={
                "SGAI-APIKEY": api_key,
                "Content-Type": "application/json",
            },
            json={"url": url, "formats": [{"type": "markdown"}]},
        )
    except requests.RequestException as e:
        raise ScrapeError(f"scrapegraphai: request failed: {e}") from e

    if not response.ok:
        raise ScrapeError(f"scrapegraphai: HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as e:
        raise ScrapeError(f"scrapegraphai: invalid JSON response: {e}") from e

    markdown = _extract_scrapegraphai_markdown(payload)
    if markdown is None:
        raise ScrapeError(f"scrapegraphai: no markdown in response ({payload})")
    return markdown


def scrape_apify(url: str) -> str:
    """Fallback #3: Apify managed actor `apify/website-content-crawler`, driven via the
    `apify` CLI as a subprocess — NOT HTTP, NOT the MCP server (see docs/tools/apify.md).
    Last resort for generic sites; later the mandatory route for social hosts (Task 3.4)."""
    if not shutil.which("apify"):
        raise ScrapeError("apify: CLI not installed (optional fallback)")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
            json.dump(
                {
                    "startUrls": [{"url": url}],
                    "crawlerType": "adaptive",
                    "maxCrawlPages": 1,
                    "saveMarkdown": True,
                },
                tmp,
            )

        try:
            # UNCONFIRMED (docs/tools/apify.md): the input flag may be `-i <file>`,
            # `-i <inline-json>`, or `-f <file>` depending on installed CLI version.
            # Using `-i <tmpfile-path>` per the brief; Task 3.5's live smoke is the
            # first real `apify` invocation and will confirm or correct this form.
            result = subprocess.run(
                ["apify", "call", "apify/website-content-crawler", "-i", tmp_path, "--output-dataset"],
                capture_output=True,
                text=True,
            )
        except (subprocess.SubprocessError, OSError) as e:
            raise ScrapeError(f"apify: subprocess failed: {e}") from e

        if result.returncode != 0:
            stderr_line = (result.stderr or "").strip().splitlines()[:1]
            stderr_line = stderr_line[0] if stderr_line else ""
            raise ScrapeError(f"apify: CLI exited {result.returncode}: {stderr_line}")

        try:
            items = json.loads(result.stdout)
        except (ValueError, json.JSONDecodeError) as e:
            raise ScrapeError(f"apify: invalid JSON output: {e}") from e

        parts = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            text = item.get("markdown") or item.get("text")
            if text:
                parts.append(text)

        if not parts:
            raise ScrapeError("apify: empty dataset")

        return "\n\n".join(parts)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def _not_configured(name: str):
    def _scraper(url: str) -> str:
        raise ScrapeError(f"{name}: no API key configured (optional fallback)")

    return _scraper


SCRAPERS = {
    "crawl4ai": scrape_crawl4ai,
    "firecrawl": scrape_firecrawl,
    "apify": scrape_apify,
    "scrapegraphai": scrape_scrapegraphai,
}


def scrape(url: str, preferred: str = "crawl4ai", registry: dict | None = None) -> str:
    """Try `preferred` first, then the rest of FALLBACK_ORDER. Log & skip failures.

    Social hosts (LinkedIn, Twitter/X, Instagram, Facebook) always route to Apify
    first — the only scraper of the four that can render/authenticate those sites.
    This override applies regardless of `preferred` or a custom `registry`.
    """
    registry = registry if registry is not None else SCRAPERS
    if _is_social_host(url):
        preferred = "apify"
    chain = [preferred] + [n for n in FALLBACK_ORDER if n != preferred]
    errors = []
    for name in chain:
        fn = registry.get(name)
        if fn is None:
            continue
        try:
            md = fn(url)
        except ScrapeError as e:
            log.warning("scraper %s failed on %s: %s", name, url, e)
            errors.append(f"{name}: {e}")
            continue
        if len(md.strip()) < MIN_MARKDOWN_CHARS:
            log.warning("scraper %s returned junk (%d chars) for %s", name, len(md.strip()), url)
            errors.append(f"{name}: markdown too short ({len(md.strip())} chars)")
            continue
        return md
    raise ScrapeError(f"all scrapers failed for {url}: " + "; ".join(errors))
