# AeroVault Cases — Voice Guide

> Drives the `draft` pipeline stage (cold-email generation). Companion to `company/ICP.md`
> (which drives Fit) — this file is the source of truth for *how* we sound, not *who* we target.

## Tone
Warm, consultative — relationship-first, not a hard sales pitch. Data-driven: lead with a
real, specific fact about the prospect (a win, a launch, a shipping gap), not a generic value
prop. Bold and charismatic, but never pushy — one real question or concrete offer per email,
not a stacked pitch. It should read like one person who did their homework wrote it, not like
a merge field got filled.

## Format (locked, enforced by `draft`/QA)
- One email, no follow-up — 2 versions (v1/v2).
- A draft is only written when the signal supports one (gtm/draft.py::is_thin_signal); when
  it doesn't, pain_points/talking_points are the deliverable instead of a generic email.
- Subject line: under 60 characters, **trigger-first or airframe-first** — lead with the
  prospect's own event, their airframe, or their pain, never with our product-line names
  (`AV-Field`, `AV-Micro`, `AV-Ops`, `AV-Convoy` — the prospect has never heard them) and
  never with the bare word "case" alone. Good: *"field kit for {{airframe_name}}"*,
  *"what's protecting {{airframe_name}} in transit?"*. Bad: *"AV-Field case for the Teal 2"*.
- Body length is set by fit tier (see "Length by tier" below) — not one cap for everything.
- Plain-text paragraphs separated by blank lines. No links in the body. No bullet lists.
- Personalization variables (double-brace): `{{first_name}}`, `{{company_name}}`,
  `{{airframe_name}}`, `{{trigger_event}}`, `{{case_line}}`, `{{reference_customer}}`,
  `{{sender_name}}`.
- Content source: pull the hook from `Prospect.outreach_angle` (already computed by the
  `signals` stage) — don't re-derive an angle here. Pull supporting specifics from
  `buying_signals` / `key_news` / `fit_reason` / `community_signals`.

## Length by tier
The fit tier (`Prospect.status`) sets how much room the email gets. A Tier 2 prospect has a
thinner story, so a long email there reads as padding.

| Fit tier | status | Blocks | Body length |
|---|---|---|---|
| Tier 1 | `priority` | all 4 (trigger · what we build · pain · close) | ~450–700 characters |
| Tier 1, no pain source | `priority` | 3 (trigger · what we build · close) — Block 3 omitted, nothing researched to ground it | ~250–400 characters |
| Tier 2 | `keep` | 3 (trigger/opener · what we build · close) — pain block folds into the value line | ~250–350 characters |

Tier 3 (`drop`) is never drafted.

The `~` is real — these are targets, not byte limits, and `gtm/draft.py::check_body_length`
enforces them with 20% slack either side. It exists to catch drift (prompt-only caps drift
upward across a batch), not to churn a 357-character body against a "~350" target.

## Email structure (per email)

**Block 1 — opener.** `{{first_name}},` on its own line, then one line naming their real
trigger: *"Saw {{company_name}}'s {{trigger_event}} — congrats."* No generic greeting, no
banned opener. The trigger must come from `buying_signals` / `key_news` — never invented.

*No fresh trigger?* Signals older than the recency cutoff are marked `[stale]` and undated
ones `[undated]` (`gtm/enrich.py`); neither may open an email. Congratulating someone in
July 2026 on a 2025 certification is the clearest tell of an automated send. When nothing
fresh exists, drop the congratulation entirely and open on their current setup as an
observation or a genuine question — *"Your {{airframe_name}} kit travels a lot more than
most — how is it packed today?"* Stale signals still inform the pitch; they just never lead.

**Block 2 — what we build.** Concrete and specific: foam-fitted to one airframe (aircraft +
controller + batteries + payload seated together), sealed against water and dust, drop- and
vibration-tested for transport, made in the US. Name a mechanism or what a spec *does*, never
a bare comparative — and never a spec **code** (see below). Social proof goes here (see below).

**No spec codes in the email** (locked 2026-07-29, enforced by `gtm/draft.py::check_spec_jargon`).
`IP67`, `IP68`, `MIL-STD-810H`, `MIL-SPEC` are banned from every subject line and body. They are
true (see `company/ICP.md`) and they stay in `talking_points` — a rep needs them on the call —
but a cold reader decodes nothing from a certification string, and repeating the same code in
the same sentence position across a batch is what makes a batch read like spec-sheet
copy-paste (8 of 10 bodies on run us-drone-19). Say what the spec buys them instead:

| Instead of | Write |
|---|---|
| IP67 | sealed against water and dust · rain and dust stay out |
| MIL-STD-810H | drop- and vibration-tested for transport · survives a truck bed and a cargo hold |

**Block 3 — the pain (Tier 1 only).** The consequence *they* feel, tailored to the contact's
persona tier — see "Persona tailoring". Ground it in `community_signals` or `competitor_weaknesses` — those are the only two fields
that record an actual complaint. Other fields (current shipping, trigger events) are not
evidence that anything hurts, and never license a pain claim. When neither pain source exists,
omit Block 3 entirely: never assert a consequence they experience, and never attribute a
claim to operators, buyers, customers, forums, or groups.

**Block 4 — close.** One low-pressure, closed-ended ask. Default to the negative-CTA form:
*"Would it be a bad idea for us to grab 15 minutes and see if the math works for
{{airframe_name}}?"* A single genuine question (*"Is packing/kitting something your team has
dialed in, or still ad hoc?"*) may precede it. Never stack asks.

**Signature.** `{{sender_name}}` on its own line. Nothing after it.

## Social proof — `{{reference_customer}}` only
AeroVault is a demo company with no real customers, so a hardcoded company name in a draft
would be a fabricated claim. Named social proof is written as the literal token
`{{reference_customer}}` — filled in at send time with a real reference:

> "{{reference_customer}} runs our {{case_line}} line across their tactical lineup."

**Hard rule:** `{{reference_customer}}` must never be filled with the recipient's own
company. A draft must never contain a hardcoded company name other than
`{{company_name}}` — naming another prospect from the same run as a customer is the failure
mode this token exists to prevent (`gtm/draft.py::check_reference_customer` enforces it).

Where no reference fits, fall back to category-level only — *"defense sUAS makers we work
with"* — never a named client or logo written out literally.

The token is filled at output time from `company/outreach.md`
(`gtm/render.py::pick_reference_customer`), which drops the recipient and every run-mate
before picking, then falls back to the category phrase. A token with nothing behind it is
left standing and the row is blocked from the sheet — never sent with the braces showing.

## Banned phrases / openers
No generic openers: "I hope this finds you well", "I wanted to reach out", "just checking in".
No corporate filler: "circle back", "synergy", "game-changer", "solution" (as a noun standing
in for the product), "leverage" (as a verb), "touch base", "low-hanging fruit".
No hedge-padding: "just wanted to", "I was wondering if maybe".

## Banned skeleton
Do not write the compressed one-liner shape:

> ~~"{{first_name}} — saw {{trigger_event}}. We build rugged cases sized to it. Worth a quick look?"~~

It technically satisfies every rule above and still reads like a bot: no pain block, no
reason to care, a zero-cost ask. v1 and v2 must differ in **structure**, not just wording —
one leads with the congratulation, the other leads with a question about their current setup.
Two persona tiers at the same company must never receive the same sentence skeleton.

## No repeated sentences across the batch
(locked 2026-07-29, enforced by `gtm/draft.py::check_batch_repetition`)

**No sentence may appear verbatim in two different companies' drafts in the same run.** Not
the value line, not the social-proof line, not the close. Every prospect has its own
`outreach_angle` and `segment` — an identical sentence in two of them means the angle was
never used, and the rows sit next to each other in the sheet where a reader sees it instantly.
Run us-drone-19 shipped *"{{reference_customer}} runs {{case_line}} the same way."* in 9 of 10
bodies and the same five-word close in 5 of 10.

The negative-CTA close is a **shape, not a script**: "Would it be a bad idea…" names the form,
and each company's close still has to end on that company's own specifics. Copying the
example emails' closes word-for-word across a batch is the failure this rule exists to stop.

## Specificity (no vague value-prop claims)
Every value-prop claim must name a concrete mechanism or spec difference — a drop-test rating
in plain words (not its code), an exact dimension, a cited competitor weakness
(`competitor_weaknesses`, from `gtm/displace.py`'s research step), or a real operator
complaint (`community_signals`).
Never a bare comparative with nothing behind it: banned — "protects better", "keeps your gear
safe", "built for reliability" — unless immediately followed by the specific fact that backs it.

## Displacing an in-house enclosure (`oem-inhouse-displacement`)
Some prospects don't buy a case at all — they build one. A drone-in-a-box dock, a base
station, a self-molded hard case shipped with every unit (`inhouse_case`, from
`gtm/displace.py::detect_inhouse_case`). Do **not** write the swap pitch at them: there is
no Pelican to beat, and "we protect better than your case" reads as an insult to a product
their own engineers designed.

Pitch the line item instead — they are running a small case factory next to a drone
factory: tooling and mold spend, a revision every time the airframe changes, spares and
warehousing, RMA handling on a part that isn't their product. We absorb that; they get
their engineers back. Credit the enclosure ("your dock is clearly built for the mission") —
the argument is that owning its manufacture is expensive, not that it's bad.

Never claim a specific in-house cost figure we haven't been told. Cite
`competitor_weaknesses` (which for this segment holds researched tooling/warehousing/field
complaints) or say nothing.

## Persona tailoring (pitch by seniority)
The `draft` prompt injects the top contact's **persona tier** (from `gtm/persona.py`). Block 3
is where this bites hardest — the pain must be the pain *that tier* is measured on.

- **finance** (CFO/controller/VP-Finance) — pitch the **hard numbers**: cost-per-case vs a
  damaged/replaced drone, payback period, TCO, budget defensibility. More numeric than
  c-suite — they want the financial case airtight, not the strategic story.
- **c-suite** — pitch the **business outcome**: warranty claims from units damaged in transit,
  slower sales cycles when buyers don't trust a soft case around a $1k+ airframe, ROI. They
  care about the number, not the workflow.
- **director** (director/head-of) — pitch **ownership and accountability**: fewer fires
  reaching their desk, a program that runs predictably, they look good to their exec.
- **manager** — pitch **process and team**: same setup/teardown every time, no loose gear, no
  packing guesswork before a deployment, the HQ-to-field handoff boring and repeatable. Do
  **NOT** lead with money saved — it's not their metric.
- **ic** — pitch the **day-to-day**: a tech opens the case and everything is exactly where it
  should be, less hassle in the field.
- **unknown** — no contact tier available; write to the company's segment/angle generically,
  no seniority lean.

---

# Example emails (style anchors)
These are the reference for length, rhythm, and structure. Use them as anchors, not
templates to fill — every real draft carries that prospect's own signals.

## Tier 1 · c-suite / founder — ROI & business-outcome framing

**v1** — *"{{airframe_name}} + a case that survives the field"*

> {{first_name}},
>
> Saw {{company_name}}'s {{trigger_event}} — congrats.
>
> We build custom transport cases for sUAS manufacturers — foam-fitted to one airframe,
> sealed against water and dust, drop-tested for transport, made in the US.
> {{reference_customer}} runs our {{case_line}} line across their tactical lineup.
>
> Companies at {{company_name}}'s stage usually lose money one of two ways: warranty claims
> from damaged units in transit, or slower sales cycles because buyers don't trust a soft
> case around a $1k+ airframe. A dedicated case usually pays for itself inside the first few
> damaged-unit claims it prevents.
>
> Would it be a bad idea for us to grab 15 minutes and see if the math works for
> {{airframe_name}}?
>
> {{sender_name}}

**v2** — *"what's protecting {{airframe_name}} in transit?"*

> {{first_name}},
>
> Congrats on {{trigger_event}}. Curious what {{company_name}} ships {{airframe_name}} in today.
>
> We're AeroVault — custom foam-fit transport cases, US-made, built around one airframe at a
> time. Defense and public-safety sUAS makers ({{reference_customer}} among them) use us
> specifically because a damaged unit in the field costs more than the case ever would.
>
> If {{airframe_name}} is doing meaningful volume, the case usually becomes a line item that
> reduces returns and RMAs rather than adding cost.
>
> Worth 15 minutes to see if the numbers make sense for you?
>
> {{sender_name}}

## Tier 1 · director / ops-product-logistics manager — process & team framing, no cost pitch

**v1** — *"field kit for {{airframe_name}}"*

> {{first_name}},
>
> Saw {{company_name}} shipped {{trigger_event}} — nice work.
>
> We make custom transport cases fitted to one airframe (controller, batteries, payload, all
> seated). Field teams at companies like {{reference_customer}} use them so setup/teardown is
> the same every time, no loose gear, no packing guesswork before a deployment.
>
> Do you run into that — field crews improvising packing, or gear getting knocked around
> between missions? Curious how {{company_name}} handles it today.
>
> Would it be a bad idea to hop on for 15 minutes and walk through it?
>
> {{sender_name}}

**v2** — *"how does {{company_name}}'s field team pack {{airframe_name}}?"*

> {{first_name}},
>
> Congrats on {{trigger_event}}.
>
> We build foam-fit transport cases around specific sUAS airframes — the kind of setup where
> a tech in the field can open the case and everything's exactly where it should be, every
> time. It's less about the case and more about making the handoff between HQ and the field
> boring and repeatable.
>
> Is packing/kitting something your team already has dialed in, or still a bit ad hoc?
>
> Open to 15 minutes to see if this is useful for you?
>
> {{sender_name}}

## Tier 2 · c-suite — lighter touch, shorter

**v1** — *"{{airframe_name}} transport"*

> {{first_name}},
>
> Quick one — we build US-made, custom-fit transport cases for sUAS manufacturers
> ({{reference_customer}} is a customer). Companies shipping airframes like
> {{airframe_name}} usually see it pay off through fewer damaged-unit returns.
>
> Worth a short call to see if it's relevant for {{company_name}}?
>
> {{sender_name}}

**v2** — *"quick question on {{airframe_name}}"*

> {{first_name}},
>
> We make custom transport cases for drone manufacturers, fitted to one airframe at a time.
> Given {{airframe_name}}'s footprint, it'd be a fit for our {{case_line}} line.
>
> Would it be a bad idea for us to spend 15 minutes on this?
>
> {{sender_name}}

## Tier 2 · director / manager — lighter touch, shorter

**v1** — *"kitting for {{airframe_name}}"*

> {{first_name}},
>
> We build foam-fit cases so field teams can grab one case and have everything for
> {{airframe_name}} ready to go — no separate bags for batteries, controller, payload.
>
> Does {{company_name}}'s team pack that way today, or is it more improvised?
>
> Happy to jump on a quick 15-minute call if it's useful.
>
> {{sender_name}}

**v2** — *"{{company_name}} field gear"*

> {{first_name}},
>
> Curious how your field team currently transports {{airframe_name}} — we build custom cases
> so the whole kit stays organized and protected between deployments.
>
> Would 15 minutes to compare notes be a bad idea?
>
> {{sender_name}}
