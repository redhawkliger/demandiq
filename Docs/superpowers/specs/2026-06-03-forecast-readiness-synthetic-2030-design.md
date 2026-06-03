# Spec — Real‑Forecast Readiness: synthetic differential‑growth 2030

**Status:** Approved design, pre‑implementation (this spec is the contract; no code yet).
**Date:** 2026‑06‑03
**Milestone:** prove the NCHRP‑765 forecast pipeline on *real, differential* growth and be a one‑file swap away from a real client forecast — without waiting on the (not‑yet‑available) real 2030 SANDAG network.

## Problem / context
Forecasting v1 shipped to `main` (engine + API + F1–F4 + Corridor/Scenario VMT + multi‑county Phases 1–2). But **no real base→2030 forecast has ever run**: only one model year (`hwyLoad.shp`) is on disk, so every result to date is synthetic or identity‑growth (base == horizon). The real 2030 SANDAG network isn't available yet.

This milestone closes the readiness gap: derive a **realistic, documented, non‑identity** synthetic 2030 from the real base via **per‑functional‑class** growth, validate that real growth flows through `refine → Pass 1 → Pass 2 → VMT`, and make swapping in the real 2030 a single step.

## Locked decisions (do not drift)
- **FACTORS are explicitly synthetic, per‑functional‑class.** They are illustrative readiness factors, **not** a SANDAG projection — stated as such in the module docstring.
- **Reuse `SANDAG_FC_MAP` and `FLOW_COLS` from `backend/forecasting/adapters/sandag.py`** — do not redefine either (single schema source; consistent with the Phase‑2 canonical work).
- **Output file is `data/sandag/hwyLoad_2030_synthetic.shp`** — keep the `_synthetic` suffix; **never** a bare `2030` name. Overwriting an existing `dst` requires an explicit `--force`.
- **Geo deps (`geopandas`/`shapely`/`pyogrio`) stay lazily imported inside `synth_horizon.py` only.** The gdf transform and everything downstream stay pure Python.
- **Three tests:** generator unit test; differential‑growth pipeline test (non‑identity, per‑class divergence, `GROWTH-OUTLIER` fires on an extreme factor); CI‑skipped real‑file smoke.
- **No UI, no new endpoints, no spatial gradient.** Dev/readiness tool only.

## Architecture & components
One new module: **`backend/forecasting/synth_horizon.py`**.

- `FACTORS` — per‑canonical‑class multiplier table (full table below).
- `synthesize_horizon_gdf(gdf, factors=FACTORS)` → gdf — **pure transform** on a SANDAG GeoDataFrame (no geo imports needed at call time; operates on an already‑loaded frame). For each link: map `fc_desc → canonical class` via `SANDAG_FC_MAP` (imported), look up the factor (default `Other`), and multiply **every column in `FLOW_COLS` (the 10 directional `{ab,ba}_{ea,am,md,pm,ev}_flow` columns)** plus `total_flow` by it. Leaves `hwycov_id` (link_id), `from_node`/`to_node`, geometry, `len_mile`, lanes, and `fc_desc` **unchanged** — so base↔horizon `link_id`s stay identical and the ingest overlap/ID‑stability check passes at ~100%.
- `synthesize_horizon_shp(src, dst, *, factors=FACTORS, force=False)` — **lazy‑imports geopandas** (mirrors the adapter's geo boundary), reads `src`, calls `synthesize_horizon_gdf`, writes `dst`. Refuses to overwrite an existing `dst` unless `force=True`.
- `python -m forecasting.synth_horizon [--src …] [--dst …] [--force]` CLI — defaults `src=data/sandag/hwyLoad.shp`, `dst=data/sandag/hwyLoad_2030_synthetic.shp`.

Why scaling all period flows + `total_flow` by the same per‑link factor is consistent: SANDAG's `total_flow == Σ` of the period flows, so a uniform per‑link multiply preserves that identity and keeps the VMT daily/period ratio coherent. `len_mile` is intentionally untouched (growth is demand, not geometry).

## FACTORS table (full — per canonical class from `SANDAG_FC_MAP`)
| Canonical class | Factor | Source `fc_desc` values (via `SANDAG_FC_MAP`) |
|---|---|---|
| Freeway | **1.35** | Freeway |
| Ramp | **1.35** | Freeway Connector Ramp, Local Ramp |
| Prime Arterial | **1.20** | Prime Arterial |
| Major Arterial | **1.20** | Major Arterial |
| Collector | **1.10** | Collector, Local Collector, Rural Collector |
| Local | **1.05** | Local (non‑circulation element) Road |
| Connector | **1.00** | Zone Connector (no artificial growth on zone connectors) |
| Other | **1.10** | anything unmapped (adapter default) |

These values are **illustrative**, engineer‑replaceable, and explicitly synthetic.

## Data flow / plug‑in (zero app changes)
1. **Dev step (once):** `python -m forecasting.synth_horizon` → writes `data/sandag/hwyLoad_2030_synthetic.shp` (+ `.dbf/.shx/.prj/.cpg`). The whole `data/sandag/` tree is gitignored, so this artifact is **local‑only** by construction.
2. **Existing app path, unchanged:** F1 tags base = `hwyLoad.shp` (engineer‑tagged base year) and horizon = `hwyLoad_2030_synthetic.shp` (tagged 2030) → F2 `ingest‑match` pulls both → F3 `/forecast/run` produces **real differential growth** through `refine → Pass 1 → Pass 2 → VMT` → F4 / VMT show non‑identity growth. The base↔horizon overlap check passes (identical link_ids).

## The one‑file swap (when the real 2030 network arrives)
1. Drop the real horizon network's files into `data/sandag/` (e.g. `hwyLoad_2030.shp` + sidecars).
2. In **F1**, set the horizon network's **path** field to the real filename (`hwyLoad_2030.shp`) and tag its real model year.
3. **Re‑pull** in F2 (ingest‑match), then **re‑run** F3.
4. No code change. The synthetic file was never committed (gitignored), so there is nothing to revert; delete or keep it as you like.

The swap is purely "point F1 at a different filename," because the synthetic was produced at the same shapefile level the real file will arrive at.

## Testing
New file **`backend/tests/forecasting/test_synth_horizon.py`**, sitting beside the existing forecasting tests (`test_api`, `test_ingest`, `test_matcher`, `test_pass1`, `test_pass2`, `test_refinement`, `test_sandag_adapter`, `test_vmt`, with shared fixtures in `conftest.py`). Reuses the `conftest` `synthetic_sandag_gdf` fixture, which already spans Freeway / Major Arterial / Collector / Zone Connector / Local — so per‑class divergence is observable in CI with no real file.

1. **Generator unit test (CI‑safe):** apply `synthesize_horizon_gdf` to the synthetic base; assert each link's `FLOW_COLS` + `total_flow` scaled by its class factor (Freeway ×1.35, Major Arterial ×1.20, Collector ×1.10, Local ×1.05, Connector ×1.00), `total_flow` stays `== Σ` period flows post‑scale, and `hwycov_id`/geometry/`len_mile` are unchanged.
2. **Differential‑growth pipeline test (CI‑safe):** ingest base + synthetic horizon (per‑class), then `refine_corridor → forecast_corridor → balance_future → corridor_vmt`; assert growth is **non‑identity** (future ≠ base), **per‑class divergent** (a Freeway‑fed leg's refined growth > a Collector‑fed leg's, all > 1.0), Pass 1 converges to grown targets, Pass 2 conserves + rounds to 5, and VMT future > existing. Plus: feeding one class an **extreme factor (> 4×)** trips the `GROWTH-OUTLIER` flag — proving that guard path is live.
3. **Real‑file smoke (CI‑skipped, gated on `data/sandag/hwyLoad.shp`):** synthesize a 2030 from the real base into a tmp dir, `ingest‑match` base + horizon, `/forecast/run`; assert non‑identity growth and that the overlap/ID‑stability check passes. Skipped on CI exactly like the existing real‑file tests (`test_real_vmt_smoke`, `test_ingest_match_real_file`, `test_real_single_network_ingest`).

**Test count:** currently **157** collected (`93` in `tests/forecasting`). After this milestone: **160** (`96` in `tests/forecasting`). On CI the real‑file smoke is skipped (like the other gated real‑file tests), so CI sees +2 passing / +1 skipped; locally with the real `hwyLoad.shp` present, all 3 run.

## Error handling & schema reuse
- Import `SANDAG_FC_MAP` and `FLOW_COLS` from `adapters/sandag.py`; never redefine column names or the class map.
- `synthesize_horizon_shp` fails loud if `src` is missing, if required columns (`fc_desc`, the `FLOW_COLS`, `total_flow`) are absent, or if geo deps are unavailable (clear message — it's a combined‑venv dev tool).
- Refuses to overwrite an existing `dst` unless `--force` / `force=True` — protects a real file that might already sit at the destination.

## Scope / non‑goals (YAGNI)
- No UI changes (F1–F4 already accept two networks; the dry‑run identity path already exists — now there's a real differential horizon to point it at).
- No new endpoints; the served runtime is untouched.
- The generator is a **dev/readiness tool**, not part of the production app.
- Growth is **per‑class only** — no spatial gradient.
- The output is **explicitly synthetic** and must never be presented as a SANDAG projection.

## Success criteria
- `synth_horizon.py` exists with the locked behavior; `import app` and the lean runtime are unaffected (geo deps lazy).
- Running the CLI on the real `hwyLoad.shp` produces a valid `hwyLoad_2030_synthetic.shp` that ingest‑matches and runs through `/forecast/run` end‑to‑end with **non‑identity, per‑class‑differential** growth.
- All three tests pass (160 total locally; +2/+1‑skip on CI).
- The one‑file swap procedure above is the only step needed when the real 2030 network arrives.
