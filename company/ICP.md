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
- *Software-only, reseller, distributor.* Score Procurement & compliance fit low (they
  can't buy OEM cases) and let the total fall below 40 on its own — but a "distributor"
  that also manufactures under its own brand should not be thrown away by a keyword.

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
| Procurement & compliance fit | 15 | Scrape + enrichment |
| Displacement opportunity — named competitor case, or blank slate | 15 | Scrape + enrichment |

**Procurement & compliance fit /15** replaced "US-made / NDAA" on 2026-07-28. The old
signal handed 15 points to every US company and 0 to every non-US one, which is a
geography bias, not a business signal — and since NDAA compliance is near-universal
among US makers in this ICP, it also failed to discriminate *within* the US set. What
we actually care about is whether this buyer's procurement is serious enough to pay for
a custom case. Score on evidence, in any country:

| Band | Evidence |
|---|---|
| 12–15 | Named defense/gov program or certification — NDAA / Blue UAS (US), NATO stock number, national MoD or ministry framework, EU/allied defense program, awarded gov contract |
| 8–11 | Regulated commercial procurement — BVLOS or national equivalent waiver, utility/energy framework agreement, aviation-authority type certification, public-safety agency sales |
| 4–7 | Commercial sales, no certification or program evidence found |
| 0–3 | Unknown after the web hunt, **or** the company cannot buy OEM cases at all (software-only, pure reseller/distributor) |

`us_made_ndaa: true` maps to the 12–15 band, but it is one route into that band, not the
band's definition — a Norwegian maker on a NATO framework or a German maker selling to
the Bundespolizei scores the same. Never award points for being US-based per se, and
never deduct for being foreign. If a run's brief explicitly asks for US/NDAA companies,
that is an input *filter* applied before scoring, not a change to this rubric.

Physical-fit scoring must cite published folded dimensions when available; when inferring
from weight/class alone, cap at 26/30 and say "inferred" in fit_reason. Dimensions found by
the web hunt (specs pages, reviews, Reddit) count as published — cite the source.

Displacement-opportunity scoring must cite case_evidence:

| Band | Evidence |
|---|---|
| 13–15 | **In-house enclosure** — they tool and warehouse their own housing (drone-in-a-box, dock, base station, self-molded hard case). Highest value: a recurring OEM line, not a one-off swap, and no incumbent vendor defending the account |
| 11–14 | Named rugged-case competitor (Pelican, Nanuk, SKB, Hardigg, Seahorse, Explorer) — a concrete displacement target with researchable weaknesses |
| 8–10 | Soft bag / generic case / no case at all — a real upgrade opportunity, but no named incumbent to research |
| 3 | case_evidence still unknown after the web hunt — write "unknown"; never award midpoint points for missing evidence |

An in-house enclosure outranks a named competitor because the sale replaces a
manufacturing cost centre (tooling, molds, spares, a revision every time the airframe
changes) rather than another vendor's SKU. It is the harder pitch and the larger one —
see `company/voice-guide.md` for how to make it.

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
