# Prospeo API — person enrichment (waterfall tier: email hunt)

Fetched from prospeo.io/api-docs/{enrich-person,authentication,rate-limits} and
prospeo.io/pricing on 2026-07-18. Read this before touching `gtm/emails.py`.

## ⚠️ Deprecated endpoint — do not use
`POST https://api.prospeo.io/email-finder` is marked `[Deprecated] Email Finder API` in
the live docs, with a migration timeline that says the endpoint is **fully removed on
March 1st**. The docs' own "last updated" stamp is June 11 2026 and today is 2026-07-18
— i.e. that removal date has plausibly already passed. **Treat the old endpoint as
dead; do not code against it, do not fall back to it.** Use `/enrich-person` below.

## Auth
Header `X-KEY: $PROSPEO_API_KEY` + `Content-Type: application/json`. Key from
app.prospeo.io/api. Base host: `api.prospeo.io` (HTTPS only). Env var: `PROSPEO_API_KEY`.

## Enrich Person (current endpoint)
`POST https://api.prospeo.io/enrich-person`

Body — identify the person with `data` (need `first_name`+`last_name` plus one of
`company_name`/`company_website`/`company_linkedin_url`; `linkedin_url` or `email` alone
also work):
```json
{
  "only_verified_email": true,
  "data": {
    "first_name": "Jane",
    "last_name": "Doe",
    "company_website": "example.com"
  }
}
```
```
curl -X POST https://api.prospeo.io/enrich-person \
  -H "X-KEY: $PROSPEO_API_KEY" -H "Content-Type: application/json" \
  -d '{"only_verified_email": true, "data": {"first_name": "Jane", "last_name": "Doe", "company_website": "example.com"}}'
```

Response (fields we care about — full schema also returns job history, company, etc.):
- `error` (bool), `free_enrichment` (bool, cached-match = no charge)
- `person.email`: `{ "status": "VERIFIED" | "UNVERIFIED" | null, "revealed": bool,
  "email": string, "verification_method": string }`
- `person.email.email` is only present/non-null when a match was found — null/absent =
  miss, fall through the waterfall.

## Verdict mapping
Internal vocabulary from `gtm/emails.py::verdict()`: `verified | risky | unverified | reject`.

| `person.email.status` | our verdict |
|---|---|
| `VERIFIED` | `verified` |
| `UNVERIFIED` | `unverified` |
| `null` / no email returned | not applicable — treat as a miss, don't call `verdict()` |

`only_verified_email: true` in the request already filters to verified-only matches on
Prospeo's side; set it true if we want to avoid spending a credit on an unverified guess.

## Limits
- Free plan: **75 email credits/month** + 100 Chrome-extension credits/month, no card required.
- Cost: 1 credit per matched email; +9 more (10 total) if `enrich_mobile: true`; no
  charge on `NO_MATCH`; repeat enrichment of the same person within 90 days is free (cached).
- Rate limit (free/Starter tier): ~5 req/s, 300/min, 2,000–5,000/day.

## Errors
JSON `{"error": true, "error_code": "..."}` on HTTP 400/429. Known codes: `NO_MATCH`,
`INVALID_DATAPOINTS` (not enough identifying info), `INSUFFICIENT_CREDITS` (monthly quota
exhausted — stop this tier, fall through), `INVALID_API_KEY`, `INVALID_REQUEST`,
`INTERNAL_ERROR`. HTTP 429 = rate limit — back off, don't hot-loop retry.

## Gotchas
- Don't resurrect the old `/email-finder` request/response shape (`GET`, different body)
  — it's a different contract even though the intent overlaps with `/enrich-person`.
- Bulk endpoint (`/bulk-enrich-person`, up to 50/call) exists and is cheaper on
  round-trips if we ever batch; not needed for the current one-company-at-a-time flow.
- `free_enrichment: true` on a response means it was a cached hit — good, but don't
  assume freshness; re-verify if the data looks stale.
