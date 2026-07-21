# Monitor (recurring watch) — design

## Problem

Today the pipeline is entirely one-shot: `gtm/run.py` stages scrape/extract/fit
a company once, at the moment you run them. There's no way to keep watching a
prospect's site for a change (new drone model, NDAA cert, rugged-case switch)
or keep an open-ended search running for newly-appearing ICP-fit manufacturers
— you'd have to remember to re-run the pipeline by hand. Firecrawl's
Monitoring API (`POST /v2/monitor`) does exactly this: recurring
scrape/crawl/search checks on a schedule, with an optional AI judge against a
goal. Not yet integrated — `docs/tools/firecrawl.md` only documents the
one-shot `/v2/scrape` endpoint used as scraper fallback #1.

## Scope

- A new conversational trigger ("monitor X", "watch this for changes", "alert
  me if X happens", "keep an eye on...") that walks through clarifying
  questions and creates a Firecrawl monitor.
- A new `gtm/monitor.py` module wrapping Firecrawl's monitor
  create/list/check/delete calls.
- New `gtm/run.py` subcommands: `monitor create <config.json>`, `monitor
  list`, `monitor check <name>`, `monitor apply <name> <answer.json>`,
  `monitor delete <name>`.
- A new `.agents/skills/monitor/SKILL.md` (symlinked to `.claude/skills/monitor`,
  matching every other skill in this repo) driving the conversational flow.
- **Out of scope:** webhook receivers (no persistent server in this project —
  results are pulled on demand, never pushed to us), auto-expiry (explicitly
  rejected — an open-ended monitor stays live until you delete it), any UI
  beyond the existing CLI + chat loop.

## Trigger rule (must be airtight)

Semantic/intent-based, not a literal command word. Triggers on an explicit ask
to watch or track something *ongoing*:

- Triggers: "monitor Teal Drones", "watch their site for changes", "alert me
  if they announce a new model", "keep an eye on drone manufacturers
  launching this quarter".
- Does NOT trigger: "check their site", "research Teal Drones", "what's new
  with them" — those are one-off asks, handled by `prospect-research` /
  `company-research`. Running a one-off check is never itself grounds to spin
  up a recurring monitor.

The distinguishing signal is **ongoing-ness** — the user is asking to be told
about something that hasn't happened yet, on a recurring basis, not asking
for a snapshot of what's true right now.

## Architecture

### `gtm/monitor.py`

Same shape as `gtm/contacts.py`: Pydantic models + isolated network calls,
reusing the `FIRECRAWL_API_KEY` env var already read by
`gtm/scrape.py::scrape_firecrawl`.

```python
class MonitorConfig(BaseModel):
    name: str
    target_type: Literal["page", "website", "search"]
    urls: list[str] = []       # page/website targets
    goal: str                  # always required — see "Always ask a goal" below
    schedule_text: str         # natural-language, passed straight to Firecrawl
    run: str = ""              # page/website only: which pipeline run this is tied to
    company: str = ""          # page/website only: which prospect this is tied to
    end_condition: str = ""    # descriptive only, not enforced (see Duration below)

class Monitor(BaseModel):
    firecrawl_id: str
    name: str
    target_type: str
    schedule_text: str
    estimated_credits_per_month: float

class MonitorCheck(BaseModel):
    checked_at: str
    changed: bool
    results: list[dict]        # raw Firecrawl check payload (page diffs or search hits)

def create_monitor(config: MonitorConfig) -> Monitor: ...
def list_monitors() -> list[Monitor]: ...
def get_monitor_check(firecrawl_id: str) -> MonitorCheck: ...
def delete_monitor(firecrawl_id: str) -> None: ...
```

### Local state — `data/monitors/<name>.json`

The only local state this feature needs, same "local files as state"
convention as `data/runs/<run>/prospects.json`:

```json
{
  "firecrawl_id": "...",
  "name": "teal-drones-watch",
  "target_type": "page",
  "run": "teal-demo",
  "company": "Teal Drones",
  "end_condition": "until the Teal outreach campaign wraps"
}
```

This is the mapping that tells `monitor check` which prospect a page/website
monitor's findings belong to. Search-type monitors don't have a `run`/
`company` — their findings are brand-new candidate companies, not updates to
an existing prospect.

**Write-after-success only**: the local file is written *after* Firecrawl
confirms creation, never before. A failed remote call leaves zero local
state — no orphaned mapping file claiming a monitor exists that doesn't.

### CLI (`gtm/run.py`)

- **`monitor create <config.json>`** — the skill writes this config file
  after its conversational Q&A (same "prompt printed, answer goes in a JSON
  file" convention as `fit`/`signals`/`draft`), then this command calls
  `create_monitor` and writes the local mapping file.
- **`monitor list`** — calls `list_monitors()`, prints name / target /
  schedule / `estimated_credits_per_month` for every monitor Firecrawl has on
  file. This is the safety net against a forgotten, still-billing monitor —
  since there's no auto-expiry, this is the only thing standing between you
  and paying for a monitor nobody's watching anymore.
- **`monitor check <name>`** — resolves `<name>` to a `firecrawl_id` via the
  local mapping file, calls `get_monitor_check`. Two paths:
  - **page/website target, tied to a run+company**: if `changed`, prints a
    Claude judgment prompt (same house style as `signals`) — "here's what
    changed, decide how it folds into this prospect's `buying_signals`/
    `key_news`" — and raises `CheckpointPending` pointing at `monitor apply`.
  - **search target**: prints the new/candidate results directly (company
    names + URLs). Nothing in `prospects.json` to update — these are
    companies that don't exist in any run yet. You decide whether to feed
    them into a new `gtm.run start`.
- **`monitor apply <name> <answer.json>`** — merges the Claude-judged answer
  into the tied prospect's record in `data/runs/<run>/prospects.json`
  (`buying_signals`/`key_news`), same pattern as `cmd_signals`.
- **`monitor delete <name>`** — deletes remotely via Firecrawl, then removes
  the local `data/monitors/<name>.json`.

### The skill (`monitor`)

1. **Confirm the trigger** — if genuinely ambiguous whether this is a one-off
   check or an ongoing watch, ask; don't guess wrong on a real API call.
2. **Clarify target** — a known company/URL → page/website target; an
   open-ended ask ("find more drone manufacturers like Teal") → search
   target.
3. **Clarify schedule** — plain language ("every day", "every Monday"),
   passed straight through as Firecrawl's `schedule.text` — no cron math on
   our side.
4. **Always ask a goal** — regardless of target type, ask what the monitor
   should actually watch *for* (e.g. "a new drone model announcement", "an
   NDAA certification"). This becomes `MonitorConfig.goal` and enables
   Firecrawl's AI judge on every monitor we create — never create a
   judge-less monitor, since an un-judged monitor just means you manually
   read raw diffs later, defeating the point.
5. **Clarify end condition** — plain language ("until the campaign wraps",
   "until I say stop"), stored as descriptive metadata only. **No
   auto-expiry** — the skill explicitly tells you this means `monitor list`
   is the only thing between you and a monitor that quietly keeps billing.
6. **Cost preview + explicit confirm** — before writing the config JSON or
   calling `create_monitor`, compute an estimate client-side from Firecrawl's
   published per-check credit table (page/website: 1 credit/URL/check;
   search: 2 credits/10 results/check, +1/judged result) × the schedule
   frequency. Show the number, require an explicit "yes, create it" before
   proceeding — Firecrawl's create call both estimates *and* creates in one
   shot, so this confirmation must happen in the skill's conversation, not
   after the API call.
7. Ends with the same Self-improvement clause as every other skill in this
   repo.

## Data flow

```
you: "monitor Teal Drones for a new NDAA cert"
  -> skill recognizes ongoing-watch intent (not a one-off check)
  -> skill asks: schedule? goal (already given)? end condition?
  -> skill computes cost estimate, you confirm
  -> skill writes monitor-config.json
  -> `python -m gtm.run monitor create monitor-config.json`
       -> gtm/monitor.py::create_monitor() -> Firecrawl POST /v2/monitor
       -> data/monitors/teal-drones-watch.json written (write-after-success)

...days later...
you: "check my monitors"
  -> `python -m gtm.run monitor list`         (safety net, all active monitors + est. cost)
  -> `python -m gtm.run monitor check teal-drones-watch`
       -> gtm/monitor.py::get_monitor_check() -> Firecrawl GET check
       -> changed=true -> prints Claude judgment prompt
  -> you answer, save to monitor-answer.json
  -> `python -m gtm.run monitor apply teal-drones-watch monitor-answer.json`
       -> merges into data/runs/teal-demo/prospects.json (buying_signals/key_news)
```

## Error handling

- Missing `FIRECRAWL_API_KEY` — clear error at `create_monitor`/
  `list_monitors`/`get_monitor_check` call time, no partial state.
- Monitor name collision on create — surfaced as an error before any network
  call (check `data/monitors/<name>.json` doesn't already exist).
- Any Firecrawl API error (network, non-2xx) on `create_monitor` — raised,
  local mapping file never written (write-after-success, per Architecture
  above) — no orphaned local state.
- `monitor check`/`monitor delete` on an unknown `<name>` — clear error, not
  a silent no-op.

## Testing

`tests/test_monitor.py`, following the project's existing per-stage
fixture-test convention (see `tests/test_output.py`'s `FakeWorksheet` for the
pattern this mirrors):

- `create_monitor`: success path (writes local mapping file with correct
  `run`/`company` for page/website, omits them for search), API-error path
  (no local file written), name-collision path (rejected before any network
  call).
- `list_monitors`: parses Firecrawl's list response into `Monitor` objects.
- `get_monitor_check`: `changed=true`/`changed=false` paths, page/website vs.
  search result shapes.
- `delete_monitor`: removes remote + local file; unknown name errors.
- `cmd_monitor_check`/`cmd_monitor_apply` in `gtm/run.py`: page/website
  target prints judgment prompt and raises `CheckpointPending`; search
  target prints candidates directly with no `CheckpointPending`.
- 1 live smoke test against Firecrawl's real API (create → check → delete),
  per the project's one-live-smoke-per-slice convention.

Docs: `docs/tools/firecrawl.md` gets a new Monitoring section (install/auth
already covered by the existing scrape section; add create/list/check/delete
call shapes, the credit-cost table, and the "estimate happens client-side
before create, since Firecrawl's create call estimates *and* commits in one
shot" gotcha) — required before `gtm/monitor.py` is coded, per this project's
tool rule. `docs/PLAN.md` gets a new stage entry. `docs/data-flow.html` gets
a new node once this ships (out of scope for this spec — a docs-sync task,
not a design decision).
