# GitHub REST API (Issues) — per-run state machine (Slice 6)

Fetched from docs.github.com/en/rest (issues/issues, issues/labels, issues/comments,
authentication, rate-limits, api-versions, permissions-required-for-fine-grained-pats,
scopes-for-oauth-apps) on 2026-07-19. Read this before writing `gtm/github_state.py`
(Task 6.1). Repo: `VladimirMickic/GTM-Zoki`. REST only — no `gh` CLI, call the API
directly with Python `requests`.

## Auth
PAT read from `.env` as `GITHUB_TOKEN` (do not read `.env` directly — load via
`os.environ`/`python-dotenv` like the rest of this project's providers).

Header: `Authorization: Bearer $GITHUB_TOKEN`. Docs state both `Bearer` and the older
`token` prefix are currently accepted for PATs, but `Bearer` is the form shown in
current examples — use that.

Also required on every call:
- `Accept: application/vnd.github+json`
- `X-GitHub-Api-Version: 2022-11-28` — pin this exact value. Docs show a newer
  `2026-03-10` version now exists, but `2022-11-28` is still fully supported (listed
  end-of-support March 10, 2028) and is the version nearly all current examples/blog
  posts assume. Omitting the header defaults to `2022-11-28` anyway, but send it
  explicitly so behavior can't drift under us if GitHub changes the default.
- `Content-Type: application/json` on POST/PUT bodies.

**Scope needed** — document both, pick one when creating the token:
- Classic PAT: `repo` scope (full control of private repos, covers issues/labels/comments).
  `public_repo` is not enough if `GTM-Zoki` is private.
- Fine-grained PAT (preferred by GitHub going forward): repository access scoped to
  `GTM-Zoki`, permission **"Issues" = Read and write**. Docs confirm this single
  permission covers create-issue, add/replace-labels, and create-comment.

## 1. Create an issue (one per pipeline run)
`POST https://api.github.com/repos/{owner}/{repo}/issues`

Body:
```json
{
  "title": "GTM run: teal-demo",
  "body": "Run started ...",
  "labels": ["run:teal-demo", "stage:input", "status:running"]
}
```
`labels` is an array of plain label-name strings (not objects). `title` is required;
`body`/`labels` optional.

Response (201): use `number` (the issue number — needed for every later labels/comments
call), `id`, `html_url`. `state` will be `open`.

Note from docs: labels are silently dropped on issue creation if the token/user lacks
push access — not a concern here since we own the repo, but worth knowing if this ever
runs under a lower-privilege token.

## 2. Replace an issue's labels (stage/status/run transitions)
`PUT https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels`

Confirmed **PUT**, not PATCH — this is the "set the full label set" endpoint. Body:
```json
{ "labels": ["run:teal-demo", "stage:fit", "status:running"] }
```
This **replaces all labels** on the issue (docs: "removes any previous labels and sets
the new labels"). Every call must therefore send the complete desired label set for all
three dimensions (`run:*` / `stage:*` / `status:*`), not just the one that changed —
`set_stage_labels` (Task 6.1) needs to read-modify-write the full set, not append.

Passing `{"labels": []}` clears all labels (documented explicitly).

Response: 200, JSON array of the resulting label objects (`id`, `name`, `color`,
`description`, `default`, ...).

**Unverified — flag for Task 6.1/6.3**: the docs page did not state whether labels that
don't yet exist on the repo are auto-created by this PUT, or whether it errors/silently
drops unknown label names. Do not assume auto-create. Before relying on it, either (a)
empirically test against `GTM-Zoki` in Task 6.1, or (b) safer: pre-create all
`run:*`/`stage:*`/`status:*` labels we'll ever use via `POST /repos/{owner}/{repo}/labels`
once at setup time (a one-off script or manual step), so this call never depends on
auto-create behavior either way.

(Separately, `POST .../issues/{issue_number}/labels` — not PUT — *adds* to the existing
set instead of replacing it. Not what we want here since our labels move across
dimensions, but worth knowing the distinction exists if a future need calls for additive
labeling instead of full-replace.)

## 3. Create a comment (checkpoint-pending messages)
`POST https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments`

Body:
```json
{ "body": "Checkpoint: fit review pending for 6 prospects. Run `python -m gtm.run fit ...`" }
```
Single required field, `body` (string). Response (201): `id`, `body`, `html_url`,
`created_at`. We don't currently need any response field beyond confirming 201 (no need
to store the comment id for this project's use case, but it's there if a later slice
wants to edit/delete a checkpoint comment).

## Rate limits
Primary limit for an authenticated PAT: **5,000 requests/hour** (shared across all REST
calls made with that token). Given this project's low run volume (one issue + a handful
of label-replace/comment calls per pipeline run), we will not come close to this.

Read remaining quota from response headers on every response (header names are
case-insensitive over HTTP, docs show them lowercase):
- `x-ratelimit-limit` — cap for the window
- `x-ratelimit-remaining` — calls left
- `x-ratelimit-used` — calls used so far
- `x-ratelimit-reset` — UTC epoch seconds when the window resets

Per this project's "log & skip" convention: `github_state.py` should check
`x-ratelimit-remaining` (or catch a 403/429) and log-and-skip the GitHub-state-update
call rather than crash the pipeline — a GitHub Issue update failing should never take
down a scrape/fit/enrich run.

**Secondary rate limits** also apply and are more likely to matter than the primary
5,000/hr cap for our low-but-bursty comment/label-replace pattern:
- Max 100 concurrent requests (irrelevant, we're sequential).
- Content-creation actions (issues, comments) capped at **80/minute and 500/hour**
  specifically — this is the one to actually watch, since every stage transition posts
  a comment/label update.
- Exceeding either limit returns 403 or 429; if no `retry-after` header is present,
  back off at least 60s before retrying (or just log & skip per convention, don't block
  the pipeline waiting).

## Error response shapes
- `401` — bad/missing token.
- `403` — either a permissions problem (token lacks `repo`/Issues:write) or a rate limit
  hit; check body/headers to disambiguate (`x-ratelimit-remaining: 0` = rate limit).
- `404` — repo or issue number doesn't exist (or token can't see it — GitHub returns 404
  rather than 403 for private-repo visibility, to avoid leaking existence).
- `422` — validation failed (e.g. malformed `labels` field, empty `title`). Body is
  `{"message": ..., "errors": [...]}`.
- `429` — secondary rate limit (see above).

All are plain JSON bodies with a `message` field at minimum — treat any non-2xx as a
provider error, log & skip, per this project's convention (same pattern as the scraper/
email-provider adapters).

## Gotchas
- **Idempotency**: none of these endpoints are idempotent. Calling "create issue" twice
  for the same run creates two issues. `open_run_issue` (Task 6.1) must be safe to call
  once per run — e.g. only call it at run-start, and persist the returned issue number
  in run state (`data/runs/<run>/...`) so later stages reuse it instead of re-creating.
- **Label PUT replaces everything** (see above) — `set_stage_labels` must always pass the
  full three-dimension label set, computed from current run state, not a delta.
- **Label auto-create on PUT is unverified** — see flag under section 2. Safer path:
  pre-create the label set on the repo once, don't depend on implicit creation.
- Don't confuse `POST .../labels` (additive) with `PUT .../labels` (replace-all) — easy
  mistake, we want PUT.
- `X-GitHub-Api-Version: 2022-11-28` should be pinned explicitly and revisited
  periodically — GitHub does version the REST API now (a `2026-03-10` version exists per
  the docs fetch during this task), so don't assume no-header behavior stays stable
  forever.
