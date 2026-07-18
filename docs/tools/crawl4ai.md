# crawl4ai (v0.9.x) — Reference

Docs: https://docs.crawl4ai.com/

## 1. Install

```bash
pip install crawl4ai
crawl4ai-setup        # installs/updates browser deps (Playwright) for regular + undetected modes, OS checks
crawl4ai-doctor        # verifies Python compatibility, Playwright install, flags env conflicts
```

Optional extras (per docs): `pip install crawl4ai[torch]`, `crawl4ai[transformer]`, `crawl4ai[all]` for extra ML capabilities; `crawl4ai-download-models` to pre-fetch/cache large models locally.

If `crawl4ai-doctor` reports issues, follow its suggestions (e.g. install missing system packages) and re-run `crawl4ai-setup`.

## 2. Auth

No API key required. It's fully open source / local. From the homepage: "No forced API keys, no paywalls—everyone can access their data."

## 3. Our use: URL → clean markdown

Minimal crawl:

```python
import asyncio
from crawl4ai import AsyncWebCrawler

async def main():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun("https://example.com")
        print(result.markdown[:300])

if __name__ == "__main__":
    asyncio.run(main())
```

`AsyncWebCrawler` launches a headless browser (Chromium by default) and converts the HTML into Markdown automatically.

Pruned / "fit" markdown (strips nav/boilerplate) — exact code from `core/fit-markdown/`:

```python
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

async def main():
    prune_filter = PruningContentFilter(
        threshold=0.45,
        threshold_type="dynamic",
        min_word_threshold=5
    )
    md_generator = DefaultMarkdownGenerator(content_filter=prune_filter)
    config = CrawlerRunConfig(markdown_generator=md_generator)

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url="https://news.ycombinator.com", config=config)
        if result.success:
            raw = result.markdown.raw_markdown   # unfiltered
            fit = result.markdown.fit_markdown   # pruned/filtered
```

`PruningContentFilter` params: `threshold` (0-1, pruning strictness), `threshold_type` (`"fixed"` or `"dynamic"`), `min_word_threshold` (min words to keep a block). Removes low-density sections by text density, link density, and tag importance.

## 4. CrawlResult fields (from `api/crawl-result/`)

- **`success`** (bool) — True if the crawl pipeline ended without major errors; False otherwise.
- **`status_code`** (Optional[int]) — HTTP status code of the page (e.g. 200, 404); status of the first response in the redirect chain.
- **`markdown`** (Optional[Union[str, MarkdownGenerationResult]]) — a `MarkdownGenerationResult` with:
  - `raw_markdown` (str) — full HTML→Markdown conversion
  - `markdown_with_citations` (str) — same markdown, with link references as academic-style citations
  - `references_markdown` (str) — reference list/footnotes
  - `fit_markdown` (Optional[str]) — filtered text if content filtering (Pruning/BM25) was applied; not populated unless a filter strategy is configured
  - `fit_html` (Optional[str]) — the HTML that produced `fit_markdown`
- **`error_message`** (Optional[str]) — if `success=False`, textual description of the failure.
- **`links`** (Dict[str, List[Dict]]) — verified against installed v0.9.x `crawl4ai.models.CrawlResult`: keys `"internal"`/`"external"`, each item a dict with `href` (+ `text`, etc.). Note: `fit_markdown` strips link syntax entirely, so this field is the only way to get page links.

## 5. CLI (from `core/cli/`)

```bash
crwl https://example.com                       # basic crawl
crwl https://example.com -o markdown            # markdown output
crwl https://example.com -o markdown-fit -f filter_bm25.yml   # pruned/fit markdown with a filter config
crwl https://example.com -o json -v --bypass-cache             # verbose JSON, skip cache
```

Key flags: `-o` output format (`markdown`, `json`, `all`, `markdown-fit`), `-B` browser config file, `-C` crawler config file, `-e` extraction config file, `-s` JSON schema file, `-q` LLM question for content analysis, `-f` content filter config, `-v` verbose, `--bypass-cache`.

## 6. Gotchas

- **First-run browser download**: `crawl4ai-setup` must be run after `pip install` to install/update the Playwright browser binaries — crawling will fail without this step.
- **Async requirement**: `AsyncWebCrawler` is async-only; must be driven via `asyncio.run(main())` inside an `async def main()` using `async with AsyncWebCrawler() as crawler`.
- **`fit_markdown` requires a filter**: `result.markdown.fit_markdown` only populates when a content filtering strategy (e.g. `PruningContentFilter`, BM25) is attached via `markdown_generator`; otherwise use `raw_markdown`.
- **JS-heavy pages**: not fully detailed on the fetched pages — quickstart mentions `CrawlerRunConfig` supports a `js_code` parameter to run custom scripts before extraction, and `page_timeout` (e.g. `page_timeout=80000`) for longer operations. An explicit `wait_for` parameter was not found on the pages fetched for this reference (`core/quickstart/`, `core/fit-markdown/`, `api/crawl-result/`, `core/cli/`, `core/installation/`) — check `core/page-interaction/` or `CrawlerRunConfig` API docs directly if needed.
- **Doctor tool**: if `crawl4ai-doctor` flags issues, install the missing system packages it names and re-run `crawl4ai-setup`.
