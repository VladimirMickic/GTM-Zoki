# Firecrawl — managed scrape API returning markdown (fallback #1: anti-bot/Cloudflare)

Fetched from docs.firecrawl.dev (introduction, features/scrape, api-reference/endpoint/scrape)
and firecrawl.dev/pricing on 2026-07-18/19. Read this before writing `scrape_firecrawl` in
`gtm/scrape.py`. This is our first fallback after crawl4ai specifically because it handles
proxies/anti-bot/JS rendering — crawl4ai got Cloudflare-blocked on Red Cat's site in a prior run.

## Auth
`Authorization: Bearer $FIRECRAWL_API_KEY` header. Key format `fc-YOUR-API-KEY` from the
Firecrawl dashboard. Env var: `FIRECRAWL_API_KEY`.

## Scrape endpoint (the one call our adapter needs)
`POST https://api.firecrawl.dev/v2/scrape` (v2 is current; v1 still referenced in some
third-party posts but v2 is what the primary docs document — do not use v1).

Request body:
```json
{
  "url": "https://example.com",
  "formats": ["markdown"]
}
```
`formats` is an array (can request multiple, e.g. `["markdown", "html"]`); `markdown` is the
default if omitted, but pass it explicitly so we never accidentally pay for formats we don't use.

Response:
```json
{
  "success": true,
  "data": {
    "markdown": "...",
    "metadata": { ... }
  }
}
```
Our adapter just needs `response["data"]["markdown"]`.

curl example:
```bash
curl -X POST "https://api.firecrawl.dev/v2/scrape" \
  -H "Authorization: Bearer $FIRECRAWL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "formats": ["markdown"]}'
```

## Anti-bot / proxy / stealth (why this tier exists)
Firecrawl "handles the hard stuff: proxies, anti-bot, JavaScript rendering, and dynamic
content" automatically on every scrape — no special flag needed for baseline anti-bot handling.
For harder targets:
- `"proxy"` param: `"basic"` (default, fastest, standard proxies), `"enhanced"` (advanced
  anti-bot handling, costs up to 5 credits/request), `"auto"` (tries basic, retries with
  enhanced on failure). For known-Cloudflare-blocked sites, consider passing `"proxy": "auto"`
  or `"enhanced"` directly rather than burning a request on `basic` first.
- `"waitFor"` (ms): let JS-heavy pages finish rendering before extraction.
- `"actions"`: scripted wait/click/scroll steps for pages needing interaction before content
  loads (not needed for our simple GET-and-read use case, but available).
- `"location"`: `{country, languages}` to emulate a region if a site geofences.

## Limits
Free plan: **1,000 credits/month**, recurring monthly (not a one-time trial grant) — this
diverges from the ~500 one-time credits assumed going in; confirm current numbers at
firecrawl.dev/pricing before budgeting, pricing pages change often. 1 scrape = 1 credit at
`basic` proxy; `enhanced`/Stealth-tier proxy costs up to 5x. Free plan also caps concurrency
at 2 simultaneous requests. Paid tiers start at $16/mo (Hobby, 3,000 credits).

## Errors
Non-2xx / `"success": false` responses. Watch for: 401/403 bad or missing key, 429 rate
limit (free plan's 2-concurrency cap trips easily — back off), 402/insufficient credits once
the monthly 1,000 is exhausted. Treat any of these as `ScrapeError` and fall through to the
next scraper in the chain.

## Gotchas
- We do NOT use Firecrawl's `extract` / structured-output features (separate paid product,
  ~$89/mo add-on) — only `formats: ["markdown"]` from `/v2/scrape`. Extraction stays in our
  own gpt-4o-mini stage (S2).
- Free-tier credits don't roll over month to month — budget demo runs accordingly.
- `formats` unconfirmed to include `"markdown"` as *the only* required field for a bare-bones
  call; docs show `url` + `formats` as the minimal request, everything else optional.
- Confidence caveat: the exact free-tier credit figure (1,000/month) came from a direct fetch
  of firecrawl.dev/pricing, a primary source, but pricing pages are known to change without
  notice — re-check before relying on it for demo budgeting.
