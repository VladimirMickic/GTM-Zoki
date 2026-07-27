---
name: cold-email
description: Draft a 2-email cold sequence (initial + follow-up, 2 versions each) for one prospect, following company/voice-guide.md exactly. Use for a manual one-off draft outside a pipeline run (`gtm/run.py` stage 6 does this automatically via gtm/draft.py), or to redo a draft after feedback.
allowed-tools: Read, Write, Grep
---

# cold-email

Manual companion to the pipeline's automated draft stage (`gtm/draft.py::build_draft_prompt`).
Same voice, same format, same output shape — run by hand for one prospect.

## Phase 1: Load Context
1. Read `company/voice-guide.md` in full — tone, banned phrases, signature, email
   structure, and persona-tailoring rules all live there. Don't summarize or paraphrase
   these from memory; read the file each time.
2. Get the prospect's facts. If a pipeline run exists for this prospect, pull them
   straight from its `data/runs/<run>/prospects.json` record — don't re-derive:
   - `outreach_angle` — the hook. Use it as-is, don't invent a different one.
   - `segment`, `buying_signals`, `key_news`, `fit_reason` — supporting specifics.
   - `contact_title` (first entry if `;`-joined) — classify with the persona rule below.
   If no run exists, ask the user for these five facts one at a time before drafting —
   never fabricate a buying signal or news item.
3. Classify the top contact's persona tier from their title (same rule as
   `gtm/persona.py::classify_persona`): title contains founder/owner/ceo/cto/coo/cfo/chief/
   president/vp/"vice president" → **c-suite**; contains director/"head of"/manager/
   operations/program/logistics/lead → **manager**; any other non-empty title → **ic**;
   empty/unknown title → **unknown**.

## Phase 2: Draft
Write 2 emails (initial + follow-up), 2 versions each — 4 drafts total. Each draft follows
the voice guide's 3-part structure:
1. **Opening line** — a real, specific fact about the prospect (the `outreach_angle` or a
   `key_news` item), never a generic greeting.
2. **Value prop** — one use case + one comparable social-proof customer + the pain it
   removes. Lean the pitch toward the contact's persona tier:
   - **c-suite** → business outcome (ROI, cost, program win). Skip process detail.
   - **manager** → process/team outcome (smoother logistics, less firefighting). Never
     lead with money saved.
   - **ic** → day-to-day outcome (easier handling, less field hassle).
   - **unknown** → the segment's angle generically, no seniority lean.
3. **Close** — one closed-ended (yes/no) ask. Never stack asks. Prefer a low-pressure or
   negative-CTA close (e.g. "Would it be a bad idea to grab 15 min?") over a hard ask.

Format rules (self-enforce, non-negotiable):
- Subject line under 40 characters.
- Body capped at ~150 characters — one or two sentences, no more.
- Personalization variables as `{FIRST_NAME}`, `{COMPANY}` (literal braces, not filled in).
- No links in the body.
- Every draft closes with the signature block from the voice guide:
  ```
  Alex Rivera
  Sales, AeroVault Cases
  ```
- No banned phrases from the voice guide's list (generic openers, corporate filler,
  hedge-padding) — grep the voice guide's "Banned phrases" section if unsure.

## Phase 3: Quality Gates
- [ ] Subject < 40 chars, both emails, both versions
- [ ] Body ~150 chars, one/two sentences, both emails, both versions
- [ ] No banned phrase from the voice guide present in any draft
- [ ] `{FIRST_NAME}`/`{COMPANY}` present and unfilled
- [ ] No links in any body
- [ ] Angle used is the prospect's actual `outreach_angle` — not invented
- [ ] Value prop matches the contact's persona tier (or generic if unknown)
- [ ] Close is a single closed-ended ask, not stacked
- [ ] Signature block present on all 4 drafts

## Self-improvement
If, while running this skill, you get corrected on an assumption, a format rule, a persona
lean, or any other instruction here — edit this file to bake the correction in before you
finish. A correction that isn't written back just recurs next time, including in sessions
with no memory of this one (this skill is mirrored for both Claude Code and Codex via
`.agents/skills`, neither of which shares the other's session memory).
