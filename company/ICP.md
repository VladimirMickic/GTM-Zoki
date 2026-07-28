# AeroVault Cases — Ideal Customer Profile (ICP)

> Fictional company for this demo, modeled on **SKB Cases**. Rename freely.
> This file is the source of truth for the pipeline's **Fit** stage.

## Who we are
AeroVault Cases is a US-based manufacturer of rugged, waterproof protective cases.
Made in USA, injection-molded and rotomolded, **IP67 / MIL-STD-810H**. Our niche vs.
generic case makers: **custom CNC-cut foam transport cases built around specific drone
airframes** (aircraft + controller + spare batteries + payload, all seated in one case).

Positioning: *"Deploy anywhere. Come back intact."*

### Our case lines (internal usable dimensions — these define what fits)
| Line | Build | Internal L×W×D (in) | Best for |
|---|---|---|---|
| AV-Micro | Injection-molded | 13 × 9 × 6 | Compact folded quads + controller |
| AV-Field | Injection-molded | 20 × 14 × 8 | **Flagship** — tactical / enterprise sUAS |
| AV-Ops | Injection-molded | 30 × 20 × 12 | Larger quadcopters, mapping/cinema rigs |
| AV-Convoy | Rotomolded, wheeled | 40 × 24 × 16 | Multi-drone kits, ground-station loadouts |

**Hard physical limit:** a single airframe's *folded/packed* footprint must fit inside
40 × 24 × 16 in. Anything larger (heavy-lift agricultural sprayers, fixed-wing with
long spans) is **custom-quote only → treat as disqualified** for automated outreach.

---

## Who we sell to (target customer = drone MANUFACTURERS)
We sell OEM / co-branded / accessory cases to companies that **make** drones whose
customers deploy them in the field and need protected transport.

### Ideal prospect
- Makes **field-deployed** drones: defense, public safety, industrial inspection,
  survey/mapping, energy/utilities, SAR, firefighting.
- Airframe **fits our case envelope** (see table) — small-to-mid sUAS is the sweet spot.
- Ships at **meaningful volume / price point** ($1k+ per unit) so custom cases are justified.
- Bonus: **US-made / NDAA / Blue UAS** — same gov & defense buyers value US-made cases (us).
- Currently ships in a generic/soft case we can **upgrade or replace**.

### Strong-fit segments
Defense & tactical sUAS · Public safety / first responder · Industrial & infrastructure
inspection · Survey / mapping / GIS · Energy & utilities · Search & rescue.

### Disqualifiers (auto-reject in Fit stage)
- Consumer **toy / hobby / nano** drones (<250g, sub-$500).
- **Indoor-only** or racing-only drones with no field-transport need.
- Airframe **too large** for AV-Convoy (heavy-lift ag sprayers, big fixed-wing).
- **Software-only** / no hardware, or defunct company.
- Pure reseller/distributor (doesn't manufacture).

### Target titles for outreach
Who we search for and rank (`gtm/contacts.py::_RANK_KEYWORDS`) — ops/product/founders buy
transport cases, not generic sales/biz-dev, so they rank highest:

| Rank | Titles | Why |
|---|---|---|
| 1 | Founder, any Chief (CTO/COO/CFO) | final budget authority |
| 2 | VP / Vice President | division owner, signs off |
| 3 | Head of..., Director | owns the field-gear/logistics program day to day |
| 4 | Operations, Product, Program, Logistics (manager-level) | hands-on buyer, feels the pain directly |
| 5 | Sales | fallback only — rarely the actual buyer |

**Not targeted:** CEO — never surfaced as a contact, even as a fallback when no other title
is found (`gtm/contacts.py::_CEO_TITLES`). **Unless they founded the company:** a founder who
is also CEO stays, because Founder is rank 1 above and at a founder-led company the two are
the same person. Decided 2026-07-27 after the cold-0727 run — Arcsky's SERP returned both
co-founders, titled "Co-CEO | Co-Founder", and the blanket exclusion dropped both, leaving a
drafted email with no recipient. The carve-out is scoped to this collision only: a "Founding
Engineer" is still excluded, as an engineer.

Draft tone is then tailored to whichever tier the top-ranked contact falls into
(`gtm/persona.py::classify_persona` — finance / c-suite / director / manager / ic; doctrine
per tier lives in `company/voice-guide.md`'s "Persona tailoring" section).

---

## Fit scoring (used by the pipeline)
Score each scraped prospect 0–100. Auto-reject on any disqualifier regardless of score.

| Signal | Weight | Source |
|---|---|---|
| Airframe physically fits a case line | 30 | Scrape (drone dimensions) |
| Field-deployed / rugged use case | 25 | Scrape + enrichment |
| Volume / price point signals real budget | 15 | Enrichment |
| US-made / NDAA / defense/gov buyers | 15 | Scrape + enrichment |
| Displacement opportunity — named competitor case, or blank slate | 15 | Scrape + enrichment |

Physical-fit scoring must cite published folded dimensions when available; when inferring
from weight/class alone, cap at 26/30 and say "inferred" in fit_reason. Dimensions found by
the web hunt (specs pages, reviews, Reddit) count as published — cite the source.

Displacement-opportunity scoring must cite case_evidence: a named rugged-case competitor
(Pelican, Nanuk, SKB, Hardigg, Seahorse, Explorer, etc.) is a concrete displacement target —
score 12-15/15 and say so; a soft bag/generic case/no case at all is still an upgrade
opportunity but with no named incumbent to research — score 8-11/15. If case_evidence is
still unknown after the web hunt, score exactly 3/15 and write "unknown" — never award
midpoint points for missing evidence.

- **Tier 1 (70–100)** → `status="priority"` — push to sheet, full personalized outreach (drafted).
- **Tier 2 (40–69)** → `status="keep"` — push to sheet, lower priority, still gets a personalized draft.
- **Tier 3 (<40, or any disqualifier)** → `status="drop"` — logged, excluded from the sheet, **never drafted**. Fit is the last stage a Tier 3 company reaches: enrich/segment/draft all gate on `status in ("priority", "keep")`, so no email is ever personalized for it.

---

## Outreach angles (for later cold-email stage)
- **New model launch** → "your new airframe needs a transport case built around it."
- **Defense/NDAA win** → "US-made, MIL-STD case to match your US-made drone."
- **Field/harsh-environment marketing** → "IP67 protection from truck to mission."
- **Generic case today** → co-branded custom-foam upgrade, better unboxing + protection.
- **Competitor detected** → named-competitor weakness, cited — displace with proof.

## Buying signals to watch (enrichment stage)
New drone launch · defense/gov contract award · NDAA/Blue UAS certification · funding
round · hiring in field ops/logistics/manufacturing · expansion into new verticals.

---

## Worked example — Teal Drones (first prospect)
US-made tactical sUAS (Black Widow, Hellcat, Teal 2, Fang FPV), Salt Lake City,
NDAA / Blue UAS, US Army SRR program. Small backpack-portable airframes → fit **AV-Field**.
Defense/public-safety buyers, US-made → **strong fit**. Expected score: high (~85+).
