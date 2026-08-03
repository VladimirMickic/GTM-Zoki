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

**Size is the only hard constraint** (locked 2026-07-28). Geography is not: we ship
worldwide and a non-US manufacturer with a well-fitting airframe is as good a prospect
as a US one. Everything that used to auto-reject other than size is now a *score
penalty*, not a rejection — see "Disqualifiers" below.

---

## Who we sell to (target customer = drone MANUFACTURERS)
We sell OEM / co-branded / accessory cases to companies that **make** drones whose
customers deploy them in the field and need protected transport.

### Ideal prospect
- Makes **field-deployed** drones: defense, public safety, industrial inspection,
  survey/mapping, energy/utilities, SAR, firefighting.
- Airframe **fits our case envelope** (see table) — small-to-mid sUAS is the sweet spot.
- Ships at **meaningful volume / price point** ($1k+ per unit) so custom cases are justified.
- Sells into a **procurement-serious** buyer: defense, gov, regulated utility, enterprise.
  Any country. Certification (NDAA/Blue UAS in the US, national MoD/NATO/EU defense
  frameworks elsewhere) is evidence of that, not a requirement in itself.
- Currently ships in a generic/soft case, or **builds its own enclosure**, that we can
  upgrade, replace, or take over.

### Strong-fit segments
Defense & tactical sUAS · Public safety / first responder · Industrial & infrastructure
inspection · Survey / mapping / GIS · Energy & utilities · Search & rescue.

### Disqualifiers (auto-reject in Fit stage)
**Size only** — both bounds. Nothing else auto-rejects.
- **Upper bound:** airframe's folded/packed footprint too large for AV-Convoy
  (40 × 24 × 16 in) — heavy-lift ag sprayers, large fixed-wing. Custom-quote only.
- **Lower bound:** consumer **toy / hobby / nano** drones (heaviest airframe <250g) —
  no custom rugged case is warranted at that size or price point.

**Not disqualifiers any more** (2026-07-28) — these are score penalties, judged inside
the rubric below, because each of them is sometimes wrong:
- *Non-US company.* Geography is irrelevant to whether a case fits and sells.
- *Indoor-only / racing.* Racing teams travel constantly; some do need transport.
- *Software-only, reseller, distributor.* They have no airframe of their own, so they land
  in the 0-7 "no airframe identified" band of **Airframe physically fits a case line** and
  pick up the no-airframe cap (`gtm/fit.py::evidence_cap`, 48) — which puts priority tier
  out of reach and lets the total fall below the keep line on its own. Score it there, on
  the airframe evidence, not by inferring a budget; Budget & procurement is Python's and
  has no reseller signal. But a "distributor" that also manufactures under its own brand
  names an airframe, so it scores that airframe on the ordinary bands and should not be
  thrown away by a keyword.

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

Scored in two phases. Claude scores 80 points from **scrape data only**; Python adds
the remaining 20 after the enrich stage, from fields that do not exist at Fit time.

| Signal | Weight | Phase | Source |
|---|---|---|---|
| Airframe physically fits a case line | 35 | Fit (Claude) | Scrape — dimensions/weights |
| Field-deployed / rugged use case | 25 | Fit (Claude) | Scrape — description, models, case_evidence |
| Displacement opportunity | 20 | Fit (Claude) | Scrape — case_evidence |
| Budget & procurement | 20 | Post-enrich (Python) | headcount, key_news, compliance_evidence |

**Every criterion's bottom band is "no evidence".** Missing evidence scores the bottom
band, never the midpoint — the rule Displacement has carried since 2026-07-28, now
applied to all four. A score the fields cannot support is worse than a low score: it
reads as a finding, and on a company Claude has never heard of it silently becomes 0.

### Airframe physically fits a case line /35

| Band | Evidence |
|---|---|
| 30-35 | Published folded L×W×H fits a named case line — cite the line and the source |
| 20-29 | Inferred from weight/class alone, no published dimensions — write "inferred" |
| 8-19 | Airframe named but neither dimensions nor weight found |
| 0-7 | No airframe identified at all (`drone_models` and `drone_dimensions` both empty) |

Dimensions found by the web hunt (spec pages, reviews, Reddit) count as published —
cite the source. The 20-29 cap on weight-only inference is the old 26/30 rule rescaled.

### Field-deployed / rugged use case /25

Score **what the airframe survives, not who buys it.** A category word — "military",
"defense", "industrial" — is not evidence of field deployment. An agricultural sprayer
trucked to a field daily, eating dust and chemical wash, scores above a defense company
that names no airframe and no mission. All six strong-fit segments score on the same
table: defense/tactical, public safety, industrial inspection, survey/mapping, energy
and utilities, and search & rescue carry no inherent advantage over each other.

| Band | Evidence |
|---|---|
| 21-25 | Named harsh-environment duty cycle — daily field transport, vehicle-borne or backpack-carried, launched away from a hangar, weather/dust/chemical exposure |
| 15-20 | Field or outdoor use clearly stated, but no duty-cycle or environment detail |
| 8-14 | Mixed indoor/outdoor, or commercial/cinema use with no ruggedness claim |
| 0-7 | Indoor-only, racing, benchtop, or no use case found after the web hunt |

### Displacement opportunity /20

Displacement-opportunity scoring must cite case_evidence:

| Band | Evidence |
|---|---|
| 17–20 | **In-house enclosure** — they tool and warehouse their own housing (drone-in-a-box, dock, base station, self-molded hard case). Highest value: a recurring OEM line, not a one-off swap, and no incumbent vendor defending the account |
| 14–17 | Named rugged-case competitor (Pelican, Nanuk, SKB, Hardigg, Seahorse, Explorer) — a concrete displacement target with researchable weaknesses |
| 10–13 | Soft bag / generic case / no case at all — a real upgrade opportunity, but no named incumbent to research |
| 0–4 | case_evidence still unknown after the web hunt — write "unknown"; never award midpoint points for missing evidence |

An in-house enclosure outranks a named competitor because the sale replaces a
manufacturing cost centre (tooling, molds, spares, a revision every time the airframe
changes) rather than another vendor's SKU. It is the harder pitch and the larger one —
see `company/voice-guide.md` for how to make it.

### Budget & procurement /20 (post-enrich, deterministic)

Last on purpose: the three criteria above are Claude's, this one is Python's. The fit
prompt tells Claude to skip this section, so nothing Claude must score may be nested
under it.

Replaced "Volume / price point" (15) and "Procurement & compliance fit" (15) on
2026-07-31. Both measured the same thing — can this buyer fund tooled custom foam —
and both were sourced from enrichment data that the Fit stage never sees, because
enrich runs after Fit and only on passers. On run us-drone-20 that produced a line
reading "no unit-price/volume evidence was captured this run" attached to a score of
10/15, filled in from what the model already knew about a famous company.

Scored by `gtm/budget.py::score_budget`, no LLM call, no prose judgment:

| Points | Component | Evidence |
|---|---|---|
| 8 | Procurement evidence | `us_made_ndaa` true, OR non-empty `compliance_evidence`, OR an award-shaped `key_news` line (contract, task order, NDAA, Blue UAS, framework, NATO stock number) |
| 7 / 4 / 1 / 0 | Scale | headcount >=50 / 11-49 / 1-10 / unknown |
| 5 | Capital event | a `key_news` line naming a funding round, Series, or raise |

Geography is not a component. A national MoD framework, a NATO stock number and a US
Blue UAS listing all satisfy "procurement evidence" identically.

- **Tier 1 (70–100)** → `status="priority"` — push to sheet, full personalized outreach (drafted).
- **Tier 2 (40–69)** → `status="keep"` — push to sheet, lower priority, still gets a personalized draft.
- **Tier 3 (<40, or any disqualifier)** → `status="drop"` — logged, excluded from the sheet, **never drafted**. Fit is the last stage a Tier 3 company reaches: enrich/segment/draft all gate on `status in ("priority", "keep")`, so no email is ever personalized for it.

---

## Outreach angles (for later cold-email stage)
- **New model launch** → "your new airframe needs a transport case built around it."
- **Procurement/compliance win** → "MIL-STD case to match the standard your buyer already
  holds you to." (US: "US-made, NDAA-aligned". Elsewhere: name their own framework —
  never assume a US program.)
- **Field/harsh-environment marketing** → "IP67 protection from truck to mission."
- **Generic case today** → co-branded custom-foam upgrade, better unboxing + protection.
- **Competitor detected** → named-competitor weakness, cited — displace with proof.

## Buying signals to watch (enrichment stage)
New drone launch · defense/gov contract award (any country) · procurement certification
(NDAA/Blue UAS, NATO stock number, national MoD framework, aviation-authority type cert)
· funding round · hiring in field ops/logistics/manufacturing · expansion into new
verticals or new export markets.

---

## Worked example — Teal Drones (first prospect)
US-made tactical sUAS (Black Widow, Hellcat, Teal 2, Fang FPV), Salt Lake City,
NDAA / Blue UAS, US Army SRR program. Small backpack-portable airframes → fit **AV-Field**.
Defense/public-safety buyers, US-made → **strong fit**. Expected score: high (~85+).
