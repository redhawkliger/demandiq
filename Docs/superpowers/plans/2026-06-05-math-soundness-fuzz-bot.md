# Math-Soundness Fuzz Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Hypothesis property-based fuzz bot that generates valid random corridors and asserts the DemandIQ forecasting/balancing math obeys its invariants, wired into CI as a blocking gate plus a nightly deep run.

**Architecture:** A hybrid generator. One end-to-end corridor generator drives the real pure-numeric spine (`matcher → refine_corridor → forecast_corridor → balance_future → corridor_vmt`); focused unit properties hit `furness_intersection` and `balance_future` directly. All targets are pure Python — verified to pull **zero** geo modules (geopandas/shapely) — so the whole suite runs in lean CI with no shapefiles. Generators reuse the exact input idioms already proven in `tests/forecasting/test_pass1.py`, `test_refinement.py`, and `test_vmt.py`.

**Tech Stack:** Python 3.12, pytest, Hypothesis, the existing `forecasting` package + `balancer.py`.

---

## Context the engineer needs

**Verified facts (do not re-litigate):**
- The numeric pipeline imports and runs with **no geo modules loaded**. Confirmed by driving `match_network_to_legs → refine_corridor → forecast_corridor → balance_future` and checking `sys.modules`.
- Pydantic is available in lean CI (pulled transitively by `fastapi==0.115.5` in `backend/requirements.txt`); `numpy==2.4.4` is pinned. Neither `pytest` nor `hypothesis` is present yet.
- The existing forecasting pytest suite (`tests/forecasting/test_pass1.py`, etc.) is **not run in CI today** — `backend/run_tests.sh` hardcodes a list of plain-script runners and never invokes pytest. Geo-dependent tests in that suite are gated by `@pytest.mark.skipif(not REAL_SHP.exists())` and import geopandas *inside* functions, so they skip cleanly when no shapefile is present.

**Key signatures (verified against source):**
- `furness_intersection(matrix, row_targets, col_targets, present, tol=0.5, max_iter=500)` → `(M, converged: bool, iters_used: int, final_residual: float)`. `matrix` is a 4×4 list-of-lists; `row_targets`/`col_targets` are length-4 lists (entries may be `None`); `present` is a length-4 bool list. (`backend/balancer.py:460`)
- `balance_future(futures, links, coords=None, ...)` → dict with keys `balanced` (`{int_num: {movement: float}}`), `link_conservation` (list of `{fromNum, toNum, direction, upstream_outflow, downstream_inflow, delta, mode}`), `method`. (`backend/forecasting/pass2.py`)
- `match_network_to_legs(intersections, layer)` → match_results; `refine_corridor(mr, base, horizon, counts, Period.AM, **kw)` → `[per-intersection dict]`; `forecast_corridor(rr, counts, manual_targets=None)` → `(futures, meta)`.
- `corridor_vmt(corridor, coords, matches, base, horizon, existing, future, refinement, Period.AM, scenario_factor=None, expansion_factor=None)` → dict with `corridor`, `links`, `network`, `scenario`. (`backend/forecasting/vmt.py:108`)
- `compute_link_conservation` iterates the **explicit** `resolved_links` graph, not array order (`backend/balancer.py:644`) — this is the corridor-order anchor invariant #6 guards.

**Working directory:** all paths below are relative to repo root `/Users/Ak47/Desktop/demandiq`. Run pytest from `backend/`.

**Branch:** work continues on `feat/math-soundness-fuzz-bot` (already created; the spec doc is committed there).

---

## File Structure

- Create: `backend/tests/forecasting/fuzz/__init__.py` — package marker (empty).
- Create: `backend/tests/forecasting/fuzz/conftest.py` — Hypothesis profiles (`ci`, `nightly`).
- Create: `backend/tests/forecasting/fuzz/generators.py` — Hypothesis `@composite` strategies + shared builders. One responsibility: produce valid pipeline inputs.
- Create: `backend/tests/forecasting/fuzz/test_generators.py` — self-tests proving generators emit valid contract objects (the TDD red/green driver).
- Create: `backend/tests/forecasting/fuzz/test_fuzz_balancer.py` — focused properties on `furness_intersection` + `balance_future`.
- Create: `backend/tests/forecasting/fuzz/test_fuzz_pipeline.py` — spine + VMT properties.
- Modify: `backend/requirements.txt` — add `pytest`, `hypothesis`.
- Modify: `.github/workflows/ci.yml` — add a pytest step to the `backend` job running the forecasting suite (gate).
- Create: `.github/workflows/fuzz-nightly.yml` — scheduled deep run, fails loudly, no auto-issues.
- Modify: `backend/.gitignore` (or create) — ignore Hypothesis's `.hypothesis/` example cache but keep committed counterexamples (see Task 8).

---

## Task 1: Add dependencies and scaffold the fuzz package

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/forecasting/fuzz/__init__.py`
- Create: `backend/tests/forecasting/fuzz/conftest.py`

- [ ] **Step 1: Add the two pure-Python deps**

Append to `backend/requirements.txt`:

```
pytest==8.3.4
hypothesis==6.122.3
```

- [ ] **Step 2: Install into the venv used for local runs**

Run (from `backend/`): `.venv-forecasting/bin/python -m pip install pytest==8.3.4 hypothesis==6.122.3`
Expected: both install without disturbing geopandas (pure-Python wheels).

- [ ] **Step 3: Create the empty package marker**

Create `backend/tests/forecasting/fuzz/__init__.py` with no content.

- [ ] **Step 4: Create conftest with the two Hypothesis profiles**

Create `backend/tests/forecasting/fuzz/conftest.py`:

```python
"""Hypothesis profiles for the math-soundness fuzz bot.

`ci`      — deterministic, bounded; the PR gate. Zero flakes.
`nightly` — deep, randomized; the scheduled bot.

Select with `pytest -p no:randomly --hypothesis-profile=ci` or via
HYPOTHESIS_PROFILE; the session hook below honors the env var, default `ci`.
"""
import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    max_examples=150,
    deadline=2000,                 # ms per example; pure math is fast
    derandomize=True,              # fixed example stream -> reproducible gate
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=5000,
    deadline=None,                 # deep exploration, no per-example clock
    derandomize=False,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
```

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/tests/forecasting/fuzz/__init__.py backend/tests/forecasting/fuzz/conftest.py
git commit -m "test(forecasting): scaffold fuzz package + Hypothesis ci/nightly profiles"
```

---

## Task 2: Generators — shared builders and contract-valid strategies

**Files:**
- Create: `backend/tests/forecasting/fuzz/generators.py`
- Test: `backend/tests/forecasting/fuzz/test_generators.py`

- [ ] **Step 1: Write the failing generator self-test**

Create `backend/tests/forecasting/fuzz/test_generators.py`:

```python
"""Self-tests: every generator must emit STRUCTURALLY VALID inputs, so a
property failure later means a real math bug, not a malformed-input artifact."""
from hypothesis import given

from forecasting.contract import NetworkLayer
from tests.forecasting.fuzz import generators as g


@given(g.ew_corridor())
def test_ew_corridor_is_valid(corridor):
    nums, coords, links, volumes = corridor
    assert len(nums) == len(set(nums)) >= 2          # distinct intersection numbers
    assert set(volumes) == set(nums)                 # one volume dict per intersection
    # corridor order is the GIVEN order, deliberately not sorted by number
    assert [l["fromNum"] for l in links] == nums[:-1]
    assert [l["toNum"] for l in links] == nums[1:]
    for v in volumes.values():
        assert all(x >= 0 for x in v.values())       # non-negative seeds only


@given(g.single_intersection_spine())
def test_spine_layers_are_valid(case):
    base, horizon, intersections, counts, growth = case
    assert isinstance(base, NetworkLayer)            # pydantic validation passed (unique link_id)
    assert isinstance(horizon, NetworkLayer)
    assert set(counts[1]) >= set(g.ALL12)
    assert growth > 0


@given(g.consistent_ipf())
def test_ipf_inputs_have_matching_totals(case):
    M, row_t, col_t, present = case
    assert all(present)
    assert abs(sum(row_t) - sum(col_t)) < 1e-6       # consistent margins => IPF must converge
    assert all(M[r][c] > 0 for r in range(4) for c in range(4))
```

- [ ] **Step 2: Run it to verify it fails**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/test_generators.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.forecasting.fuzz.generators'` (or import error on missing `ew_corridor`).

- [ ] **Step 3: Implement the generators**

Create `backend/tests/forecasting/fuzz/generators.py`:

```python
"""Hypothesis strategies that emit VALID forecasting-pipeline inputs.

Reuses the exact construction idioms proven in tests/forecasting/test_pass1.py
and test_vmt.py. Everything here is pure Python (no geo), so generated cases run
in lean CI.
"""
import math

from hypothesis import strategies as st

from forecasting.contract import DirectionalFlow, NetworkLayer, NetworkLink, Period

ALL12 = ["NBL", "NBT", "NBR", "SBL", "SBT", "SBR",
         "EBL", "EBT", "EBR", "WBL", "WBT", "WBR"]

# Non-negative, finite vehicle counts. Bounded to keep IPF iteration cheap.
_count = st.integers(min_value=0, max_value=2000)
_flow = st.floats(min_value=0.0, max_value=5000.0,
                  allow_nan=False, allow_infinity=False)
_pos = st.floats(min_value=1.0, max_value=1000.0,
                 allow_nan=False, allow_infinity=False)


# ── 1. East-west corridor for the balancer (balance_future) ───────────────────
@st.composite
def ew_corridor(draw):
    """k intersections with DISTINCT, deliberately unsorted numbers, laid out
    west->east (increasing lng). Links connect consecutive intersections in the
    GIVEN order. Returns (nums, coords, links, volumes)."""
    k = draw(st.integers(min_value=2, max_value=6))
    nums = draw(st.lists(st.integers(min_value=1, max_value=99),
                         min_size=k, max_size=k, unique=True))
    coords = {n: {"lat": 32.72, "lng": -117.20 + 0.01 * i}
              for i, n in enumerate(nums)}
    links = [{"fromNum": nums[i], "toNum": nums[i + 1],
              "direction": "EB/WB", "mode": "Full"} for i in range(k - 1)]
    volumes = {n: {m: float(draw(_count)) for m in ALL12} for n in nums}
    return nums, coords, links, volumes


# ── 2. Single 4-leg intersection for the refine -> pass1 spine ─────────────────
_CENTER_LNG, _CENTER_LAT = -117.160, 32.720
_C_XY = (_CENTER_LNG, _CENTER_LAT)


def _dest(brng, dist_ft=500.0):
    r = 3958.8 * 5280.0
    d = dist_ft / r
    th = math.radians(brng)
    phi1, lam1 = math.radians(_CENTER_LAT), math.radians(_CENTER_LNG)
    phi2 = math.asin(math.sin(phi1) * math.cos(d)
                     + math.cos(phi1) * math.sin(d) * math.cos(th))
    lam2 = lam1 + math.atan2(math.sin(th) * math.sin(d) * math.cos(phi1),
                             math.cos(d) - math.sin(phi1) * math.sin(phi2))
    return (math.degrees(lam2), math.degrees(phi2))


# leg key -> (from_node, to_node, from_xy, to_xy). Mirrors test_pass1._SPEC.
_SPEC = {
    "N": (100, 1, _C_XY, _dest(0)),
    "S": (2, 100, _dest(180), _C_XY),
    "E": (100, 3, _C_XY, _dest(90)),
    "W": (4, 100, _dest(270), _C_XY),
}


def _link(lid, fn, tn, fxy, txy, ab, ba):
    return NetworkLink(link_id=str(lid), from_node=fn, to_node=tn,
                       geometry=[fxy, txy], from_node_xy=fxy, to_node_xy=txy,
                       functional_class="Major Arterial",
                       flow=DirectionalFlow(ab={Period.AM: ab}, ba={Period.AM: ba}))


def _layer(flows):
    links = [_link(k, *_SPEC[k], ab, ba) for k, (ab, ba) in flows.items()]
    return NetworkLayer(region="SANDAG", source_crs_epsg=2230, crs_epsg=4326,
                        scenario_year=2025, links=links)


@st.composite
def single_intersection_spine(draw, identity=False):
    """A 4-leg intersection (num=1) with random base flows + counts and a horizon
    derived by a single growth factor. identity=True forces horizon==base (growth
    1.0) for the identity-conservation property. Returns
    (base_layer, horizon_layer, intersections, counts, growth)."""
    base_flows = {leg: (float(draw(_count)) + 1.0, float(draw(_count)) + 1.0)
                  for leg in _SPEC}                    # +1 keeps model base > 0
    growth = 1.0 if identity else draw(
        st.floats(min_value=0.5, max_value=3.0,
                  allow_nan=False, allow_infinity=False))
    horizon_flows = {leg: (ab * growth, ba * growth)
                     for leg, (ab, ba) in base_flows.items()}
    counts = {1: {m: draw(_count) for m in ALL12}}
    intersections = [{"num": 1, "lat": _CENTER_LAT, "lng": _CENTER_LNG}]
    return _layer(base_flows), _layer(horizon_flows), intersections, counts, growth


# ── 3. Consistent IPF input for furness_intersection ──────────────────────────
@st.composite
def consistent_ipf(draw):
    """A strictly-positive 4x4 seed with row/col target margins that share the
    SAME total -> IPF is guaranteed to converge. Returns
    (matrix, row_targets, col_targets, present)."""
    M = [[draw(_pos) for _ in range(4)] for _ in range(4)]
    row_t = [draw(_pos) for _ in range(4)]
    total = sum(row_t)
    raw_col = [draw(_pos) for _ in range(4)]
    s = sum(raw_col)
    col_t = [total * f / s for f in raw_col]           # rescale to match row total
    present = [True, True, True, True]
    return M, row_t, col_t, present
```

- [ ] **Step 4: Run the self-test to verify it passes**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/test_generators.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/forecasting/fuzz/generators.py backend/tests/forecasting/fuzz/test_generators.py
git commit -m "test(forecasting): fuzz generators for corridor, spine, and IPF inputs"
```

---

## Task 3: Focused balancer properties — IPF convergence and non-negativity

**Files:**
- Create: `backend/tests/forecasting/fuzz/test_fuzz_balancer.py`

- [ ] **Step 1: Write the IPF property test**

Create `backend/tests/forecasting/fuzz/test_fuzz_balancer.py`:

```python
"""Focused properties on the pure numeric core: furness_intersection (IPF) and
balance_future (corridor balance)."""
import math

from hypothesis import given

from balancer import furness_intersection
from forecasting.pass2 import balance_future
from tests.forecasting.fuzz import generators as g


# Invariant #4 — IPF convergence + matrix stability on consistent margins.
@given(g.consistent_ipf())
def test_ipf_converges_on_consistent_margins(case):
    M, row_t, col_t, present = case
    out, converged, iters, residual = furness_intersection(M, row_t, col_t, present)
    assert converged is True
    assert residual < 0.5                              # the function's own tol
    # Invariant #2 — every cell stays finite and non-negative.
    for r in range(4):
        for c in range(4):
            assert math.isfinite(out[r][c])
            assert out[r][c] >= 0.0
```

- [ ] **Step 2: Run to verify it passes on correct code**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/test_fuzz_balancer.py -q`
Expected: PASS (1 passed). A failure here is a genuine finding — investigate with superpowers:systematic-debugging before weakening the property.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/forecasting/fuzz/test_fuzz_balancer.py
git commit -m "test(forecasting): fuzz IPF convergence + non-negativity (invariants 2,4)"
```

---

## Task 4: Balancer corridor properties — conservation, round-to-5, corridor order

**Files:**
- Modify: `backend/tests/forecasting/fuzz/test_fuzz_balancer.py`

- [ ] **Step 1: Add the corridor balance property**

Append to `backend/tests/forecasting/fuzz/test_fuzz_balancer.py`:

```python
# Invariants #1 (link conservation), #2 (non-negativity), #3 (round-to-5),
# #6 (corridor-order: conservation edges follow the GIVEN links, never re-sorted).
@given(g.ew_corridor())
def test_balance_future_corridor_invariants(corridor):
    nums, coords, links, volumes = corridor
    res = balance_future(volumes, links, coords=coords)
    balanced = res["balanced"]

    # #2 non-negativity + #3 round-to-5 on every balanced movement.
    for vols in balanced.values():
        for v in vols.values():
            assert v >= 0
            assert v % 5 == 0, f"{v} not a multiple of 5"

    # #1 every Full link conserves exactly after reconciliation.
    full = [c for c in res["link_conservation"] if c["mode"] == "Full"]
    assert full, "expected Full links in a corridor"
    for c in full:
        assert c["delta"] == 0, f"link {c['fromNum']}->{c['toNum']} delta {c['delta']}"

    # #6 the conservation graph edges are EXACTLY the given links, in identity
    # (fromNum,toNum) — never reconnected by sorted intersection number.
    got_edges = {(c["fromNum"], c["toNum"]) for c in res["link_conservation"]}
    want_edges = {(l["fromNum"], l["toNum"]) for l in links}
    assert got_edges == want_edges
```

- [ ] **Step 2: Run the file**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/test_fuzz_balancer.py -q`
Expected: PASS (2 passed).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/forecasting/fuzz/test_fuzz_balancer.py
git commit -m "test(forecasting): fuzz corridor conservation, round-to-5, corridor order (invariants 1,3,6)"
```

---

## Task 5: Spine property — identity-growth conservation through refine → pass1

**Files:**
- Create: `backend/tests/forecasting/fuzz/test_fuzz_pipeline.py`

- [ ] **Step 1: Write the spine property test**

Create `backend/tests/forecasting/fuzz/test_fuzz_pipeline.py`:

```python
"""End-to-end spine + VMT properties on the pure numeric pipeline."""
from hypothesis import given

from forecasting.contract import Period
from forecasting.matcher import match_network_to_legs
from forecasting.refinement import refine_corridor
from forecasting.pass1 import forecast_corridor
from forecasting.pass2 import balance_future
from tests.forecasting.fuzz import generators as g


# Invariant #7 — identity growth (horizon == base) returns the base counts on
# every bound leg; plus #2 non-negativity through the whole spine.
@given(g.single_intersection_spine(identity=True))
def test_identity_growth_conserves_counts(case):
    base, horizon, intersections, counts, growth = case
    assert growth == 1.0
    mr = match_network_to_legs(intersections, base)
    rr = refine_corridor(mr, base, horizon, counts, Period.AM)
    [r] = rr
    bound = [d for d in ("NB", "SB", "EB", "WB")
             if r["approaches"][d]["status"] == "bound"]
    for d in bound:
        for direction in ("inbound", "outbound"):
            sub = r["approaches"][d][direction]
            if sub["status"] != "held-flat":           # held legs also equal count
                assert sub["refined"] == sub["count_base"] or \
                    abs(sub["refined"] - sub["count_base"]) < 1e-6

    futures, meta = forecast_corridor(rr, counts)
    for vols in futures.values():                       # #2 non-negativity
        for v in vols.values():
            assert v >= 0

    res = balance_future(futures, [], coords={1: intersections[0]})
    for vols in res["balanced"].values():               # #3 round-to-5 holds end-to-end
        for v in vols.values():
            assert v >= 0 and v % 5 == 0
```

- [ ] **Step 2: Run it**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/test_fuzz_pipeline.py -q`
Expected: PASS (1 passed). A failure is a real finding — debug, do not weaken.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/forecasting/fuzz/test_fuzz_pipeline.py
git commit -m "test(forecasting): fuzz identity-growth conservation through the spine (invariant 7)"
```

---

## Task 6: VMT properties — scenario linearity, daily all-or-none, non-negativity

**Files:**
- Modify: `backend/tests/forecasting/fuzz/test_fuzz_pipeline.py`
- Modify: `backend/tests/forecasting/fuzz/generators.py`

- [ ] **Step 1: Add a VMT-case generator**

Append to `backend/tests/forecasting/fuzz/generators.py`:

```python
# ── 4. Two-link EB/WB segment for corridor_vmt ────────────────────────────────
from forecasting.contract import NetworkLink as _NL   # local alias for clarity

_VMT_CORRIDOR = [{"fromNum": 1, "toNum": 2, "direction": "EB/WB"}]
_VMT_COORDS = {1: {"lat": 32.72, "lng": -117.20}, 2: {"lat": 32.72, "lng": -117.10}}
_VMT_MATCHES = [{"intersection_num": 1, "snapped_node": 100, "legs": {}},
                {"intersection_num": 2, "snapped_node": 200, "legs": {}}]


def _vmt_link(lid, fn, tn, total_flow, ab_am, ba_am):
    return _NL(link_id=lid, from_node=fn, to_node=tn,
              geometry=[(0.0, 0.0), (0.01, 0.0)],
              from_node_xy=(0.0, 0.0), to_node_xy=(0.01, 0.0),
              length_mi=0.5, daily_total=total_flow,
              flow=DirectionalFlow(ab={Period.AM: ab_am}, ba={Period.AM: ba_am}))


def _vmt_layer(total_flow, ab_am, ba_am):
    # 100 -> 150 -> 200, each 0.5 mi (chain length 1.0).
    return NetworkLayer(region="SANDAG", source_crs_epsg=2230, crs_epsg=4326,
                        scenario_year=2025, links=[
                            _vmt_link("L1", 100, 150, total_flow, ab_am, ba_am),
                            _vmt_link("L2", 150, 200, total_flow, ab_am, ba_am)])


@st.composite
def vmt_case(draw):
    """Returns (layer, existing, future, scenario_factor). Flows are non-negative;
    future = existing scaled by a growth factor; scenario_factor in (0,1)."""
    ebt = float(draw(_count)); wbt = float(draw(_count))
    grow = draw(st.floats(min_value=1.0, max_value=2.0,
                          allow_nan=False, allow_infinity=False))
    total_flow = draw(st.integers(min_value=0, max_value=20000))
    layer = _vmt_layer(total_flow, ebt or 1.0, wbt or 1.0)
    existing = {1: {"EBT": ebt, "WBT": wbt}, 2: {"EBT": ebt, "WBT": wbt}}
    future = {1: {"EBT": ebt * grow, "WBT": wbt * grow},
              2: {"EBT": ebt * grow, "WBT": wbt * grow}}
    factor = draw(st.floats(min_value=0.01, max_value=0.99,
                            allow_nan=False, allow_infinity=False))
    return layer, existing, future, factor


VMT_CORRIDOR = _VMT_CORRIDOR
VMT_COORDS = _VMT_COORDS
VMT_MATCHES = _VMT_MATCHES
```

- [ ] **Step 2: Add the VMT property test**

Append to `backend/tests/forecasting/fuzz/test_fuzz_pipeline.py`:

```python
from forecasting.vmt import corridor_vmt   # noqa: E402


# Invariants #8 (scenario linearity), #10 (daily all-or-none), #2 (non-negativity).
@given(g.vmt_case())
def test_vmt_scenario_and_daily_invariants(case):
    layer, existing, future, factor = case
    out = corridor_vmt(g.VMT_CORRIDOR, g.VMT_COORDS, g.VMT_MATCHES, layer, layer,
                       existing, future, [], Period.AM, scenario_factor=factor)
    c = out["corridor"]

    # #2 non-negativity of peak-hour VMT.
    assert c["existing_vmt"] >= 0 and c["future_vmt"] >= 0

    # #8 scenario VMT is exactly baseline * (1 - factor), by linearity.
    sc = out["scenario"]
    assert sc is not None
    assert sc["vmt"] == _approx(sc["baseline_vmt"] * (1.0 - factor))
    assert sc["baseline_vmt"] == _approx(c["future_vmt"])

    # #10 daily fields are all-or-none, never partially populated.
    daily_fields = [c["daily_existing_vmt"], c["daily_future_vmt"]]
    assert all(x is None for x in daily_fields) or all(x is not None for x in daily_fields)


def _approx(x, tol=1e-6):
    class _A:
        def __eq__(self, other):
            return abs(other - x) <= tol + 1e-9 * abs(x)
    return _A()
```

- [ ] **Step 3: Run the pipeline file**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/test_fuzz_pipeline.py -q`
Expected: PASS (2 passed).

- [ ] **Step 4: Run the whole fuzz suite together**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/ -q`
Expected: PASS (all generator self-tests + balancer + pipeline properties green).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/forecasting/fuzz/generators.py backend/tests/forecasting/fuzz/test_fuzz_pipeline.py
git commit -m "test(forecasting): fuzz VMT scenario linearity + daily all-or-none (invariants 8,10)"
```

---

## Task 7: U-turn passthrough property (invariant #5)

**Files:**
- Modify: `backend/tests/forecasting/fuzz/test_fuzz_pipeline.py`

- [ ] **Step 1: Add the U-turn passthrough property**

Append to `backend/tests/forecasting/fuzz/test_fuzz_pipeline.py`:

```python
from hypothesis import strategies as st   # noqa: E402


# Invariant #5 — U-turn volumes pass through Pass 1 unchanged (the 4x4 IPF has no
# U-turn cell, so a seeded U-turn must equal its output value exactly).
@given(g.single_intersection_spine(identity=False), st.integers(min_value=0, max_value=500))
def test_uturn_passthrough(case, nbu):
    base, horizon, intersections, counts, growth = case
    counts = {1: dict(counts[1], NBU=nbu)}              # inject a North-bound U-turn seed
    mr = match_network_to_legs(intersections, base)
    rr = refine_corridor(mr, base, horizon, counts, Period.AM)
    futures, _ = forecast_corridor(rr, counts)
    assert futures[1]["NBU"] == float(nbu)              # carried through unchanged
```

- [ ] **Step 2: Run the pipeline file**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/test_fuzz_pipeline.py -q`
Expected: PASS (3 passed).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/forecasting/fuzz/test_fuzz_pipeline.py
git commit -m "test(forecasting): fuzz U-turn passthrough (invariant 5)"
```

---

## Task 8: Fix the CI gap — run the forecasting suite (incl. fuzz) as a blocking gate

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Verify the forecasting suite is lean-clean locally first**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/ -q`
Expected: PASS with the real-shapefile integration tests reported as SKIPPED (no shapefile assumed in CI). Confirm there are NO collection errors. If any non-skipped test imports geopandas at runtime, note it — but the verified expectation is all-pass/skip.

- [ ] **Step 2: Add a pytest step to the backend CI job**

In `.github/workflows/ci.yml`, the `backend` job currently ends with the `Test suite` step that runs `PYTHON=python ./run_tests.sh` (`.github/workflows/ci.yml:47-55`). Add a new step immediately after it:

```yaml
      - name: Forecasting + fuzz suite (pytest)
        env:
          HYPOTHESIS_PROFILE: ci
        # Geo-dependent integration tests are skipif-gated on a real shapefile
        # that CI does not check out, so they skip cleanly. The numeric pipeline
        # and the fuzz bot are pure Python (no geopandas) and run here.
        run: python -m pytest tests/forecasting/ -q
```

(`pytest` and `hypothesis` were added to `requirements.txt` in Task 1, so the existing `pip install -r requirements.txt` step already provides them.)

- [ ] **Step 3: Verify the workflow file parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))" && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(backend): run forecasting + fuzz suite as a blocking gate"
```

---

## Task 9: Nightly deep-run bot (no auto-issues) + Hypothesis example DB policy

**Files:**
- Create: `.github/workflows/fuzz-nightly.yml`
- Modify: `backend/.gitignore` (create if absent)

- [ ] **Step 1: Decide the Hypothesis example-DB policy**

Hypothesis writes a per-developer `.hypothesis/` example cache. We do NOT want the transient local cache in git, but we DO want any committed counterexample regressions to replay. Policy: ignore the cache directory; when the nightly bot finds a counterexample, the fix lands as an explicit `@example(...)` pin in the relevant test (committed), not as a cache blob.

Create or append to `backend/.gitignore`:

```
.hypothesis/
```

- [ ] **Step 2: Create the nightly workflow**

Create `.github/workflows/fuzz-nightly.yml`:

```yaml
name: Fuzz — nightly deep run

# Deep, randomized property exploration. Fails loudly in the Actions tab on a
# violation; it does NOT open issues or modify the repo.
on:
  schedule:
    - cron: '0 8 * * *'        # 08:00 UTC daily
  workflow_dispatch:           # allow manual runs

jobs:
  fuzz:
    name: Math-soundness fuzz (nightly profile)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - name: Deep fuzz run
        env:
          HYPOTHESIS_PROFILE: nightly
          ANTHROPIC_API_KEY: placeholder-not-used-by-tested-endpoints
        run: python -m pytest tests/forecasting/fuzz/ -q --hypothesis-show-statistics
```

- [ ] **Step 3: Verify the workflow file parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/fuzz-nightly.yml'))" && echo OK`
Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/fuzz-nightly.yml backend/.gitignore
git commit -m "ci(fuzz): nightly deep-run bot (fails loudly, no auto-issues)"
```

---

## Task 10: Final verification and PR

- [ ] **Step 1: Run the full fuzz suite under the nightly profile once locally**

Run (from `backend/`): `HYPOTHESIS_PROFILE=nightly .venv-forecasting/bin/python -m pytest tests/forecasting/fuzz/ -q --hypothesis-show-statistics`
Expected: PASS. This is the deep pass — if a real invariant violation exists, it surfaces here with a shrunk counterexample. If so, STOP and debug with superpowers:systematic-debugging; a violation is the bot doing its job.

- [ ] **Step 2: Run the existing forecasting suite to confirm no regressions**

Run (from `backend/`): `.venv-forecasting/bin/python -m pytest tests/forecasting/ -q`
Expected: PASS / SKIP, no errors.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/math-soundness-fuzz-bot
gh pr create --title "test(forecasting): math-soundness fuzz bot + CI gap fix" \
  --body "Hypothesis property-based fuzz bot for the pure-numeric forecasting pipeline. CI gate + nightly deep run (no auto-issues). Also runs the previously-unrun forecasting pytest suite in CI. See docs/superpowers/specs/2026-06-05-math-soundness-fuzz-bot-design.md."
```

Expected: PR created; both CI checks (existing + new forecasting/fuzz step) run and go green.

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** invariants 1,2,3,4,6 → Tasks 3–4; 7 → Task 5; 8,10 → Task 6; 5 (U-turn passthrough) → Task 7. That is 9 of the 10 spec invariants covered by a dedicated property.
- **Invariant 9 (`total_flow` identity) — reclassified, not dropped:** the `total_flow == Σ period/directional flows` identity (commit `ab9b821`) lives in the SANDAG **adapter / synth-horizon** layer, where `daily_total` is populated from source columns. That layer needs shapefiles + geopandas and is explicitly **out of scope** for this lean numeric pipeline per the spec §6 (geo-ingest fuzzing is deferred). It belongs to the deferred geo-ingest fuzz milestone, not this one. Flag this to the user explicitly so it is a conscious deferral, not a silent gap.
- **`_approx` helper:** used instead of `pytest.approx` only to keep the comparison explicit inside generated runs; `pytest.approx` also works and may be substituted.
- **If a property fails on first run:** that is a candidate finding. Do not weaken the assertion to make it pass. Investigate with superpowers:systematic-debugging, confirm whether it's a real math bug or an over-broad generator (e.g. a degenerate corridor the engine legitimately rejects), and either fix the code or tighten the generator with `assume(...)`.
