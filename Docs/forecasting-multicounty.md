# Forecasting — Multi-County (Region-Generalization) Spec

**Status:** Phases 1–2 built; Phases 3–5 **deliberately deferred** (see triggers below).
**Milestone framing:** a *refactor-and-document* milestone, **not** a feature add.

This document exists so that future-me can find **why** Phases 3–5 were deferred
without re-deriving it, and knows the exact **trigger** that promotes them into
active work. If you are reading this because a second MPO model just arrived,
jump to [Trigger](#trigger).

---

## Scope (locked decisions)

Three decisions, made when the milestone was approved, fix the shape of this work:

1. **One region per project.** A project targets exactly one MPO model. No single
   corridor spans two models. Therefore the forecast **engine** —
   `matcher`, `refinement`, `pass1`, `pass2` — is already region-blind and **does
   not change**. (The harder "cross-county corridor" — a corridor stitching two
   models in one forecast — was explicitly **not** chosen.)
2. **SANDAG-shaped models.** Future models are directional link shapefiles with
   period flows. They differ only in **column names, CRS, functional-class
   taxonomy, and asset location**. The `Period` enum, the ratio-as-default refinement
   logic, and the canonical contract all **stay as-is**.
3. **Speculative / no second consumer yet.** The goal is to keep SANDAG-only from
   calcifying — **not** to ship SCAG/MTC. This is the load-bearing constraint:
   with no real second model to validate against, inventing an abstraction the
   eventual real model doesn't fit is the primary risk. So we **name and refactor
   the seam**, and **stop before building a speculative second adapter.**

### Guiding principle

Every phase is judged by: *does it pay off even if a second region never arrives?*
Pure architecture/quality wins ship now (Phases 1–2). Anything that requires
guessing an unseen schema's shape is **documented and deferred** until a concrete
model exists — building it speculatively is the wrong-abstraction trap that
decision #3 warns against.

---

## Coupling map (where region-specificity lives today)

Captured from a full read of `backend/forecasting/` so the phasing is grounded,
not guessed.

**Already region-agnostic — no change needed:**
- `contract.py` `NetworkLayer`/`NetworkLink` — designed for "SANDAG, and any future region".
- `matcher.py`, `refinement.py` math, `pass1.py`, `pass2.py` — pure Python on the
  canonical contract. The entire forecast engine is region-blind.

**The clean seam (where region binds):**
- `ingest.py` — region dispatch + asset registry + the adapter import.
- `adapters/sandag.py` — the whole file: field map (`COL_*`, `FLOW_COLS`,
  `SANDAG_FC_MAP`), source CRS, shapefile reader, AB/BA digitization assumption.

**Leaks outside the seam (the real Phase-2 work):**
1. **`Period` enum** is SANDAG's EA/AM/MD/PM/EV scheme. *Out of scope* under
   "SANDAG-shaped" (same period scheme); see Phase 4.
2. **`vmt.py` read SANDAG column-name strings out of `source_attributes`** —
   `ab_am_flow`/…, `total_flow`, `len_mile` — when the canonical `link.flow`
   already carried the per-period volumes. A SANDAG-shaped model with different
   column names would silently yield no daily ratio and no model length. **This
   is the sharpest leak and a latent defect independent of multi-county. Closed
   in Phase 2.**
3. **`refinement.py`'s ratio-default** rests on the SANDAG fact "`*_flow` are
   *period* volumes, no peak-hour field." *Out of scope* under "SANDAG-shaped";
   see Phase 4.
4. **`api.py`** ingest-match resolves paths under `SANDAG_DATA_DIR` only.
   See Phase 5.

**UI copy / config (cosmetic until a 2nd region exists):** `F1` `DEFAULT_SANDAG_PATH`
+ "SANDAG model networks", `F2` "Pull SANDAG network", `F3` period-volume rationale,
`F4` "· SANDAG ·" chip, `projectStore` forecasting slice. See Phase 5.

---

## Phases

### Phase 1 — Name the seam — **BUILT**
Replace `ingest.py`'s hardcoded `if region != "SANDAG": raise NotImplementedError`
with an explicit **adapter registry** `{ "SANDAG": ingest_sandag }`, dispatched by
lookup. Define the `RegionAdapter` contract (the signature `ingest_sandag` already
satisfies). See [How to add a region](#how-to-add-a-region).

*Pays off regardless:* removes a hardcode, documents the boundary, ~zero risk.

### Phase 2 — Close the canonical-field leaks — **BUILT**
Make the engine consume the **canonical contract**, not SANDAG schema strings.
This was treated as a **latent-defect fix**, not just multi-county prep.
- `NetworkLink` gains typed `length_mi` and `daily_total` fields (optional); the
  **adapter populates them** (length from `len_mile` if > 0, else geodesic from
  the link geometry — identical to the old `vmt.py` logic; daily from `total_flow`).
- `vmt.py` now reads `link.flow` (per-period volumes), `link.length_mi`, and
  `link.daily_total` from the contract. `PERIOD_FLOW_COLS` and all
  `source_attributes` schema-name reads are **deleted** from `vmt.py`. The shared
  geodesic helper lives in `forecasting/geo.py`.
- `refinement.py` confirmed to have **no** raw-schema reads (only a documentary
  comment about the SANDAG period-volume fact).

*Pays off regardless:* removes a real "engine secretly depends on SANDAG strings"
smell and a duplicated flow-column table — an architecture win on its own. A
SANDAG-shaped model with different column names now produces correct VMT
automatically, because the adapter already mapped its columns into `DirectionalFlow`.

**Hard constraint honored:** Phase 2 is behavior-preserving. Same numbers out,
cleaner path in — verified by the full suite (156) **and** the real-file
ingest-match + real VMT export render producing identical output to before.

---

### Phase 3 — Declarative region schema — **DEFERRED**
*Goal when triggered:* extract the adapter's `COL_*` / `FLOW_COLS` / `SANDAG_FC_MAP`
into a declarative `RegionSchema`; the shapefile body becomes a generic
`ingest_link_shapefile(schema, …)`; SANDAG becomes one `RegionSchema` instance.
Then a SANDAG-shaped MPO = a new schema literal, **no new reader code**.

**Folded into this phase (deferred, NOT dropped) — from the original multi-county vision:**
- **The suggest-confirm schema-mapping agent** — an assistant that inspects an
  unknown shapefile's columns and *proposes* a `RegionSchema` mapping for the
  engineer to confirm/correct. It belongs here because the `RegionSchema` shape it
  targets only becomes real in Phase 3.
- **The web-dictionary lookup** — resolving an MPO's published data-dictionary to
  seed/validate the column mapping. Same dependency: it feeds the schema-mapping
  agent.

*Why deferred:* this is exactly where the wrong-abstraction risk lives. The correct
shape of `RegionSchema` (and therefore what the mapping agent targets) is only
knowable once a **second** real schema exists to generalize against. Building it
now means designing for an imagined model. Phases 1–2 already make this a clean,
localized future change.

### Phase 4 — Period scheme & flow-basis — **DEFERRED (documented boundary)**
Not needed under "SANDAG-shaped" (same period scheme, period volumes). Recorded
boundary: a future model using a different period set, or **peak-hour** rather than
**period** volumes, would generalize the `Period` enum and flip `refinement.py`'s
ratio-default. Promote only if such a model appears.

### Phase 5 — UI / API region-awareness — **DEFERRED**
Parameterize the SANDAG-specific copy, asset directory, and path default (F1/F2/F3/F4,
`api.py` `SANDAG_DATA_DIR`, `projectStore`). Cosmetic/config until a second region
actually exists.

---

## Trigger

**A concrete second MPO model arriving** promotes **Phase 3** (bind `RegionSchema`
to it, build the suggest-confirm mapping agent + web-dictionary lookup against it)
and **Phase 5** (region-aware UI/API) into active work — **validated against the
real schema, not an imagined one.** Phase 4 promotes only if that model differs in
period scheme or flow basis (peak-hour vs period volumes).

Until then, the seam is named (Phase 1) and the engine is clean (Phase 2); adding
a region is a localized change, not surgery.

---

## How to add a region

The `RegionAdapter` contract is the callable signature `ingest_sandag` satisfies:

```
ingest_<region>(source, scenario_year, project_intersections_4326, *, filter_radius_ft=300)
    -> NetworkLayer
```

It must:
1. Read the region's raw network for the given `scenario_year`.
2. Spatially filter to within `filter_radius_ft` of the project intersections
   (filter-first keeps the returned layer KB-scale).
3. Reproject geometry to the project CRS (EPSG:4326) — the adapter owns the transform.
4. Emit a canonical `NetworkLayer` of `NetworkLink`s, populating **all** canonical
   fields the engine consumes — including `flow` (per-period AB/BA volumes via the
   `inbound_to`/`outbound_from` convention), `length_mi`, and `daily_total`. Raw
   source rows may also be stashed in `source_attributes` for provenance, but the
   engine must never depend on them.

Then **register it** in `ingest.py`'s adapter registry under the region key. No
other engine code should need to change for a SANDAG-shaped model.
