# ScrapeGraphAI — managed scrape API for markdown (fallback #2: last generic resort)

Fetched from docs.scrapegraphai.com/api-reference/introduction (primary) plus WebSearch
snippets citing docs.scrapegraphai.com/api-reference/endpoint/... pages that 404'd on direct
fetch this session (flagged below) on 2026-07-19. Read this before writing
`scrape_scrapegraphai` in `gtm/scrape.py`.

## Auth
Header `SGAI-APIKEY: $SGAI_API_KEY`. Key format `sgai-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
— **unconfirmed, WebSearch snippet only** (the header name/format was not visible on the
primary `api-reference/introduction` page fetched directly; a search snippet quoting
ScrapeGraphAI's own curl examples gave `SGAI-APIKEY`). Env var: `SGAI_API_KEY` — but this
repo's `.env` spells it `SCRAPEGRAPHAI_API_KEY`, so `gtm/scrape.py` reads both (vendor name
first). Reading only `SGAI_API_KEY` left the configured key unread and this fallback dead. Key from the
ScrapeGraphAI dashboard (scrapegraphai.com/dashboard).

## Scrape endpoint (the one call our adapter needs)
Base URL: `https://v2-api.scrapegraphai.com` (confirmed via primary fetch of
`api-reference/introduction`).
`POST https://v2-api.scrapegraphai.com/api/scrape`

Request body, markdown output:
```json
{
  "url": "https://example.com",
  "formats": [{ "type": "markdown" }]
}
```
(Exact `formats` array shape — `[{"type": "markdown"}]` vs a bare string — is
**unconfirmed, WebSearch snippet only**; the primary `introduction` page confirmed the
endpoint and base URL but not this exact request body. Sanity-check the shape with a live
`test`-mode call, or against the SDK source, before hardcoding.)

curl example (from search snippet, same confidence caveat as above):
```bash
curl -X POST https://v2-api.scrapegraphai.com/api/scrape \
  -H "SGAI-APIKEY: $SGAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "formats": [{"type": "markdown"}]}'
```

Response includes `request_id`, `status`, and the markdown content — exact JSON key for the
markdown body **unconfirmed** (not visible in fetched primary content). The Python SDK
(`scrapegraph_py`) exposes `sgai.scrape(url)` as the equivalent call if the raw HTTP shape
needs double-checking before implementing.

## Free tier
**500 credits, one-time free-tier allocation** — sourced from a WebSearch snippet
(scrapegraphai.com/blog and third-party review posts as of mid-2026), **not confirmed on a
primary ScrapeGraphAI page fetched this session** (the primary `introduction` page did not
disclose credit amounts). Per that same snippet: markdown/html/links/images/summary scrape =
1 credit each; `extract` (AI) = 5 credits/call; `search` = 2-5 credits/result. Re-verify at
scrapegraphai.com/pricing before relying on this for budgeting.

## Response shape (confirmed live 2026-07-30)
`POST /api/scrape` with `formats: [{"type": "markdown"}]` answers:
```json
{
  "id": "01f01dd3-1daa-4360-919f-e5a6632b10a3",
  "results": {"markdown": {"data": ["# Example Domain\n\n..."]}},
  "metadata": {"contentType": "text/html"}
}
```
`results.markdown.data` is a **list** of markdown chunks — `gtm/scrape.py` joins them with a
blank line. Earlier guesses (`result`, `data.markdown`, `content`) all assumed a single string,
so genuine 200s were being thrown away as "no markdown in response".

## We do NOT use its AI extraction
ScrapeGraphAI's `extract` endpoint (`POST /api/extract`, formerly `smartscraper`) does
AI-powered structured-data extraction directly from a URL — this overlaps with our own S2
gpt-4o-mini extraction stage. **We deliberately call only the markdown-producing `scrape`
endpoint (`formats: [{"type": "markdown"}]`) and never `extract`.** Keep extraction logic
entirely in `gtm/extract.py`.

## Errors
Not directly confirmed this session (no primary error-schema page fetched) — treat any
non-2xx or a response missing the expected markdown field as `ScrapeError`, matching the
pattern used for the other scrapers, and fall through the chain. Watch for 401 (bad
`SGAI-APIKEY`) and 402/429-style credit-exhaustion responses once the free 500 credits run
out.

## Gotchas
- **V1 is deprecated.** The old `https://api.scrapegraphai.com/v1` host and its endpoint
  names (`smartscraper`, `searchscraper`, `markdownify`, `smartcrawler`) are gone — do not
  build against `markdownify`, despite that being the name used in the brief and in older
  blog posts. In V2, "markdownify" is just `scrape` with `formats: [{"type": "markdown"}]`.
  This is the single biggest divergence from the brief's assumption.
- This is documented as our **last generic resort** in the fallback chain — only reached
  when crawl4ai and Firecrawl have both failed or returned junk.
- Never echo `SGAI_API_KEY` in logs; header-only auth.
