# MyEmailVerifier API — single-email verification (waterfall tier: verifier)

Fetched from github.com/pat-myemailverifier/myemailverifier-api and myemailverifier.com
on 2026-07-18. Read this before touching `gtm/emails.py`.

## Auth
`apikey` query param (no header option documented). Key comes from the MyEmailVerifier
dashboard after signup. Env var: `MYEMAILVERIFIER_API_KEY`.
Alt endpoint form exists (`client.myemailverifier.com/verifier/validate_single/{email}/{apikey}`)
— **unverified** (seen referenced, not fetched/confirmed directly) — prefer the
query-param form below, it's the one in the primary docs.

## Single Verify
`GET https://api.myemailverifier.com/api/validate_single.php?apikey=$KEY&email=$EMAIL`

Example:
```
curl "https://api.myemailverifier.com/api/validate_single.php?apikey=$MYEMAILVERIFIER_API_KEY&email=test@example.com"
```

Response JSON: `Address`, `Status`, `Diagnosis` (human-readable reason), `catch_all`
(bool-ish string), `Disposable_Domain`, `Role_Based`, `Free_Domain`, `Greylisted`
(bool-ish strings), plus `error_code` (0 = success).

## Verdict mapping
**Correction to prior assumption:** the vendor's `Status` values are capitalized words
(`Valid`, `Invalid`, `Catch-All`, `Unknown`, `Disposable`, `Role-Based`, `Greylisted`,
`Spam Trap`) — **not** the lowercase `ok`/`invalid`/`catch-all`/`unknown` this doc was
originally scoped against.

The adapter's job is to normalize vendor status into the **hunter-style** vocabulary
(`valid | invalid | accept_all | unknown`, same shape as Hunter's `email-verifier`
`status`) — that's what `gtm/emails.py`'s existing `_VERDICTS` table then maps to the
sheet label. Task 2.2/2.3 code against the middle column below; the right column is
shown for reference only (it's what `verdict()` produces downstream, not something the
adapter computes itself):

| `Status` | hunter-style (adapter output) | sheet verdict (via `_VERDICTS`) |
|---|---|---|
| `Valid` | `valid` | `verified` |
| `Invalid` | `invalid` | `reject` |
| `Catch-All` | `accept_all` | `risky` |
| `Unknown` | `unknown` | `unverified` |
| `Greylisted` | `unknown` (server deferred, re-check later) | `unverified` |
| `Disposable` | `invalid` | `reject` |
| `Role-Based` | `invalid` | `reject` |
| `Spam Trap` | `invalid` | `reject` |

`catch_all: "true"` on an otherwise-`Valid` result should also downgrade the adapter
output to `accept_all`, same pattern as Hunter's own `accept_all`.

## Score
No numeric score in the response; the adapter must synthesize one (e.g. `100` for
`Valid`, `0` otherwise) to satisfy the `verify() -> {"status": ..., "score": int}`
contract.

## Limits
- Free plan: **100 credits/day**, no credit card required for signup.
- Default rate limit: ~30 requests/minute (raise a ticket for more).

## Errors
- Docs did not surface an explicit 429 JSON body — treat any non-`error_code: 0` /
  non-200 response as "stop this tier for the run", fall through to the next waterfall
  step rather than retrying in a loop.
- Detailed error-code list lives in a separate `ERROR_CODES.md` in the GitHub repo that
  wasn't inlined here — check it if `error_code != 0` starts showing up in practice.

## Gotchas
- Query-param auth only — the key will land in server access logs; don't log full
  request URLs in our error log, log the email + status instead.
- `Diagnosis` is a free-text explanation, not a stable enum — don't branch on it, only
  on `Status`.
