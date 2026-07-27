# AeroVault Cases — Voice Guide

> Drives the `draft` pipeline stage (cold-email generation). Companion to `company/ICP.md`
> (which drives Fit) — this file is the source of truth for *how* we sound, not *who* we target.

## Tone
Warm, consultative — relationship-first, not a hard sales pitch. Data-driven: lead with a
real, specific fact about the prospect (a win, a launch, a shipping gap), not a generic value
prop. Bold and charismatic, but never pushy — one real question or concrete offer per email,
not a stacked pitch.

## Format (locked, enforced by `draft`/QA)
- One email, no follow-up — 2 versions (v1/v2).
- A draft is only written when the signal supports one (gtm/draft.py::is_thin_signal); when
  it doesn't, pain_points/talking_points are the deliverable instead of a generic email.
- Subject line: under 40 characters, **trigger-first** — lead with the prospect's own
  event or pain (their contract win, launch, shipping gap), never with our product-line
  names (`AV-Field`, `AV-Micro`, `AV-Ops`, `AV-Convoy` — the prospect has never heard them)
  and never with the bare word "case". Good: *"Switchblade 400 field kit?"*. Bad:
  *"AV-Field case for the Switchblade?"*.
- Body: capped at ~150 characters — one or two sentences, no more.
- Personalization variables: `{FIRST_NAME}`, `{COMPANY}`.
- No links in the body.
- Content source: pull the hook from `Prospect.outreach_angle` (already computed by the
  `signals` stage) — don't re-derive an angle here. Pull supporting specifics from
  `buying_signals` / `key_news` / `fit_reason`.

## Banned phrases / openers
No generic openers: "I hope this finds you well", "I wanted to reach out", "just checking in".
No corporate filler: "circle back", "synergy", "game-changer", "solution" (as a noun standing
in for the product), "leverage" (as a verb), "touch base", "low-hanging fruit".
No hedge-padding: "just wanted to", "I was wondering if maybe".

## Specificity (no vague value-prop claims)
Every value-prop claim must name a concrete mechanism or spec difference — a MIL-STD-810H
drop-test rating, an exact dimension, a cited competitor weakness (`competitor_weaknesses`,
from `gtm/displace.py`'s research step). Never a bare comparative with nothing behind it:
banned — "protects better", "keeps your gear safe", "built for reliability" — unless
immediately followed by the specific fact that backs it.

## Signature
Every draft closes with:
```
Alex Rivera
Sales, AeroVault Cases
```

## Example emails (style anchor — Teal Drones, defense/NDAA angle)
Real prospect, real buying signal (US Army SRR program win), matched to ICP.md's
"Defense/NDAA win" outreach angle. Use these as the tone/length reference, not a template to
fill in — every real draft should read this specific, using that prospect's own signals.

**Initial, v1** — *"Teal's SRR win + transport?"*
> {FIRST_NAME} — saw Teal's SRR win. We build MIL-STD cases sized to the Teal 2, made in the
> US like you. Worth 10 min this week?

**Initial, v2** — *"Congrats on SRR — quick Q"*
> {FIRST_NAME}, congrats on SRR. Curious what Teal 2 units ship in today — we build
> MIL-STD-810H cases sized to it. Quick call?

Each closes with the signature above.

## Email structure (per email)
1. **Opening line** — a real, specific fact about the prospect (a win, launch, or shipping gap), not a generic greeting.
2. **Value prop** — a use case + social proof + the pain it removes. AeroVault Cases is a
   demo company with no real customers: social proof must be **category-level only**
   ("other defense sUAS makers ship in our cases") — never a named client or logo. Also
   name a concrete mechanism or spec difference (a MIL-STD-810H drop-test spec, a cited
   competitor weakness, an exact dimension) — never a bare comparative like "protects
   better" with nothing backing it. Example framing: "Other {segment} drone makers run
   into {xyz} — our {mechanism} fixes it."
3. **Close** — one closed-ended (yes/no) call to action. Never stack asks. Prefer a low-pressure ask, e.g. a negative-CTA: "Do you think it'd be a bad idea to sit and chat for 15 min?" or a single real question: "Do you run into {problem}, and how do you handle it today?"

## Persona tailoring (pitch by seniority)
The `draft` prompt injects the top contact's **persona tier** (from `gtm/persona.py`). Lean the value prop toward the matching rule:

- **finance** (CFO/controller/VP-Finance) — pitch the **hard numbers**: cost-per-case vs a damaged/replaced drone, payback period, TCO, budget defensibility. More numeric than c-suite — they want the financial case airtight, not the strategic story.
- **c-suite** — pitch the **business outcome**: ROI, cost, what the case program wins or saves them. Skip process detail. They care about the number, not the workflow.
- **director** (director/head-of) — pitch **ownership and accountability**: fewer fires reaching their desk, a program that runs predictably, they look good to their exec. Bridges outcome and process — more than a manager cares about, less pure-numbers than c-suite.
- **manager** — pitch **process and team**: smoother logistics, less firefighting, a team that isn't fighting broken gear. Do NOT lead with money saved — it's not their metric.
- **ic** — pitch the **day-to-day**: easier handling, less hassle in the field, people happier doing the work.
- **unknown** — no contact tier available; write to the company's segment/angle generically, no seniority lean.
