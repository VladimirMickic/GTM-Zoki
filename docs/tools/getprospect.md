# GetProspect API

Email finder + verifier, added as a 5th provider in the `EmailProvider` waterfall
(gtm/email_providers.py, gtm/emails.py). Free-tier finder/verifier ahead of Hunter
in the chain (cheap → expensive).

## Confirmed from official docs (getprospect.readme.io)

- Base: `https://api.getprospect.com/public/v1/`
- Auth: header `apiKey: <key>` (docs also allow `?apiKey=` query param — we use the header).
- **Email Finder** — `GET /email/find` — query params: `name` (full name, "first last"),
  `company` (company name or domain; domain increases match odds). Status codes: 200
  (found), 400/401/404/408 (miss/error).
- **Email Verifier** — `GET /email/verify` — query param: `email`. Status codes: 200 (checked),
  401 (unauthorized), 402 (insufficient credits), 408 (timeout).
- Key management: https://app.getprospect.com/settings/api. API-key access reportedly
  requires GetProspect's Enterprise plan per a third-party aggregator (apitracker.io) —
  unconfirmed directly, and the user has a working key, so treat that claim as noise
  unless calls start 401ing.

## NOT confirmed — response JSON field names

readme.io's endpoint pages render the request shape (method, params, status codes) as
static content, but the **response body examples are behind their JS-only "Try It"
panel**, which every fetch attempt (direct, via Postman mirror, via aggregators) came
back either 403, empty, or admittedly-a-guess. No GitHub reference implementation was
findable either.

`GetProspectProvider` in gtm/email_providers.py therefore parses the response
**defensively**: it tries a short list of plausible field paths for the email
(`email`, `data.email`) and for verify status (`status`, `data.status`), and returns
`None` (miss — falls through to Hunter) if none match. This is safe by construction —
a wrong guess just means GetProspect always misses, not a crash — but it means the
field-name guesses need one real live call to confirm/fix.

**Action item for whoever runs the first live enrich with `GETPROSPECT_API_KEY` set:**
temporarily log `resp.json()` for one real find/verify call, compare against the
`_get`/`_parse` logic in `GetProspectProvider`, and correct the field paths if the
guess was wrong. Then delete the temporary logging and remove this note.

## Gotchas

- Same log-and-skip contract as every other provider: missing key, any non-200, or
  malformed response → return `None`, never raise.
- `find()` receives lowercased first/last from the waterfall (see `_find_chain`'s
  comment in gtm/emails.py) — GetProspect's `name` param is built from those, so it
  will be lowercase. Untested whether GetProspect's matching is case-sensitive.
