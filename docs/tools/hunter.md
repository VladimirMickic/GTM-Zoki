# Hunter.io API v2 — email finder + verifier (waterfall tiers 2 + validation)

Fetched from hunter.io/api-documentation/v2 on 2026-07-18. Read this before touching
`gtm/emails.py`.

## Auth
`X-API-KEY: $HUNTER_API_KEY` header (also accepts `?api_key=` query — don't, it leaks
into logs). Key comes from hunter.io dashboard → API. Env var: `HUNTER_API_KEY`.
Special key `test-api-key` validates params and returns dummy data (no credits burned).

## Email Finder (tier 2)
`GET https://api.hunter.io/v2/email-finder`
Params: `domain` + `first_name` + `last_name` (or `full_name`). Optional `max_duration` (3-20s).
Response `data`: `email`, `score` (0-100), `verification: {status, date}`.
`email` can be null when nothing found — that's a miss, fall through to tier 3.

## Email Verifier (validation for all tiers)
`GET https://api.hunter.io/v2/email-verifier?email=...`
Response `data`: `status` ∈ valid | invalid | accept_all | webmail | disposable | unknown,
`score` (0-100), plus `mx_records`, `smtp_check`, `accept_all` booleans.
Our acceptance rule: `valid` → verified; `accept_all`/`webmail` → risky (keep, flag);
`invalid`/`disposable` → reject; `unknown` → keep unverified, flag.

## Limits
- Free plan: ~25 finder searches + 50 verifications per month — budget for demo runs.
- Rate: finder 15 req/s / 500 per min; verifier 10 req/s / 300 per min (no throttling
  needed at our volumes).

## Errors
JSON `{"errors": [{"id", "code", "details"}]}`. Watch for: 401 bad key, 403 rate limit,
429 monthly usage exceeded (free tier cap — stop the waterfall tier, don't retry), 451
legal block for a specific person (skip that contact, not fatal).

## Gotchas
- Verification inside finder responses is often stale — re-verify found emails anyway.
- `accept_all` domains make verification weak evidence; mark risky, never "verified".
- Never echo the key; requests via header only.
