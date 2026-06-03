"""Tests for Future Furness Pass 1 (module 6).

Full pipeline: layers built directly → real matcher → real refinement → Pass 1.
The IPF engine is reused from balancer.furness_intersection; these tests verify
the glue (target mapping, pending hold-flat / manual override, U-turn passthrough,
zero-seed, imbalance residual).

Run from backend/ with the forecasting venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting/test_pass1.py -v
"""

import math
from pathlib import Path

import pytest

from forecasting.contract import DirectionalFlow, NetworkLayer, NetworkLink, Period
from forecasting.matcher import match_network_to_legs
from forecasting.refinement import refine_corridor
from forecasting.pass1 import forecast_corridor

CENTER_LNG, CENTER_LAT = -117.160, 32.720
C_XY = (CENTER_LNG, CENTER_LAT)


def _dest(brng, dist_ft=500.0):
    r = 3958.8 * 5280.0
    d = dist_ft / r
    th = math.radians(brng)
    phi1, lam1 = math.radians(CENTER_LAT), math.radians(CENTER_LNG)
    phi2 = math.asin(math.sin(phi1) * math.cos(d) + math.cos(phi1) * math.sin(d) * math.cos(th))
    lam2 = lam1 + math.atan2(math.sin(th) * math.sin(d) * math.cos(phi1),
                             math.cos(d) - math.sin(phi1) * math.sin(phi2))
    return (math.degrees(lam2), math.degrees(phi2))


def _link(lid, fn, tn, fxy, txy, ab, ba):
    return NetworkLink(link_id=str(lid), from_node=fn, to_node=tn,
                       geometry=[fxy, txy], from_node_xy=fxy, to_node_xy=txy,
                       functional_class="Major Arterial",
                       flow=DirectionalFlow(ab={Period.AM: ab}, ba={Period.AM: ba}))


_SPEC = {
    "N": (100, 1, C_XY, _dest(0)),     # SB approach
    "S": (2, 100, _dest(180), C_XY),   # NB approach
    "E": (100, 3, C_XY, _dest(90)),    # WB approach
    "W": (4, 100, _dest(270), C_XY),   # EB approach
}
_DEF = {"N": (900, 1200), "S": (1000, 1160), "E": (700, 800), "W": (600, 650)}


def _layer(flows):
    links = [_link(k, *_SPEC[k], ab, ba) for k, (ab, ba) in flows.items()]
    return NetworkLayer(region="SANDAG", source_crs_epsg=2230, crs_epsg=4326,
                        scenario_year=2025, links=links)


def _scaled(flows, k):
    return {leg: (ab * k, ba * k) for leg, (ab, ba) in flows.items()}


COUNTS = {1: {"NBL": 100, "NBT": 500, "NBR": 50, "SBL": 80, "SBT": 480, "SBR": 40,
              "EBL": 60, "EBT": 300, "EBR": 30, "WBL": 70, "WBT": 320, "WBR": 35}}

# Approach (row) and exit (column) movement sets — exits exclude U-turns.
NB_APP = ["NBL", "NBT", "NBR"]
EB_APP = ["EBL", "EBT", "EBR"]
SB_EXIT = ["SBT", "EBR", "WBL"]            # S-leg exit (SB direction)


def _mv(d, keys):
    return sum(d.get(k, 0) for k in keys)


def _intx(approaches=None):
    it = {"num": 1, "lat": CENTER_LAT, "lng": CENTER_LNG}
    if approaches is not None:
        it["approaches"] = approaches
    return it


def _pass1(base_flows, horizon_flows, counts=None, approaches=None,
           manual_targets=None, refine_kw=None):
    base, horizon = _layer(base_flows), _layer(horizon_flows)
    cnts = counts or COUNTS
    mr = match_network_to_legs([_intx(approaches)], base)
    rr = refine_corridor(mr, base, horizon, cnts, Period.AM, **(refine_kw or {}))
    return forecast_corridor(rr, cnts, manual_targets=manual_targets)


# ── Clean 4-leg ratio fit ─────────────────────────────────────────────────────
def test_clean_four_leg_ratio_fit():
    futures, meta = _pass1(_DEF, _scaled(_DEF, 1.5))
    fut = futures[1]
    assert meta[1]["converged"] is True
    assert meta[1]["residual"] < 1.0                       # uniform growth stays balanced
    # NB approach row fits its refined target: 650 × 1.5 = 975.
    assert _mv(fut, NB_APP) == pytest.approx(975.0, abs=1.0)
    # S-leg exit column fits its target: 580 × 1.5 = 870.
    assert _mv(fut, SB_EXIT) == pytest.approx(870.0, abs=1.0)


# ── 3-leg absent ──────────────────────────────────────────────────────────────
def test_three_leg_absent_stays_zero():
    flows = {k: v for k, v in _DEF.items() if k != "W"}    # no west link
    counts = {1: {k: (0 if k.startswith("EB") else v) for k, v in COUNTS[1].items()}}
    approaches = {"NB": {"exists": True}, "SB": {"exists": True},
                  "WB": {"exists": True}, "EB": {"exists": False}}
    futures, _ = _pass1(flows, _scaled(flows, 1.5), counts=counts, approaches=approaches)
    assert _mv(futures[1], EB_APP) == 0.0                  # absent leg → zero


# ── Pending leg held flat ─────────────────────────────────────────────────────
def test_pending_leg_held_flat():
    flows = {k: v for k, v in _DEF.items() if k != "W"}    # EB unmatched (leg exists)
    futures, meta = _pass1(flows, _scaled(flows, 1.5))
    assert any(f["code"] == "PASS1-PENDING-HELD-FLAT" for f in meta[1]["flags"])
    # Held at base (390), not grown to 585.
    assert _mv(futures[1], EB_APP) < 480.0


# ── Pending leg with manual override ──────────────────────────────────────────
def test_pending_leg_manual_override():
    flows = {k: v for k, v in _DEF.items() if k != "W"}
    mt = {1: {"EB": {"inbound": 1000.0, "outbound": 900.0}}}
    futures, meta = _pass1(flows, _scaled(flows, 1.5), manual_targets=mt)
    assert any(f["code"] == "PASS1-PENDING-MANUAL" for f in meta[1]["flags"])
    # The manual target (1000) drives EB — far above held-flat (390) or growth
    # (585). It won't land exactly on 1000: the manual in/out (1000/900) against
    # the other legs' 1.5× growth makes Σrow ≠ Σcol, so the IPF reconciles to
    # KL-min and reports the gap as residual (the documented imbalance behavior).
    assert _mv(futures[1], EB_APP) > 850.0


# ── Zero-seed movement stays zero ─────────────────────────────────────────────
def test_zero_seed_movement_stays_zero():
    counts = {1: dict(COUNTS[1], NBL=0)}                   # banned NB left
    futures, _ = _pass1(_DEF, _scaled(_DEF, 1.5), counts=counts)
    assert futures[1]["NBL"] == 0.0                        # IPF cannot create it
    assert futures[1]["NBT"] > 0.0


# ── In/out imbalance reports a residual ───────────────────────────────────────
def test_in_out_imbalance_residual():
    # Horizon grows AB 2× but BA 1× → Σinbound ≠ Σoutbound at the node.
    horizon = {k: (ab * 2, ba * 1) for k, (ab, ba) in _DEF.items()}
    futures, meta = _pass1(_DEF, horizon)
    assert meta[1]["residual"] > 0.0                       # imbalance exposed, not hidden
    assert meta[1]["converged"] is True                    # matrix still stabilizes


# ── U-turn passthrough ────────────────────────────────────────────────────────
def test_uturn_passthrough():
    counts = {1: dict(COUNTS[1], NBU=77)}
    futures, _ = _pass1(_DEF, _scaled(_DEF, 1.5), counts=counts)
    assert futures[1]["NBU"] == 77.0                       # carried through unchanged


# ── Integration: full pipeline on real geometry, identity growth ──────────────
REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"
_ALL12 = ["NBL", "NBT", "NBR", "SBL", "SBT", "SBR",
          "EBL", "EBT", "EBR", "WBL", "WBT", "WBR"]


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_pipeline_identity_growth():
    from forecasting.adapters.sandag import ingest_sandag
    lat, lng = 32.624067, -116.959736                     # DISCOVERY FALLS node
    layer = ingest_sandag(REAL_SHP, 2025, [{"num": 1, "lat": lat, "lng": lng}])
    counts = {1: {m: 100 for m in _ALL12}}
    mr = match_network_to_legs([{"num": 1, "lat": lat, "lng": lng}], layer)
    rr = refine_corridor(mr, layer, layer, counts, Period.AM)   # base == horizon
    futures, meta = forecast_corridor(rr, counts)
    assert 1 in futures
    # Identity growth (+ held-flat pending legs) → matrix ≈ base; total preserved.
    assert _mv(futures[1], _ALL12) == pytest.approx(1200.0, rel=0.05)
