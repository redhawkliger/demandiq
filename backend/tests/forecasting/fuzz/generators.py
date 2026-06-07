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
    """k intersections with DISTINCT intersection numbers in arbitrary order (a
    permutation, so frequently NOT sorted) — this is what exercises the
    corridor-order invariant downstream. Links connect consecutive intersections
    in the GIVEN order. Returns (nums, coords, links, volumes)."""
    k = draw(st.integers(min_value=2, max_value=6))
    nums = draw(st.lists(st.integers(min_value=1, max_value=99),
                         min_size=k, max_size=k, unique=True))
    nums = draw(st.permutations(nums))   # arbitrary order — exercises corridor-order invariant #6
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
