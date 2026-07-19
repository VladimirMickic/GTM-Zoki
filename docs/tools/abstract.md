# Abstract Email Validation API (waterfall tier: verifier)

Fetched from docs.abstractapi.com/api/email-validation on 2026-07-18. Read this before
touching `gtm/emails.py`.

## Auth
`api_key` query param (no header option). Key from the Abstract dashboard, free per-API
key (email validation has its own key, separate from other Abstract APIs).
Env var: `ABSTRACT_API_KEY`.

## Validate
`GET https://emailvalidation.abstractapi.com/v1/?api_key=$KEY&email=$EMAIL`

Example:
```
curl "https://emailvalidation.abstractapi.com/v1/?api_key=$ABSTRACT_API_KEY&email=test@example.com"
```

Response JSON (flat, all confirmed at docs.abstractapi.com):
- `email`, `autocorrect` (suggested fix or `""`)
- `deliverability`: `DELIVERABLE` | `UNDELIVERABLE` | `UNKNOWN` — **confirmed only 3
  values**, no `RISKY` (a marketing page implied a 4th `RISKY` value on a different
  response shape/tier; the actual `/v1/` API response only has these 3 — go with what
  the API doc shows).
- `quality_score`: float 0.01–0.99
- `is_valid_format`, `is_free_email`, `is_disposable_email`, `is_role_email`,
  `is_catchall_email`, `is_mx_found`, `is_smtp_valid`: **each wrapped**
  `{"value": bool, "text": "TRUE"/"FALSE"}` — confirms the original assumption, don't
  read these as bare booleans.
- `is_mx_found` returns `null`/`UNKNOWN` on the free plan (MX check is a paid feature).

## Verdict mapping
The adapter's job is to normalize into the **hunter-style** vocabulary
(`valid | invalid | accept_all | unknown` — same shape as Hunter's `email-verifier`
`status`); that's what `gtm/emails.py`'s existing `_VERDICTS` table then maps to the
sheet label. Task 2.2/2.3 code against the middle column below; the right column is
shown for reference only:

| `deliverability` | `is_catchall_email.value` | hunter-style (adapter output) | sheet verdict (via `_VERDICTS`) |
|---|---|---|---|
| `DELIVERABLE` | `false` | `valid` | `verified` |
| `DELIVERABLE` | `true` | `accept_all` (catch-all domain accepted it, weak signal) | `risky` |
| `UNDELIVERABLE` | any | `invalid` | `reject` |
| `UNKNOWN` | any | `unknown` | `unverified` |

## Score
`quality_score` is a float `0.01`–`0.99`, not an int — the adapter must scale it to
satisfy the `verify() -> {"status": ..., "score": int}` contract: `round(quality_score * 100)`.

## Limits
- Free plan: **100 requests/month**, **3 requests/second**, no credit card required.
- Every request (valid or not) consumes 1 credit.

## Errors
- 429 = rate limit hit (req/s ceiling) — back off and retry later in the run, don't
  hammer it.
- 422 = monthly quota exhausted — stop this tier for the rest of the run, fall through.

## Gotchas
- Query-param auth — same logging caution as MyEmailVerifier: don't log the raw URL.
- `is_mx_found` being `null` on free tier means don't treat a missing MX signal as a
  negative; ignore it and rely on `deliverability` instead.
- `autocorrect` is a suggestion, not an action — surface it but don't auto-replace the
  email we're verifying.
