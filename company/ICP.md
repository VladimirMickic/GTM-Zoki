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

---

## Fit scoring (used by the pipeline)
Score each scraped prospect 0–100. Auto-reject on any disqualifier regardless of score.

| Signal | Weight | Source |
|---|---|---|
| Airframe physically fits a case line | 30 | Scrape (drone dimensions) |
| Field-deployed / rugged use case | 25 | Scrape + enrichment |
| Volume / price point signals real budget | 15 | Enrichment |
| US-made / NDAA / defense/gov buyers | 15 | Scrape + enrichment |
| Ships in weak/generic case today (upgrade gap) | 15 | Scrape |

Physical-fit scoring must cite published folded dimensions when available; when inferring
from weight/class alone, cap at 26/30 and say "inferred" in fit_reason.

- **70–100** = push to sheet, priority outreach
- **40–69** = keep, lower priority
- **<40 or any disqualifier** = drop

---

## Outreach angles (for later cold-email stage)
- **New model launch** → "your new airframe needs a transport case built around it."
- **Defense/NDAA win** → "US-made, MIL-STD case to match your US-made drone."
- **Field/harsh-environment marketing** → "IP67 protection from truck to mission."
- **Generic case today** → co-branded custom-foam upgrade, better unboxing + protection.

## Buying signals to watch (enrichment stage)
New drone launch · defense/gov contract award · NDAA/Blue UAS certification · funding
round · hiring in field ops/logistics/manufacturing · expansion into new verticals.

---

## Worked example — Teal Drones (first prospect)
US-made tactical sUAS (Black Widow, Hellcat, Teal 2, Fang FPV), Salt Lake City,
NDAA / Blue UAS, US Army SRR program. Small backpack-portable airframes → fit **AV-Field**.
Defense/public-safety buyers, US-made → **strong fit**. Expected score: high (~85+).
