# Prospeo API — person enrichment (waterfall tier: email hunt)

Fetched from prospeo.io/api-docs/{enrich-person,authentication,rate-limits} and
prospeo.io/pricing on 2026-07-18. Read this before touching `gtm/emails.py`.

## ⚠️ Deprecated endpoint — do not use
`POST https://api.prospeo.io/email-finder` is marked `[Deprecated] Email Finder API` in
the live docs — confirmed via that exact page title in WebSearch results. **Confidence
caveat:** the removal date ("fully removed on March 1st") and the docs "last updated
June 11 2026" stamp came from WebSearch snippets only — a direct WebFetch of
`prospeo.io/api-docs/email-finder` kept resolving to the generic docs-index page instead
of the specific route (likely a JS-rendered SPA path WebFetch can't execute), so neither
the exact wording nor the **year** of "March 1st" is independently confirmed from primary
source. Today is 2026-07-18, after a plausible March-1-2026 removal, so treat the old
endpoint as **probably already gone** — but this is inference from secondary snippets,
not a verified fact. **Do not code against `/email-finder`, do not build a fallback path
to it.** Task 2.5 (live smoke test) must make one real `/enrich-person` call with a live
key before this waterfall tier is trusted in a run — if that call 404s/401s in a way that
suggests the whole integration is broken (not just a missing match), escalate rather than
silently falling through.

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
The adapter's job is to normalize into the **hunter-style** vocabulary
(`valid | invalid | accept_all | unknown` — same shape as Hunter's `email-verifier`
`status`); that's what `gtm/emails.py`'s existing `_VERDICTS` table then maps to the
sheet label. Task 2.2/2.3 code against the middle column below; the right column is
shown for reference only:

| `person.email.status` | hunter-style (adapter output) | sheet verdict (via `_VERDICTS`) |
|---|---|---|
| `VERIFIED` | `valid` | `verified` |
| `UNVERIFIED` | `unknown` (Prospeo found it but couldn't confirm deliverability — closest fit to hunter's "we don't know") | `unverified` |
| `null` / no email returned | not applicable — treat as a miss, don't call `verdict()`, fall through the waterfall | — |

Prospeo has no `accept_all`/catch-all concept in the documented response — nothing maps
to `accept_all` for this provider.

`only_verified_email: true` in the request already filters to verified-only matches on
Prospeo's side; set it true if we want to avoid spending a credit on an unverified guess.

## Score
No numeric score in the documented `person.email` response shape; the adapter must
synthesize one (e.g. `100` for `VERIFIED`, `0` otherwise) to satisfy the
`find() -> {"email": str, "score": int}` contract. A `confidence_score`-style field may
exist elsewhere in the full person payload (job-history/company sections weren't fully
enumerated here) — **unconfirmed**, don't assume it's there; check the live response
shape during Task 2.5's smoke test before relying on anything beyond `person.email.status`.

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
