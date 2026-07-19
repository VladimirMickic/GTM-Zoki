# Scraper selection — which fallback to use when

Not an external-tool reference like the others in this folder — this is the decision table
for `gtm/scrape.py`'s fallback chain, consulted by both humans and in-loop Claude when picking
or debugging a scraper. Read the per-tool docs (`crawl4ai.md`, `firecrawl.md`,
`scrapegraphai.md`, `apify.md`) for call shapes; this file only says *when*.

## The chain
Intended `FALLBACK_ORDER` (replaces the current code's `["crawl4ai", "firecrawl", "scrapling",
"apify", "scrapegraphai"]` — scrapling is being dropped, order is being fixed):
```
["crawl4ai", "firecrawl", "scrapegraphai", "apify"]
```

| # | Scraper | Cost | Where it runs | Best for | Why it's at this position |
|---|---|---|---|---|---|
| 1 | **crawl4ai** | Free | Local (Playwright) | General sites, default first try | No API key, no credits burned, fully local — cheapest possible attempt first. |
| 2 | **Firecrawl** | Managed, ~1,000 free credits/mo | Firecrawl's cloud | JS-heavy sites, Cloudflare-blocked sites | Explicitly built for anti-bot/proxy/JS rendering — this is what beat the Cloudflare block that stopped crawl4ai on Red Cat's site in a prior run. First paid-tier fallback because it's the strongest generic anti-bot option. |
| 3 | **ScrapeGraphAI** | Managed, ~500 free credits (one-time, unconfirmed) | ScrapeGraphAI's cloud | Last generic resort | Another managed scrape API; reached only if both crawl4ai and Firecrawl fail or return junk (<200 chars). No unique capability over Firecrawl for our purposes — it's a backstop, not a specialist. |
| 4 | **Apify** | Managed, $5 free credits/mo | Apify's cloud, via CLI | Anti-bot generic sites (last resort) **and** all social/LinkedIn hosts (mandatory route) | Strongest anti-bot + proxy story of the four, and the only one of the four with actors that can render/authenticate social platforms. |

## Deterministic rule: social hosts go straight to Apify

Before entering the crawl4ai → Firecrawl → ScrapeGraphAI chain at all, check the URL's host.
If it matches a social platform, skip the chain entirely and call Apify directly with the
matching actor (see `apify.md` for actor IDs):

| Host pattern | Route to |
|---|---|
| `linkedin.com` | Apify (LinkedIn actor — see `apify.md`, no canonical pick confirmed yet) |
| `twitter.com`, `x.com` | Apify (`apidojo/tweet-scraper`) |
| `instagram.com` | Apify (`apify/instagram-scraper`) |
| `facebook.com` | Apify (`apify/facebook-posts-scraper`) |

**Why bypass the chain for these:** crawl4ai, Firecrawl, and ScrapeGraphAI are all generic
markdown-from-HTML scrapers — none of them can render LinkedIn/Twitter/Instagram/Facebook's
authenticated, heavily-JS, anti-scraping-hardened feeds. Sending these hosts through the
normal chain would just burn three failed/junk attempts (each counted against free-tier
credits) before eventually landing on Apify anyway. Route there first.

Suggested check (pseudocode for the orchestrator or a future `pick_scraper(url)` helper):
```python
SOCIAL_HOSTS = {"linkedin.com", "twitter.com", "x.com", "instagram.com", "facebook.com"}

def is_social(url: str) -> bool:
    host = urlparse(url).netloc.removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)
```

## For general (non-social) URLs
Use `scrape(url)` as already implemented in `gtm/scrape.py`: try `preferred` (default
`crawl4ai`), then walk `FALLBACK_ORDER`, treating any result under `MIN_MARKDOWN_CHARS` (200)
as junk and falling through. No manual selection needed — the chain order above already
encodes cost-then-capability priority (free/local first, strongest anti-bot last among the
generic three).

## When to override `preferred`
- A site is *known* Cloudflare-protected (e.g. from a prior run's error log) — start at
  `firecrawl` directly rather than wasting a crawl4ai attempt.
- A site is a social host — don't use `preferred` at all; route to Apify per the table above.

## What each tool does NOT do for us
- None of the four perform our structured extraction — that's `gtm/extract.py` (gpt-4o-mini),
  a separate stage (S2) run after any scraper returns markdown.
- Firecrawl's `extract` product and ScrapeGraphAI's `extract` endpoint both offer AI-powered
  structured extraction — we never call either; we only ever request their markdown output.
