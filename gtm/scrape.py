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

# Apify's CLI waits on a remote run: the actor itself finishes in seconds, but the
# call can sit for minutes on platform queueing (observed: a 5.2s run whose CLI
# invocation had not returned after 5 minutes). Bound it, and salvage the dataset
# if it was already printed before the timeout hit.
APIFY_TIMEOUT_SECONDS = int(os.environ.get("APIFY_TIMEOUT_SECONDS", "180"))

SOCIAL_HOSTS = {"linkedin.com", "twitter.com", "x.com", "instagram.com", "facebook.com"}


def _is_social_host(url: str) -> bool:
    host = urlparse(url).netloc.removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)


class ScrapeError(Exception):
    pass


def _crawl4ai_markdown(result) -> str:
    """installed crawl4ai (0.4.247) puts the MarkdownGenerationResult object (with
    .fit_markdown) on result.markdown_v2 — result.markdown is a plain str there for
    back-compat. Handle both shapes so a version bump either way still works."""
    md = getattr(result, "markdown_v2", None) or result.markdown
    if hasattr(md, "fit_markdown"):
        return md.fit_markdown or md.raw_markdown or ""
    return getattr(result, "fit_markdown", None) or md or ""


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
            return _crawl4ai_markdown(result)

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
            md = _crawl4ai_markdown(result)
            hrefs = [l.get("href", "") for l in (result.links or {}).get("internal", []) if l.get("href")]
            return md, hrefs

    return asyncio.run(_run())


PRODUCT_PATH = re.compile(r"/(products?|drones?|uas|systems?|hardware|fleet|aircraft)(/|$)", re.I)
# nav/footer boilerplate that never holds product specs. `team|media|downloads` were the
# expensive omission: neros.tech publishes no product page at all, so the shallow fallback
# spent both crawl slots on /teams and /media and padded the extraction prompt with staff
# bios. Gated spec vaults (/protected-downloads) are boilerplate too — the PDF behind them
# is not reachable as markdown.
BOILERPLATE_PATH = re.compile(
    r"/(about|company|contact|press|news|media|blog|articles?|insights|newsroom"
    r"|events|careers|support|privacy|terms|legal"
    r"|team|teams|mission|story|investors|partners|downloads?|protected-downloads"
    r"|login|cart|account|use-cases|resources|faq)([-_/]|$)",
    re.I,
)


def sitemap_urls(base_url: str, *, timeout: int = 10) -> list[str]:
    """`/sitemap.xml` <loc> entries, or [] if the site has none (neros.tech doesn't).

    This is the free version of a Firecrawl `/map` call — one unauthenticated GET, no
    credits. Never fatal: a missing sitemap just means we fall back to homepage links.
    """
    parsed = urlparse(base_url)
    url = f"{parsed.scheme or 'https'}://{parsed.netloc}/sitemap.xml"
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as e:
        log.debug("no sitemap at %s: %s", url, e)
        return []
    if not response.ok:
        return []
    return [m.strip() for m in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", response.text, re.I)]


def _model_likeness(href: str) -> int:
    """Sort key (0 = promote) for shallow candidates that matched no product keyword.

    A model page is named after the aircraft — it carries a digit or a hyphenated name
    (/perimeter-8, /black-widow). Nav pages are bare nouns (/learn, /magniphy, /radios).
    The live skyfront.com run picked /magniphy over /perimeter-8 on nav order alone.
    Only promotes; ties keep nav order, which is still the best signal we have (sorted()
    is stable).
    """
    slug = urlparse(href).path.strip("/").rsplit("/", 1)[-1]
    return 0 if (any(c.isdigit() for c in slug) or "-" in slug) else 1


def pick_product_links(
    hrefs: list[str], base_url: str, limit: int = 2, *, keyword_only: bool = False
) -> list[str]:
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
    if keyword_only:
        return keyword[:limit]
    # Keyword hits rank first but no longer veto the shallow tier: the live hyl.io run
    # had exactly one keyword path (/hardware) and left the second crawl slot unused
    # while /pegasus and /ares sat in the shallow tier, so extraction saw no model
    # names at all. Within each tier the aircraft-named path wins (/products/black-widow
    # over the /products index).
    ranked = sorted(keyword, key=_model_likeness)
    ranked += [h for h in sorted(shallow, key=_model_likeness) if h not in ranked]
    return ranked[:limit]


def scrape_deep(
    url: str,
    preferred: str = "crawl4ai",
    *,
    fetch=scrape_with_links,
    fallback=None,
    sitemap_fn=sitemap_urls,
) -> str:
    """Homepage + up to 2 product pages, concatenated. Falls back to plain scrape().

    Page discovery is sitemap-first but only for explicit product paths: a sitemap lists
    URLs in site-map order, which ranks nothing, whereas homepage links come in nav order
    — a real relevance signal. So the sitemap can only *add* a confident product hit, never
    outvote the homepage with a shallow guess. When neither source yields a candidate the
    homepage is scraped alone, no wasted crawls.
    """
    fallback = fallback if fallback is not None else scrape
    try:
        md, hrefs = fetch(url)
    except ScrapeError:
        return fallback(url, preferred=preferred)
    links = pick_product_links(sitemap_fn(url), url, keyword_only=True) or pick_product_links(hrefs, url)
    parts = [md]
    for link in links:
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

    CONFIRMED live 2026-07-30: V2 `/api/scrape` answers
    `{"id": ..., "results": {"markdown": {"data": ["# ...", ...]}}, "metadata": {...}}` —
    a LIST of markdown chunks, which is why every earlier single-string guess missed and
    this scraper reported "no markdown in response" on a perfectly good 200. That path is
    first; the older guesses stay behind it in case the shape varies by request type.
    """
    def _chunks(p):
        data = p["results"]["markdown"]["data"]
        if isinstance(data, str):  # single chunk, not wrapped in a list
            return data
        return "\n\n".join(s for s in data if isinstance(s, str))

    candidates = [
        _chunks,
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
    # SGAI_API_KEY is the vendor's own name (docs/tools/scrapegraphai.md); this repo's
    # .env spells it SCRAPEGRAPHAI_API_KEY, so a configured key was silently unread and
    # this fallback never ran. Accept both, vendor name first.
    api_key = os.environ.get("SGAI_API_KEY") or os.environ.get("SCRAPEGRAPHAI_API_KEY")
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
                    # Live-rejected 2026-07-30: bare "adaptive" is not an allowed value —
                    # the actor takes "playwright:adaptive" | "playwright:firefox" |
                    # "playwright:chrome" | "cheerio" | "jsdom".
                    "crawlerType": "playwright:adaptive",
                    "maxCrawlPages": 1,
                    "maxCrawlDepth": 0,  # this URL only — never follow links onto the paid meter
                    "saveMarkdown": True,
                },
                tmp,
            )

        # Confirmed against apify-cli 1.7.1 (live run 2026-07-30): `-i` is INLINE JSON,
        # a file path needs `-f/--input-file` — the old `-i <tmpfile>` form made the CLI
        # try to parse a filename as JSON, so this fallback could never have worked.
        # `--silent` keeps actor logs off stdout so `--output-dataset` prints the bare
        # JSON array we parse below.
        argv = [
            "apify", "call", "apify/website-content-crawler",
            "-f", tmp_path, "--output-dataset", "--silent",
        ]
        stdout = None
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=APIFY_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired as e:
            # The CLI can linger long after the dataset has been printed. If we already
            # have the full JSON, the scrape succeeded — only give up if we don't.
            stdout = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else e.stdout
            if not (stdout or "").strip():
                raise ScrapeError(
                    f"apify: CLI timed out after {APIFY_TIMEOUT_SECONDS}s with no output"
                ) from e
            log.warning("apify CLI timed out after %ss but had printed a dataset — using it",
                        APIFY_TIMEOUT_SECONDS)
        except (subprocess.SubprocessError, OSError) as e:
            raise ScrapeError(f"apify: subprocess failed: {e}") from e

        if stdout is None:
            if result.returncode != 0:
                stderr_line = (result.stderr or "").strip().splitlines()[:1]
                stderr_line = stderr_line[0] if stderr_line else ""
                raise ScrapeError(f"apify: CLI exited {result.returncode}: {stderr_line}")
            stdout = result.stdout

        try:
            items = json.loads(stdout)
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
