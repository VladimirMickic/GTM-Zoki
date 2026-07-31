# Outreach config — who signs the emails, and who we may name as a reference

Read by `gtm/render.py::load_outreach_config()` at output time. Every `{{token}}` in a
draft is filled from a prospect's own data except two — `{{sender_name}}` and
`{{reference_customer}}` — which have no source anywhere in the pipeline. They live here.

Format is load-bearing: `- key: value` lines under the `## Sender` heading, one bullet per
name under `## Approved reference customers`. A value containing `TODO` counts as unset —
any draft still needing it is blocked from the sheet with a `qa_flag`, never shipped with
the raw token showing (which is exactly what run `test-batch-1` pushed).

## Sender
- name: Vladimir Mickic
- title: Founder, AeroVault Cases
- email: TODO — optional, the reply-to address (nothing reads it yet; only `name`
  fills a draft token)

## Approved reference customers
Real AeroVault references only, and only ones cleared to be named in writing. Never a
company from a pipeline run: naming one prospect to another is the failure
`gtm/draft.py::check_reference_customer` exists to catch. `gtm/render.py` additionally
drops any name matching the recipient or a run-mate before picking one.

- Northfield Autonomy
- Vantage Point Robotics
- Ironline Defense Systems

## Fallback reference
Used when no approved name survives the filter. Category-level only, never a logo — this
is the voice guide's documented fallback ("Social proof — `{{reference_customer}}` only").

**Must read as a SINGULAR noun phrase.** Drafts are written around this token holding one
company name ("{{reference_customer}} runs our AV-Ops line"), so a plural fills it into
broken English. The old plural value shipped "defense sUAS makers we work with orders their
AV-Micro builds from us this way" to the live sheet in run us-drone-19 (2026-07-29).

- fallback: a defense sUAS maker we work with
