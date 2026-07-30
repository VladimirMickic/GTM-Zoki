# Apify CLI — managed crawl actors for markdown + social/LinkedIn (fallback #3, and direct route for social hosts)

Fetched from github.com/apify/apify-cli (README, primary), docs.apify.com/cli/docs/reference
(primary), apify.com/apify/website-content-crawler (primary), apify.com/pricing (primary), and
WebSearch snippets for the `APIFY_TOKEN` env var and specific social-scraping actor IDs
(flagged below) on 2026-07-19. Read this before writing `scrape_apify` in `gtm/scrape.py`.
**We use the Apify CLI — not the MCP server, not the raw HTTP API.**

## Install
```bash
curl -fsSL https://apify.com/install-cli.sh | bash
```
Confirmed verbatim from the `apify/apify-cli` GitHub README (primary fetch) as the
macOS/Linux install command.

## Auth
```bash
apify login
```
Interactive login (opens a browser to authorize). For non-interactive/CI use, pass a token
directly:
```bash
apify login -t <token>
# or the full form:
apify auth login -t <token>
```
Token comes from the Apify Console → Settings → Integrations
(`https://console.apify.com/settings/integrations`). Env var: `APIFY_TOKEN` — **confirmed via
WebSearch snippets of Apify's own SDK/env-var docs** ("By default, it is taken from the
`APIFY_TOKEN` environment variable"), but not found verbatim on the specific CLI
`docs/vars` page fetched directly this session (that page's fetched content only showed
Actor-level env-var configuration, not CLI auth vars). `APIFY_TOKEN` is nonetheless the
standard, widely-documented var across Apify's JS/Python SDKs and CLI — safe to use, but flag
this one fact as slightly-below-primary-confidence.

## Run pattern: `apify/website-content-crawler` (our markdown fallback)
Actor ID (confirmed via primary fetch of its Apify Store page): `apify/website-content-crawler`.

1. Write an input JSON file:
```json
{
  "startUrls": [{ "url": "https://example.com" }],
  "crawlerType": "adaptive",
  "maxCrawlPages": 1,
  "maxCrawlDepth": 0,
  "saveMarkdown": true
}
```
(`maxCrawlPages: 1` + `maxCrawlDepth: 0` — we only want the single page our adapter was asked
for, not a full-site crawl on a paid meter; `saveMarkdown: true` is required to get a
`markdown` field in the output.)

2. Call the actor and get the dataset back in one shot:
```bash
apify call apify/website-content-crawler -f input.json --output-dataset --silent
```
**Flag shape confirmed live 2026-07-30 against installed apify-cli 1.7.1** (`apify call --help`
plus a real run): `-i, --input=<value>` is **inline JSON only** — a file path needs
`-f, --input-file=<value>`. Passing `-i input.json` makes the CLI try to parse the filename as
JSON. `--output-dataset` (alias `-o`) "prints out the entire default dataset on successful run
of the Actor"; `--silent` suppresses the actor's run logs, which otherwise interleave with that
JSON on stdout and break parsing.

Confirmed dataset shape (one object per crawled page):
```json
[{ "url": "...", "crawl": {...}, "metadata": {...}, "text": "...", "markdown": "# ...", "html": null }]
```

**Timing gotcha:** the CLI blocks on the remote run and can sit far longer than the run itself
— the 2026-07-30 smoke was a 5.2s actor run ($0.0024) whose `apify call` had still not returned
after 5 minutes. `gtm/scrape.py` bounds it with `APIFY_TIMEOUT_SECONDS` (default 180) and, on
timeout, parses whatever dataset JSON was already printed rather than discarding a paid run.

Alternative if you already have a `datasetId` (e.g. from a prior async run) and want the
dataset separately:
```bash
apify datasets get-items <datasetId> --format json
```
(confirmed via primary fetch of the CLI reference: `apify datasets get-items <datasetId>
[--format json|jsonl|csv|html|rss|xml|xlsx]`, plus `--limit`/`--offset`.)

3. Parse the output: each dataset item has (confirmed via primary fetch of the actor's Store
page) both `text` (cleaned plain text) and `markdown` (formatted) fields:
```json
{
  "url": "https://example.com/page",
  "text": "...",
  "markdown": "# Heading...",
  "metadata": { "title": "...", "description": "...", "languageCode": "en" }
}
```
Our adapter reads `items[0]["markdown"]`.

## Social-host actors (for the later social→Apify routing rule; see `scrapers.md`)
No single official "linkedin-scraper" actor exists the way `apify/website-content-crawler`
is Apify-owned for general sites — LinkedIn actively blocks scraping, so the Store has many
competing third-party actors, several requiring session cookies. Confirmed official
Apify-owned actors for the other platforms (primary fetches of each actor's Store page):
- **Instagram**: `apify/instagram-scraper` — posts, reels, profiles, hashtags, comments.
- **Facebook**: `apify/facebook-posts-scraper` — page/profile posts, engagement, media.
- **Twitter/X**: `apidojo/tweet-scraper` — tweets via search, profile, URL, or list.
- **LinkedIn**: no canonical pick confirmed this session — **unconfirmed, WebSearch snippet
  only**. Candidates seen in the Store: `dev_fusion/linkedin-profile-scraper` (no cookies
  required) and `harvestapi/linkedin-profile-search` (no cookies). Evaluate at
  implementation time; do not hardcode without checking current cookie/auth requirements.

## Limits
Free plan: **$5 of platform usage credit per month** at $0.20/compute-unit, renews monthly,
unused credit does not roll over (confirmed via primary fetch of apify.com/pricing). Also
includes: full Store access, up to 8 GB RAM/actor, 25 concurrent runs, 5 datacenter proxy
IPs. Enough for roughly 1,000-5,000 pages/month depending on actor compute cost — budget for
demo runs, and prefer this only as a fallback, not primary.

## Errors
CLI exits non-zero on actor failure or auth failure; stderr carries the message. Watch for:
not-logged-in (run `apify login` first, or check `APIFY_TOKEN` is set), actor run `FAILED`/
`ABORTED` status, and credit exhaustion once the $5/month runs out (run fails or queues
depending on plan settings). Treat any non-zero exit or empty dataset as `ScrapeError` and
fall through — Apify is the last resort in `FALLBACK_ORDER` for generic sites, and the
mandatory route for social hosts.

## Gotchas
- CLI, not MCP, not raw HTTP — our adapter should shell out to `apify call ...` (e.g. via
  `subprocess`) and parse the printed dataset JSON, not hit `api.apify.com` directly.
- `saveMarkdown: true` must be set in actor input or the `markdown` field will be absent from
  dataset items.
- Anti-bot/proxy: `website-content-crawler` supports residential/datacenter proxy
  configuration via input (`proxyConfiguration`) and multiple crawler engines
  (`crawlerType: "adaptive" | "playwright:firefox" | "cheerio"`) — use `adaptive` as the
  general default; switch to a headless-browser type for JS-heavy/anti-bot targets.
- Never echo `APIFY_TOKEN` in logs or committed files.
