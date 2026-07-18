"""S1 — scrape a URL to clean markdown. crawl4ai primary, auto-fallback chain.

Every scraper is `(url) -> markdown str` or raises ScrapeError. Extraction happens
elsewhere (S2) — this module never returns structured data.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MIN_MARKDOWN_CHARS = 200  # anything shorter is a block page / error page, not content

FALLBACK_ORDER = ["crawl4ai", "firecrawl", "scrapling", "apify", "scrapegraphai"]


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


def _not_configured(name: str):
    def _scraper(url: str) -> str:
        raise ScrapeError(f"{name}: no API key configured (optional fallback)")

    return _scraper


SCRAPERS = {
    "crawl4ai": scrape_crawl4ai,
    "firecrawl": _not_configured("firecrawl"),
    "scrapling": _not_configured("scrapling"),
    "apify": _not_configured("apify"),
    "scrapegraphai": _not_configured("scrapegraphai"),
}


def scrape(url: str, preferred: str = "crawl4ai", registry: dict | None = None) -> str:
    """Try `preferred` first, then the rest of FALLBACK_ORDER. Log & skip failures."""
    registry = registry if registry is not None else SCRAPERS
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
