"""Tests for NCHRP 255 refinement (module 5).

Layers are built directly (pure Python); the real matcher feeds refinement so the
two integrate. Ratio is the operative method; difference/combined are gated on a
peak-hour factor K.

Run from backend/ with the forecasting venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting/test_refinement.py -v
"""

import math
from pathlib import Path

import pytest

from forecasting.contract import DirectionalFlow, NetworkLayer, NetworkLink, Period
from forecasting.matcher import match_network_to_legs
from forecasting.refinement import refine_corridor

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


def _link(lid, fn, tn, fxy, txy, ab, ba, fc="Major Arterial"):
    return NetworkLink(link_id=str(lid), from_node=fn, to_node=tn,
                       geometry=[fxy, txy], from_node_xy=fxy, to_node_xy=txy,
                       functional_class=fc,
                       flow=DirectionalFlow(ab={Period.AM: ab}, ba={Period.AM: ba}))


# leg key → (from_node, to_node, from_xy, to_xy). Bearings: N=0(SB), S=180(NB),
# E=90(WB), W=270(EB). Orientation deliberately mixes AB/BA inbound reads.
_SPEC = {
    "N": (100, 1, C_XY, _dest(0)),     # SB approach: inbound_to(100)=ba, outbound=ab
    "S": (2, 100, _dest(180), C_XY),   # NB approach: inbound_to(100)=ab, outbound=ba
    "E": (100, 3, C_XY, _dest(90)),    # WB approach: inbound=ba, outbound=ab
    "W": (4, 100, _dest(270), C_XY),   # EB approach: inbound=ab, outbound=ba
}
_DEF = {"N": (900, 1200), "S": (1000, 1160), "E": (700, 800), "W": (600, 650)}


def _layer(flows):
    """flows: {leg: (ab, ba)}. Omit a leg to drop that link."""
    links = [_link(k, *_SPEC[k], ab, ba) for k, (ab, ba) in flows.items()]
    return NetworkLayer(region="SANDAG", source_crs_epsg=2230, crs_epsg=4326,
                        scenario_year=2025, links=links)


def _scaled(flows, k):
    return {leg: (ab * k, ba * k) for leg, (ab, ba) in flows.items()}


COUNTS = {1: {"NBL": 100, "NBT": 500, "NBR": 50, "SBL": 80, "SBT": 480, "SBR": 40,
              "EBL": 60, "EBT": 300, "EBR": 30, "WBL": 70, "WBT": 320, "WBR": 35}}


def _intx(approaches=None):
    it = {"num": 1, "lat": CENTER_LAT, "lng": CENTER_LNG}
    if approaches is not None:
        it["approaches"] = approaches
    return it


def _refine(base_flows, horizon_flows, approaches=None, counts=None, **kw):
    base, horizon = _layer(base_flows), _layer(horizon_flows)
    mr = match_network_to_legs([_intx(approaches)], base)
    return refine_corridor(mr, base, horizon, counts or COUNTS, Period.AM, **kw)[0]


# ── Ratio, both directions ────────────────────────────────────────────────────
def test_ratio_both_directions():
    r = _refine(_DEF, _scaled(_DEF, 1.5))
    nb = r["approaches"]["NB"]
    assert nb["status"] == "bound"
    assert nb["link_id"] == "S"
    # NB inbound = link "S" AB (inbound_to(100)); C_in = 100+500+50 = 650.
    assert nb["inbound"]["model_base"] == 1000
    assert nb["inbound"]["growth_factor"] == 1.5
    assert nb["inbound"]["refined"] == pytest.approx(975.0)     # 650 × 1.5
    assert nb["inbound"]["method"] == "ratio"
    # NB outbound = link "S" BA (outbound_from(100)); exit via south leg = SB
    # outflow SBT+WBL+EBR = 480+70+30 = 580.
    assert nb["outbound"]["model_base"] == 1160
    assert nb["outbound"]["refined"] == pytest.approx(870.0)    # 580 × 1.5
    assert all(r["approaches"][d]["status"] == "bound" for d in ("NB", "SB", "EB", "WB"))
    # Difference/Combined unavailable without K.
    assert nb["inbound"]["difference"] is None
    assert nb["inbound"]["combined"] is None


# ── Outbound (column) total excludes the U-turn ───────────────────────────────
def test_outbound_excludes_uturn():
    # NB outbound exits via the south leg (SB). DIRECTION_SPEC['SB']['outflow_u']
    # is 'NBU' — adding it to the counts must NOT inflate the column total, since
    # the Pass 1 IPF matrix has no U-turn cell to hold it.
    counts = {1: dict(COUNTS[1], NBU=99)}
    r = _refine(_DEF, _scaled(_DEF, 1.5), counts=counts)
    nb = r["approaches"]["NB"]
    # SBT+WBL+EBR = 480+70+30 = 580; the NBU=99 is excluded.
    assert nb["outbound"]["count_base"] == 580
    assert nb["outbound"]["refined"] == pytest.approx(870.0)     # 580 × 1.5
    # Inbound is L+T+R only (never carried a U-turn).
    assert nb["inbound"]["count_base"] == 650


# ── Held flat when model base is zero ─────────────────────────────────────────
def test_held_flat_on_zero_model_base():
    base = dict(_DEF, S=(0, 1160))                 # NB inbound Mb = 0
    r = _refine(base, _scaled(_DEF, 1.5))
    nb_in = r["approaches"]["NB"]["inbound"]
    assert nb_in["status"] == "held-flat"
    assert nb_in["method"] == "held-flat"
    assert nb_in["refined"] == pytest.approx(650.0)            # held at the count
    assert any(f["code"] == "REFINE-MODEL-ZERO-BASE" for f in nb_in["flags"])


# ── Growth outlier ────────────────────────────────────────────────────────────
def test_growth_outlier_flag():
    base = dict(_DEF, S=(10, 1160))
    horizon = dict(_scaled(_DEF, 1.5), S=(100, 1740))          # NB inbound growth 10×
    r = _refine(base, horizon)
    nb_in = r["approaches"]["NB"]["inbound"]
    assert nb_in["growth_factor"] == 10.0
    assert any(f["code"] == "REFINE-GROWTH-OUTLIER" for f in nb_in["flags"])


# ── Pending: unmatched leg ────────────────────────────────────────────────────
def test_pending_when_leg_unmatched():
    flows = {k: v for k, v in _DEF.items() if k != "W"}        # no west link → EB unmatched
    r = _refine(flows, _scaled(flows, 1.5))
    eb = r["approaches"]["EB"]
    assert eb["status"] == "pending"
    assert eb["reason"] == "unmatched"
    assert eb["inbound"] is None and eb["outbound"] is None


# ── Pending: matched but no horizon twin ──────────────────────────────────────
def test_pending_when_no_horizon_twin():
    horizon = {k: v for k, v in _scaled(_DEF, 1.5).items() if k != "S"}  # drop NB link
    r = _refine(_DEF, horizon)
    nb = r["approaches"]["NB"]
    assert nb["status"] == "pending"
    assert nb["reason"] == "no-horizon-twin"


# ── Difference / Combined with a peak-hour factor ─────────────────────────────
def test_combined_with_peak_hour_factor():
    r = _refine(_DEF, _scaled(_DEF, 1.5), peak_hour_factor=0.4, method="combined")
    nb_in = r["approaches"]["NB"]["inbound"]
    # C=650, Mb=1000, Mf=1500. ratio=975; diff=650+0.4·500=850; combined=912.5.
    assert nb_in["ratio"] == pytest.approx(975.0)
    assert nb_in["difference"] == pytest.approx(850.0)
    assert nb_in["combined"] == pytest.approx(912.5)
    assert nb_in["method"] == "combined"
    assert nb_in["refined"] == pytest.approx(912.5)


def test_method_falls_back_to_ratio_without_k():
    r = _refine(_DEF, _scaled(_DEF, 1.5), method="combined")   # no K
    nb_in = r["approaches"]["NB"]["inbound"]
    assert nb_in["method"] == "ratio"
    assert any(f["code"] == "REFINE-NO-K" for f in nb_in["flags"])


# ── Negative clamp (difference path) ──────────────────────────────────────────
def test_negative_difference_clamped():
    base = dict(_DEF, S=(2000, 1160))
    horizon = dict(_scaled(_DEF, 1.5), S=(0, 1740))            # NB inbound Mf=0, Mb=2000
    r = _refine(base, horizon, peak_hour_factor=1.0, method="difference")
    nb_in = r["approaches"]["NB"]["inbound"]
    # diff = 650 + 1.0·(0 − 2000) = −1350 → clamp 0.
    assert nb_in["refined"] == 0.0
    assert any(f["code"] == "REFINE-NEGATIVE-CLAMP" for f in nb_in["flags"])


# ── Method divergence ─────────────────────────────────────────────────────────
def test_method_divergence_flag():
    base = dict(_DEF, S=(100, 1160))
    horizon = dict(_scaled(_DEF, 1.5), S=(2000, 1740))         # NB inbound growth 20×
    r = _refine(base, horizon, peak_hour_factor=0.4, method="ratio")
    nb_in = r["approaches"]["NB"]["inbound"]
    # ratio=650·20=13000; diff=650+0.4·1900=1410 → diverge ~89%.
    assert any(f["code"] == "REFINE-METHOD-DIVERGENCE" for f in nb_in["flags"])


# ── Absent leg ────────────────────────────────────────────────────────────────
def test_absent_leg():
    flows = {k: v for k, v in _DEF.items() if k != "W"}        # no west link
    approaches = {"NB": {"exists": True}, "SB": {"exists": True},
                  "WB": {"exists": True}, "EB": {"exists": False}}
    r = _refine(flows, _scaled(flows, 1.5), approaches=approaches)
    assert r["approaches"]["EB"]["status"] == "absent"


# ── Integration: real geometry, identity growth (base == horizon) ─────────────
REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"
_ALL12 = ["NBL", "NBT", "NBR", "SBL", "SBT", "SBR",
          "EBL", "EBT", "EBR", "WBL", "WBT", "WBR"]


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_identity_growth_returns_count():
    from forecasting.adapters.sandag import ingest_sandag
    lat, lng = 32.624067, -116.959736                         # DISCOVERY FALLS node
    layer = ingest_sandag(REAL_SHP, 2025, [{"num": 1, "lat": lat, "lng": lng}])
    mr = match_network_to_legs([{"num": 1, "lat": lat, "lng": lng}], layer)
    counts = {1: {m: 100 for m in _ALL12}}
    # base == horizon → growth 1.0 → ratio = count (held-flat legs also = count).
    [r] = refine_corridor(mr, layer, layer, counts, Period.AM)
    bound = [d for d in ("NB", "SB", "EB", "WB")
             if r["approaches"][d]["status"] == "bound"]
    assert bound, "expected at least one bound leg on the real node"
    for d in bound:
        for direction in ("inbound", "outbound"):
            sub = r["approaches"][d][direction]
            assert sub["refined"] == pytest.approx(sub["count_base"])
