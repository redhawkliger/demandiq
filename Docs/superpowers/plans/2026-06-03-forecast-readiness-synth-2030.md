# Real-Forecast Readiness (synthetic differential-growth 2030) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `synth_horizon` dev tool that derives an explicitly-synthetic, per-functional-class-grown 2030 SANDAG network from the real base, and prove real differential growth flows through `refine → Pass 1 → Pass 2 → VMT` — making a real 2030 forecast a one-file swap away.

**Architecture:** One new pure-ish module `backend/forecasting/synth_horizon.py` (geo deps lazy, schema reused from `adapters/sandag.py`) plus one new test file. No app/runtime changes. The generator scales each link's flow columns by its functional-class factor, leaving link_ids/geometry intact so the base↔horizon ID-stability check passes.

**Tech Stack:** Python 3.12, geopandas/pyogrio (lazy), pytest. Run under the combined venv: `backend/.venv-forecasting`.

---

## Spec
`Docs/superpowers/specs/2026-06-03-forecast-readiness-synthetic-2030-design.md` (committed on branch `forecast-readiness-synth-2030`).

## File Structure
- **Create** `backend/forecasting/synth_horizon.py` — `FACTORS`, `FLOW_COLUMNS`, `synthesize_horizon_gdf`, `synthesize_horizon_shp`, CLI. Sole responsibility: turn a SANDAG base network into a synthetic horizon by per-class flow scaling.
- **Create** `backend/tests/forecasting/test_synth_horizon.py` — the three tests, beside the existing forecasting tests; reuses `conftest.py` fixtures (`synthetic_sandag_gdf`, `project_points_near`).
- **Reuse (import only)** `backend/forecasting/adapters/sandag.py` — `SANDAG_FC_MAP`, `FLOW_COLS`.
- **No changes** to `app.py`, the `/forecast` API, F1–F4, or any engine module.

All commands run from the repo root `/Users/Ak47/Desktop/demandiq`. Test runner: `backend/.venv-forecasting/bin/python -m pytest`.

---

### Task 1: `synth_horizon` module (generator) — TDD via the generator unit test

**Files:**
- Create: `backend/forecasting/synth_horizon.py`
- Test: `backend/tests/forecasting/test_synth_horizon.py`

- [ ] **Step 1: Write the failing generator unit test**

Create `backend/tests/forecasting/test_synth_horizon.py`:

```python
"""Tests for the synthetic horizon-network generator (readiness tool).

Run: backend/.venv-forecasting/bin/python -m pytest backend/tests/forecasting/test_synth_horizon.py -v
"""
import pytest

from forecasting.synth_horizon import (
    FACTORS, FLOW_COLUMNS, synthesize_horizon_gdf, synthesize_horizon_shp,
)
from forecasting.contract import Period

_ALL12 = ["NBL", "NBT", "NBR", "SBL", "SBT", "SBR",
          "EBL", "EBT", "EBR", "WBL", "WBT", "WBR"]


def test_generator_scales_per_class_and_guards_force(synthetic_sandag_gdf, tmp_path):
    base = synthetic_sandag_gdf
    out = synthesize_horizon_gdf(base)

    # hwycov_id → expected canonical-class factor (per FACTORS + SANDAG_FC_MAP).
    expect = {58: 1.35, 59: 1.35,   # Freeway
              101: 1.20,            # Major Arterial
              102: 1.10,            # Local Collector → Collector
              900: 1.00,            # Zone Connector → Connector
              103: 1.05,            # Local road
              500: 1.10}            # Collector (far link, still scaled)
    for hid, factor in expect.items():
        b = base[base["hwycov_id"] == hid].iloc[0]
        o = out[out["hwycov_id"] == hid].iloc[0]
        for c in FLOW_COLUMNS:
            assert o[c] == pytest.approx(b[c] * factor), f"id {hid} col {c}"

    # Invariants: ids/geometry untouched; the input frame is NOT mutated.
    assert list(out["hwycov_id"]) == list(base["hwycov_id"])
    assert out.geometry.geom_equals(base.geometry).all()
    assert base[base["hwycov_id"] == 58].iloc[0]["ab_am_flow"] == pytest.approx(2451.47)

    # Shapefile writer + --force guard.
    import geopandas as gpd
    base_shp = tmp_path / "hwyLoad.shp"
    base.to_file(base_shp)
    dst = tmp_path / "hwyLoad_2030_synthetic.shp"
    synthesize_horizon_shp(str(base_shp), str(dst))
    assert dst.exists()
    written = gpd.read_file(dst)
    fw = written[written["hwycov_id"] == 58].iloc[0]["ab_am_flow"]
    assert fw == pytest.approx(2451.47 * 1.35, abs=0.5)
    # Refuses to overwrite without force; succeeds with it.
    with pytest.raises(FileExistsError):
        synthesize_horizon_shp(str(base_shp), str(dst))
    synthesize_horizon_shp(str(base_shp), str(dst), force=True)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `backend/.venv-forecasting/bin/python -m pytest backend/tests/forecasting/test_synth_horizon.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'forecasting.synth_horizon'`.

- [ ] **Step 3: Write the module**

Create `backend/forecasting/synth_horizon.py`:

```python
"""
DemandIQ Forecasting — synthetic horizon-network generator (readiness tool).

Derives an EXPLICITLY SYNTHETIC horizon-year SANDAG network from a real base
loaded-highway shapefile by scaling each link's volumes by a per-functional-class
growth factor. Lets the NCHRP-765 pipeline be validated on real, DIFFERENTIAL
(non-identity) growth while no real 2030 network is available, and makes the real
2030 network a one-file swap (drop it in, point F1 at it).

NOT a SANDAG projection. FACTORS are illustrative readiness values chosen to
exercise differential refinement — replace with a real horizon network when one
arrives. Schema (SANDAG_FC_MAP, FLOW_COLS) is reused from adapters.sandag; this
tool is SANDAG-schema-coupled by design. Geo deps are imported lazily inside
synthesize_horizon_shp only; synthesize_horizon_gdf is pure (operates on a frame).
"""

from forecasting.adapters.sandag import SANDAG_FC_MAP, FLOW_COLS

# Per canonical functional class (see SANDAG_FC_MAP values). EXPLICITLY SYNTHETIC.
FACTORS = {
    "Freeway":        1.35,
    "Ramp":           1.35,
    "Prime Arterial": 1.20,
    "Major Arterial": 1.20,
    "Collector":      1.10,
    "Local":          1.05,
    "Connector":      1.00,
    "Other":          1.10,
}

# Columns scaled: the 10 directional period flows + total_flow.
FLOW_COLUMNS = [col for pair in FLOW_COLS.values() for col in pair] + ["total_flow"]


def _factor_for(fc_desc, factors):
    """Map a raw SANDAG fc_desc → canonical class → growth factor."""
    return factors.get(SANDAG_FC_MAP.get(fc_desc, "Other"), factors["Other"])


def synthesize_horizon_gdf(gdf, factors=FACTORS):
    """Return a COPY of a SANDAG GeoDataFrame with each link's FLOW_COLUMNS scaled
    by its functional-class factor. link_id, nodes, geometry, len_mile, lanes, and
    fc_desc are untouched — base↔horizon link_ids stay identical (so ingest's
    overlap/ID-stability check passes at ~100%)."""
    out = gdf.copy()
    fac = out["fc_desc"].map(lambda d: _factor_for(d, factors))
    for c in (c for c in FLOW_COLUMNS if c in out.columns):
        out[c] = out[c] * fac
    return out


def synthesize_horizon_shp(src, dst, *, factors=FACTORS, force=False):
    """Read a SANDAG shapefile at `src`, scale flows per class, write to `dst`.
    Lazy-imports geopandas (the only geo touch). Refuses to overwrite an existing
    `dst` unless force=True (protects what may be a real network already there)."""
    import os
    import geopandas as gpd

    if os.path.exists(dst) and not force:
        raise FileExistsError(
            f"{dst} already exists — pass force=True/--force to overwrite "
            "(refusing to clobber what may be a real network).")
    gdf = gpd.read_file(src)
    required = FLOW_COLUMNS + ["fc_desc"]
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        raise ValueError(f"{src} missing required SANDAG columns {missing} — "
                         "not a SANDAG loaded-highway network?")
    out = synthesize_horizon_gdf(gdf, factors=factors)
    out.to_file(dst)
    return dst


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    data = Path(__file__).resolve().parents[2] / "data" / "sandag"
    ap = argparse.ArgumentParser(
        description="Generate an EXPLICITLY-SYNTHETIC horizon SANDAG network "
                    "(per-functional-class growth). Not a SANDAG projection.")
    ap.add_argument("--src", default=str(data / "hwyLoad.shp"))
    ap.add_argument("--dst", default=str(data / "hwyLoad_2030_synthetic.shp"))
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing destination file")
    args = ap.parse_args()
    out = synthesize_horizon_shp(args.src, args.dst, force=args.force)
    print(f"wrote synthetic horizon network: {out}")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `backend/.venv-forecasting/bin/python -m pytest backend/tests/forecasting/test_synth_horizon.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/forecasting/synth_horizon.py backend/tests/forecasting/test_synth_horizon.py
git commit -m "feat(forecasting): synthetic per-class horizon generator (synth_horizon)"
```

---

### Task 2: Differential-growth pipeline test (non-identity + per-class divergence + GROWTH-OUTLIER)

**Files:**
- Modify: `backend/tests/forecasting/test_synth_horizon.py` (append one test)

This test has no new implementation — it characterizes the generator + existing engine integration, so it should PASS once written. It proves: (a) differential growth survives ingest (deterministic, layer-level), (b) refinement's per-leg growth tracks the class factors with real (>1.0) growth, (c) Pass 1 → Pass 2 produce grown futures, (d) `corridor_vmt` runs in the path, and (e) an extreme factor trips `REFINE-GROWTH-OUTLIER`.

- [ ] **Step 1: Append the pipeline test**

Append to `backend/tests/forecasting/test_synth_horizon.py`:

```python
def test_differential_growth_through_pipeline(synthetic_sandag_gdf, project_points_near, tmp_path):
    from forecasting.ingest import ingest_networks
    from forecasting.matcher import match_network_to_legs
    from forecasting.refinement import refine_corridor
    from forecasting.pass1 import forecast_corridor
    from forecasting.pass2 import balance_future
    from forecasting.vmt import corridor_vmt

    # Base shp + a differential-growth horizon shp produced BY the generator.
    base_shp = tmp_path / "hwyLoad.shp"
    synthetic_sandag_gdf.to_file(base_shp)
    horizon_shp = tmp_path / "hwyLoad_2030_synthetic.shp"
    synthesize_horizon_shp(str(base_shp), str(horizon_shp))

    pts = project_points_near
    n = pts[0]["num"]
    layers = ingest_networks(pts, [
        {"role": "base",    "scenario_year": 2025, "path": str(base_shp)},
        {"role": "horizon", "scenario_year": 2030, "path": str(horizon_shp)},
    ])

    factor_vals = {round(v, 2) for v in FACTORS.values()}

    # (a) Differential growth survived ingest — DETERMINISTIC (no matcher):
    #     each filtered link's horizon/base AM-flow ratio equals its class factor,
    #     and >= 2 distinct factors appear across the near cluster.
    base_by = {l.link_id: l for l in layers["base"].links}
    ratios = set()
    for hl in layers["horizon"].links:
        b_am = base_by[hl.link_id].flow.ab.get(Period.AM, 0.0)
        if b_am > 0:
            ratios.add(round(hl.flow.ab[Period.AM] / b_am, 2))
    assert ratios <= factor_vals, f"ratios {ratios} not all class factors"
    assert len(ratios) >= 2, f"expected per-class divergence; got {ratios}"

    # (b) Refinement: every bound leg's growth factor is a class factor, and at
    #     least one leg shows real (>1.0) growth — non-identity.
    mr = match_network_to_legs(pts, layers["base"])
    counts = {n: {m: 100 for m in _ALL12}}
    rr = refine_corridor(mr, layers["base"], layers["horizon"], counts, Period.AM)
    [r] = rr
    bound = [d for d in ("NB", "SB", "EB", "WB") if r["approaches"][d]["status"] == "bound"]
    assert bound, "expected at least one bound leg on the synthetic node"
    grew = False
    for d in bound:
        gf = r["approaches"][d]["inbound"].get("growth_factor")
        if gf is None:
            continue
        assert round(gf, 2) in factor_vals, f"leg {d} growth {gf} not a class factor"
        if gf > 1.0:
            grew = True
    assert grew, "expected at least one leg with real (>1.0) model growth"

    # (c) Pass 1 → Pass 2 produce grown futures (> the flat base count of 100).
    futures, _ = forecast_corridor(rr, counts)
    res = balance_future(futures, [], coords={n: {"lat": pts[0]["lat"], "lng": pts[0]["lng"]}})
    assert max(res["balanced"][n].values()) > 100

    # (d) VMT is wired into the path and runs cleanly (single node → empty
    #     corridor; corridor VMT growth itself is covered in test_vmt.py).
    vmt = corridor_vmt([], {n: {"lat": pts[0]["lat"], "lng": pts[0]["lng"]}}, mr,
                       layers["base"], layers["horizon"], counts, res["balanced"], rr, Period.AM)
    assert vmt["unit"] == "veh-mi"

    # (e) An extreme class factor (> 4x) trips REFINE-GROWTH-OUTLIER.
    extreme_shp = tmp_path / "hwyLoad_2030_extreme.shp"
    synthesize_horizon_shp(str(base_shp), str(extreme_shp), factors=dict(FACTORS, Freeway=5.0))
    layers_x = ingest_networks(pts, [
        {"role": "base",    "scenario_year": 2025, "path": str(base_shp)},
        {"role": "horizon", "scenario_year": 2030, "path": str(extreme_shp)},
    ])
    rr_x = refine_corridor(match_network_to_legs(pts, layers_x["base"]),
                           layers_x["base"], layers_x["horizon"], counts, Period.AM)
    codes = [f["code"]
             for rx in rr_x
             for d in ("NB", "SB", "EB", "WB")
             if rx["approaches"][d].get("inbound")
             for f in (rx["approaches"][d]["inbound"].get("flags") or [])]
    assert "REFINE-GROWTH-OUTLIER" in codes, f"expected outlier flag; got {codes}"
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `backend/.venv-forecasting/bin/python -m pytest backend/tests/forecasting/test_synth_horizon.py -q`
Expected: PASS (2 passed). If `corridor_vmt`'s argument order trips, confirm against `backend/forecasting/vmt.py:108` — signature is `corridor_vmt(corridor_links, coords, match_results, base_layer, horizon_layer, existing_balanced, future_balanced, refinement, period, *, expansion_factor=None, scenario_factor=None)`.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/forecasting/test_synth_horizon.py
git commit -m "test(forecasting): differential-growth pipeline + GROWTH-OUTLIER via synth horizon"
```

---

### Task 3: CI-skipped real-file smoke

**Files:**
- Modify: `backend/tests/forecasting/test_synth_horizon.py` (append imports + one gated test)

- [ ] **Step 1: Append the gated real-file smoke**

Append to `backend/tests/forecasting/test_synth_horizon.py`:

```python
from pathlib import Path  # noqa: E402

REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_file_smoke(tmp_path):
    """Generate a synthetic 2030 from the REAL base, ingest base + horizon, and
    confirm non-identity growth + a passing overlap/ID-stability check end-to-end.
    Skipped on CI exactly like the other real-file gated tests."""
    from forecasting.ingest import ingest_networks
    from forecasting.matcher import match_network_to_legs
    from forecasting.refinement import refine_corridor
    from forecasting.pass1 import forecast_corridor

    horizon = tmp_path / "hwyLoad_2030_synthetic.shp"
    synthesize_horizon_shp(str(REAL_SHP), str(horizon))

    lat, lng = 32.624067, -116.959736                      # DISCOVERY FALLS node
    pts = [{"num": 1, "lat": lat, "lng": lng}]
    # ingest_networks runs base↔horizon overlap check internally; identical
    # link_ids → ~100% overlap → no raise (proves the generator preserved ids).
    layers = ingest_networks(pts, [
        {"role": "base",    "scenario_year": 2025, "path": str(REAL_SHP)},
        {"role": "horizon", "scenario_year": 2030, "path": str(horizon)},
    ])
    mr = match_network_to_legs(pts, layers["base"])
    counts = {1: {m: 100 for m in _ALL12}}
    rr = refine_corridor(mr, layers["base"], layers["horizon"], counts, Period.AM)
    futures, _ = forecast_corridor(rr, counts)
    # Non-identity: at least one future movement exceeds the flat base count.
    assert max(futures[1].values()) > 100
```

- [ ] **Step 2: Run the suite**

Run: `backend/.venv-forecasting/bin/python -m pytest backend/tests/forecasting/test_synth_horizon.py -q -rs`
Expected: locally (real `hwyLoad.shp` present) `3 passed`; on CI the smoke shows `2 passed, 1 skipped` (skip reason: real shp not present).

- [ ] **Step 3: Full-suite regression check**

Run: `cd backend && .venv-forecasting/bin/python -m pytest -q`
Expected: `160 passed` locally (was 157). Then `cd ..`.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/forecasting/test_synth_horizon.py
git commit -m "test(forecasting): CI-skipped real-file smoke for synth horizon"
```

---

### Task 4: Generate the artifact + verify in the real app (manual, no commit)

The synthetic file is gitignored (`data/sandag/`), so this produces a local artifact only — it is not committed.

- [ ] **Step 1: Generate the synthetic 2030**

Run: `cd backend && .venv-forecasting/bin/python -m forecasting.synth_horizon`
Expected: `wrote synthetic horizon network: …/data/sandag/hwyLoad_2030_synthetic.shp` and the file + sidecars exist.

- [ ] **Step 2: Verify end-to-end in the app**

Start the app under the combined venv (`cd backend && .venv-forecasting/bin/python app.py`). In F1 tag base = `hwyLoad.shp` and horizon = `hwyLoad_2030_synthetic.shp`; F2 pull/match; F3 run; confirm F4 / the VMT panel show **non-identity** future volumes (future > existing), not identity growth.
Expected: real differential growth visible. (Observation step — nothing to commit.)

---

## Self-Review

**Spec coverage:**
- Generator module + FACTORS + lazy geo + `_synthetic` name + `--force` guard → Task 1 (module) ✓.
- Reuse `SANDAG_FC_MAP` + `FLOW_COLS` (no redefining) → module imports them ✓.
- Per-class differential growth, non-identity → Task 2 (a)+(b) ✓.
- GROWTH-OUTLIER on extreme factor → Task 2 (e) ✓.
- refine→Pass1→Pass2 real growth → Task 2 (b)+(c) ✓; VMT wired → Task 2 (d) ✓ (VMT *growth* math already covered by `test_vmt.py` — noted, deliberate).
- CI-skipped real-file smoke + overlap check → Task 3 ✓.
- One-file swap → Task 4 + spec's swap section ✓.
- Test count 157 → 160 → Task 3 Step 3 ✓.
- No UI / no endpoints / no spatial gradient → no such tasks ✓.

**Placeholder scan:** none — every step has full code/commands and expected output.

**Type consistency:** `synthesize_horizon_gdf` / `synthesize_horizon_shp` / `FACTORS` / `FLOW_COLUMNS` names match across module and tests. `corridor_vmt` call uses the verified 9-positional signature. `refine_corridor(mr, base, horizon, counts, Period.AM)` matches `refinement.py:135`. Flag key is `"code": "REFINE-GROWTH-OUTLIER"` (matches `refinement.py:95`).

**Deliberate scope note (flag for reviewer):** per-class *divergence* is asserted deterministically at the post-ingest layer level (Task 2a) rather than via fragile matcher per-leg prediction; the generator unit test (Task 1) proves per-class scaling at the source. VMT is exercised for wiring only here; VMT growth math is already covered in `test_vmt.py`.
