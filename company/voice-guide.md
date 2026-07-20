# AeroVault Cases — Voice Guide

> Drives the `draft` pipeline stage (cold-email generation). Companion to `company/ICP.md`
> (which drives Fit) — this file is the source of truth for *how* we sound, not *who* we target.

## Tone
Warm, consultative — relationship-first, not a hard sales pitch. Data-driven: lead with a
real, specific fact about the prospect (a win, a launch, a shipping gap), not a generic value
prop. Bold and charismatic, but never pushy — one real question or concrete offer per email,
not a stacked pitch.

## Format (locked, enforced by `draft`/QA)
- 2-email sequence: initial + one follow-up.
- 2 versions of each (4 drafts per prospect total).
- Subject line: under 40 characters.
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

**Initial, v1** — *"Case built for the Teal 2?"*
> {FIRST_NAME} — saw Teal's SRR win. We build MIL-STD cases sized to the Teal 2, made in the
> US like you. Worth 10 min this week?

**Initial, v2** — *"US-made case, Teal-sized"*
> {FIRST_NAME}, congrats on SRR. Curious what Teal 2 units ship in today — we build
> MIL-STD-810H cases sized to it. Quick call?

**Follow-up, v1** — *"Following up — Teal 2 case"*
> {FIRST_NAME}, still curious what you're using for Teal 2 transport. Happy to send our
> AV-Field specs if useful, no pressure.

**Follow-up, v2** — *"One more try — worth 10 min?"*
> {FIRST_NAME}, know outbound gets ignored — one real question: does Teal's shipping case
> survive field drops as well as the drone does?

Each closes with the signature above.

## Email structure (per email)
1. **Opening line** — a real, specific fact about the prospect (a win, launch, or shipping gap), not a generic greeting.
2. **Value prop** — a use case + social proof (a comparable, well-known customer) + the pain it removes. Example framing: "We saw companies similar to you have {xyz}."
3. **Close** — one closed-ended (yes/no) call to action. Never stack asks. Prefer a low-pressure ask, e.g. a negative-CTA: "Do you think it'd be a bad idea to sit and chat for 15 min?" or a single real question: "Do you run into {problem}, and how do you handle it today?"

## Persona tailoring (pitch by seniority)
The `draft` prompt injects the top contact's **persona tier** (from `gtm/persona.py`). Lean the value prop toward the matching rule:

- **c-suite** — pitch the **business outcome**: ROI, cost, what the case program wins or saves them. Skip process detail. They care about the number, not the workflow.
- **manager** — pitch **process and team**: smoother logistics, less firefighting, a team that isn't fighting broken gear. Do NOT lead with money saved — it's not their metric.
- **ic** — pitch the **day-to-day**: easier handling, less hassle in the field, people happier doing the work.
- **unknown** — no contact tier available; write to the company's segment/angle generically, no seniority lean.
