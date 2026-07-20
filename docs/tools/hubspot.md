# HubSpot CRM API — sink (Slice 7)

Fetched from developers.hubspot.com (blog: "HubSpot Service Keys: The Right API Credential
for Data Integrations"; changelog: "Service Keys enter public beta for system-to-system
integrations"; docs: `apps/legacy-apps/authentication/intro-to-auth`, `api-reference/crm-
companies-v3`, `api-reference/crm-contacts-v3` batch/upsert, `api-reference/crm-associations-
v4/guide`, `developer-tooling/platform/usage-guidelines`, `developer-tooling/platform/
versioning`) on 2026-07-19. Read this before writing `gtm/hubspot.py` (Task 7.1). Free tier
(Free/Starter account), no paid add-ons.

**Auth-method correction vs. the hardening plan**: `docs/superpowers/plans/2026-07-18-gtm-
hardening.md` (Slice 7) was written assuming a legacy "private-app token." Since then
HubSpot's own UI has steered new credential creation toward **Service Keys**
(`Settings > Integrations > Service Keys`, public beta since 2026-02-10), which HubSpot
describes as the replacement for legacy private apps for exactly this kind of data-only,
system-to-system integration; legacy private apps are now flagged deprecated for new use in
the UI. Our credential lives in `.env` as **`HUBSPOT_SERVICE_KEY`** (not `HUBSPOT_TOKEN`).

## Are Service Keys the same as private-app tokens for our calls? — Yes, functionally, for auth
Confirmed from the docs (`intro-to-auth` + the Service Keys blog post): **Service Keys use
the identical Bearer-token auth mechanism as private-app access tokens.** Same header, same
format:
```
Authorization: Bearer <HUBSPOT_SERVICE_KEY>
```
No different signing, no different endpoint prefix, no different SDK path — `gtm/hubspot.py`
can treat the Service Key exactly like a private-app token would have been treated. Where
Service Keys genuinely *differ* from legacy private apps (documented, but none of this
affects our code):
- Account-level credential, not tied to a user — survives a team member leaving.
- Can be rotated with a 7-day overlap grace period instead of rebuilding the integration.
- Has last-used timestamps / activity logging in the HubSpot UI.
- Scopes are limited to ones the creating user already has (same as private apps).
- **Does not support webhooks, UI extensions, or marketplace listing** — irrelevant here,
  we only make outbound CRM object writes (no webhooks in this pipeline).

Read the key from `.env` as `HUBSPOT_SERVICE_KEY` via `os.environ`/`python-dotenv`, same
pattern as every other provider in this project — never read `.env` directly.

## Scopes needed
Set when the Service Key is created (`Settings > Integrations > Service Keys`, "Add new
scope"), limited to what the creating user's account already has:
- `crm.objects.companies.read`, `crm.objects.companies.write`
- `crm.objects.contacts.read`, `crm.objects.contacts.write`

**Unverified**: whether these two write scopes alone are sufficient to also create
associations between contacts and companies, or whether a separate associations scope is
needed. Docs did not call out a distinct scope for the Associations v4 endpoints beyond the
object-level write scopes. If Task 7.1's live smoke gets a 403 specifically on the
associations call, that's the first thing to check (add `crm.objects.companies.write` /
`crm.objects.contacts.write` explicitly if not already granted, or look for a
`crm.associations.write`-style scope in the key's scope picker).

## API versioning note (pin v3/v4, know the newer option exists)
HubSpot moved to **date-based versioning** starting 2026-03-30: new paths look like
`/crm/objects/2026-03/companies` instead of `/crm/v3/objects/companies`, with 18 months of
support per dated version and breaking changes only twice a year (March/September). The
**legacy `/crm/v3/...` and `/crm/v4/...` paths still work** — v4 paths are scheduled to move
to unsupported status 2027-03-30, well past this project's timeline, and v3 has no announced
end-of-life. The task brief specifies "CRM v3" endpoints explicitly, so this doc uses the
`/crm/v3/objects/...` object endpoints and the `/crm/v4/associations/...` endpoint below —
pin those exact paths in code. If this project is still active near 2027, re-check this file
before the v4 associations path goes unsupported.

## 1. Upsert companies (batch)
`POST https://api.hubapi.com/crm/v3/objects/companies/batch/upsert`

Body:
```json
{
  "inputs": [
    { "id": "<value>", "idProperty": "<unique-property-name>", "properties": { "name": "AeroVault Cases", "domain": "aerovaultcases.com" } }
  ]
}
```
`id` + `idProperty` + `properties` per input; `idProperty` optional only if `id` is an actual
HubSpot record ID (`hs_object_id`), which we never have on first push.

**Important gotcha — company has no built-in unique property.** Per the docs: *"there
currently aren't any built-in unique properties for the Company record"* — `name` and
`domain` are both allowed to hold duplicate values across records and **cannot be passed as
`idProperty`** to this endpoint out of the box. To upsert-by-domain you'd need to first create
a custom property on the Company object marked "must be unique value" in HubSpot's UI (or via
the Properties API), then reference that property name as `idProperty`.

This matches the plan's own note for Task 7.1 ("**Idempotent via a domain-based dedupe/
search-before-create**") — that phrasing anticipates this exact constraint. Recommended
approach for `gtm/hubspot.py`, given we don't want to require the user to hand-create a custom
unique property before this ships: **search first, then create-or-update by record ID**,
not a literal call to `batch/upsert`:
1. `POST /crm/v3/objects/companies/search` with a filter on `domain` (`EQ` our prospect's
   domain) to look for an existing record.
2. If found → `PATCH /crm/v3/objects/companies/{companyId}` with the properties to update.
3. If not found → `POST /crm/v3/objects/companies` to create.
This is idempotent on our side without requiring any manual HubSpot property setup. The
literal `batch/upsert` endpoint above is documented here for completeness (and in case a
custom unique property gets set up later, e.g. for true batch efficiency), but Task 7.1
should default to the search-then-create/update path unless that's confirmed to be
unnecessary.

Company properties we map: `company` → `name`, `website` → `domain` (strip scheme/path,
HubSpot expects a bare domain, e.g. `tealdrones.com` not `https://tealdrones.com`).

Response: 200 (or 207 multi-status if a request had partial errors — **unverified**, the
batch/upsert page's exact status-code table did not render for this fetch; treat any non-2xx
as an error and any per-item `"status": "ERROR"` inside a 207 body as a per-company failure,
consistent with this project's log-and-skip convention).

## 2. Upsert contacts (batch)
`POST https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert`

Body:
```json
{
  "inputs": [
    { "id": "jane@tealdrones.com", "idProperty": "email", "properties": { "firstname": "Jane", "lastname": "Doe", "jobtitle": "VP Engineering", "hs_linkedin_url": "https://linkedin.com/in/janedoe" } }
  ]
}
```
Unlike companies, **`email` is a valid built-in `idProperty` for contacts** — no custom
property needed. `id` + `idProperty` + `properties` required per input.

**Gotcha, flagged not fully resolved**: docs state *"partial upserts are not supported when
using `email` as the `idProperty`"* for contacts — the exact operational meaning (does an
update via email-idProperty overwrite/blank omitted fields, or does it just mean something
else, e.g. can't PATCH-merge and must resend full property set?) was not confirmed from a
clean primary-source render in this pass. Task 7.1 should either confirm this empirically in
the live-smoke step (push a contact, upsert again with fewer fields, check if the omitted
field got cleared) or use a custom unique property as `idProperty` instead of `email` if that
turns out to matter, per HubSpot's own suggested workaround.

Response: same shape family as companies — `id`, `properties`, `createdAt`, `updatedAt`,
`archived` per contact on success.

Contact properties we map, from `Prospect` (`gtm/schema.py`): `contact_name` → split into
`firstname`/`lastname`, `contact_title` → `jobtitle`, `contact_linkedin` → `hs_linkedin_url`
(HubSpot's default LinkedIn URL property; confirmed to exist as a standard contact property,
grouped under "Social Media Information" — may not appear in default UI columns but is a
real, writable API property), `contact_emails` → `email` (note: `Prospect.contact_emails` is
stored as `"email (status)"`, parallel-list-joined for multiple contacts per company per the
schema comment — Task 7.1 needs to parse that format into one `email` string per contact
before building the upsert body).

## 3. Associate a contact with its company
`POST https://api.hubapi.com/crm/v4/associations/contact/company/batch/create`

Body:
```json
{
  "inputs": [
    {
      "from": { "id": "<contactId>" },
      "to": { "id": "<companyId>" },
      "types": [ { "associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 1 } ]
    }
  ]
}
```
Confirmed body shape: `types` is a **nested array** on each input (not a flat
`associationCategory`/`associationTypeId` pair at the input's top level) — an input can carry
multiple labels in one call.

Default `HUBSPOT_DEFINED` association type IDs for contact→company (cross-checked against two
independent sources, consistent):
- **`1`** — "Contact to Primary Company" (marks this as the contact's primary company; what we
  want, since each prospect contact belongs to exactly one company here).
- **`279`** — plain unlabeled "Contact to Company" (no primary flag).

Use `associationTypeId: 1` so the company shows as the contact's primary company in HubSpot's
UI. `associationCategory: "HUBSPOT_DEFINED"` (not `USER_DEFINED` — that's for custom labels we
haven't created).

Response (per HubSpot's association objects generally): `fromObjectTypeId`, `fromObjectId`,
`toObjectTypeId`, `toObjectId`, `labels`.

**Requires both the contact and company to already have real HubSpot record IDs** — so the
call order per prospect must be: create/update company → create/update contact(s) → associate,
using the `id` HubSpot returns from steps 1–2, not the domain/email used as `idProperty`.

## Rate limits (Free/Starter tier, private-distribution app or Service Key)
- **Burst**: 100 requests / 10 seconds (per app/key).
- **Daily**: 250,000 requests / account / day, resets at midnight in the account's configured
  time zone.
- Search endpoints (e.g. the company-search-by-domain fallback in section 1) have a stricter
  separate limit: **4 requests/second** — do not hammer search in a tight loop.
- Given this project's volume (a handful of companies per run, one company-search + one
  company-write + N contact-writes + N associations each), nowhere near either limit.

Response headers report remaining quota (case-insensitive):
- `X-HubSpot-RateLimit-Max` — burst-window cap
- `X-HubSpot-RateLimit-Remaining` — calls left in the 10s burst window
- `X-HubSpot-RateLimit-Daily-Remaining` — calls left today (OAuth-app requests are excluded
  from this specific header per the docs; not relevant to us since Service Keys aren't OAuth)

## Error handling
Follow this project's log-and-skip convention (same as `github_state.py`): any non-2xx from a
HubSpot call should be caught, logged to `data/errors.log`, and that company's HubSpot push
skipped — never crash the pipeline. HubSpot best-effort push runs after Sheet output, never
blocking it.
- `401` — bad/expired Service Key.
- `403` — missing scope, or (check `X-HubSpot-RateLimit-Remaining`/`-Daily-Remaining`) rate
  limit exhausted.
- `404` — object/record ID not found (e.g. associating with a company ID that doesn't exist).
- `429` — burst or daily limit hit; back off, or per convention, just log & skip rather than
  block the pipeline.

## Gotchas summary
- **`HUBSPOT_SERVICE_KEY` env var name** — Task 7.1 reads this, not `HUBSPOT_TOKEN`.
- **No built-in unique company property** — `batch/upsert` on companies can't key off
  `domain`/`name` without a manually-created custom unique property; default to
  search-by-domain → create-or-update-by-id instead (see section 1).
- **Contacts CAN key off `email`** directly via `batch/upsert`, but the "partial upserts not
  supported with `email` as idProperty" caveat is unconfirmed in its exact behavior — verify
  empirically in the live smoke (Task 7.2).
- **Associations require real HubSpot record IDs**, obtained only after the company/contact
  writes succeed — order matters: company → contact → associate.
- **Domain must be bare** (no `https://`, no path) when writing to the `domain` property.
- Missing/absent `HUBSPOT_SERVICE_KEY` should make `gtm/hubspot.py` a no-op stub returning 0,
  per this project's "optional-provider pattern" (same as every other provider whose key is
  absent) — never raise at import or at call time for a missing key.
