"""Tests for the link-to-leg matcher (module 4).

Layers are built directly as NetworkLink/NetworkLayer objects (no shapefiles) —
the matcher is pure-Python and needs no geo deps. Bearings are placed exactly
via a destination-point helper so the geometry is unambiguous.

Run from backend/ with the forecasting venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting/test_matcher.py -v
"""

import math
from pathlib import Path

import pytest

from forecasting.contract import DirectionalFlow, NetworkLayer, NetworkLink, Period
from forecasting.matcher import (
    APPROACH_LEG_BEARING,
    SNAP_TOLERANCE_FT,
    match_network_to_legs,
)

CENTER_LNG, CENTER_LAT = -117.160, 32.720


def _dest(lng, lat, brng, dist_ft):
    """Destination (lng, lat) a given bearing + distance (ft) from a point."""
    r = 3958.8 * 5280.0
    d = dist_ft / r
    th = math.radians(brng)
    phi1, lam1 = math.radians(lat), math.radians(lng)
    phi2 = math.asin(math.sin(phi1) * math.cos(d) + math.cos(phi1) * math.sin(d) * math.cos(th))
    lam2 = lam1 + math.atan2(math.sin(th) * math.sin(d) * math.cos(phi1),
                             math.cos(d) - math.sin(phi1) * math.sin(phi2))
    return (math.degrees(lam2), math.degrees(phi2))


def _link(lid, from_node, to_node, from_xy, to_xy, ab_am, ba_am, fc="Major Arterial"):
    return NetworkLink(
        link_id=str(lid), from_node=from_node, to_node=to_node,
        geometry=[from_xy, to_xy], from_node_xy=from_xy, to_node_xy=to_xy,
        functional_class=fc,
        flow=DirectionalFlow(ab={Period.AM: ab_am}, ba={Period.AM: ba_am}),
    )


def _layer(links):
    return NetworkLayer(region="SANDAG", source_crs_epsg=2230, crs_epsg=4326,
                        scenario_year=2025, links=links)


def _radial(node_id, brng, dist_ft=500.0):
    """Far-end coord for a leg radiating `brng` from CENTER."""
    return _dest(CENTER_LNG, CENTER_LAT, brng, dist_ft)


CENTER_XY = (CENTER_LNG, CENTER_LAT)
NODE = 100


def _intersection(num=1, lat=CENTER_LAT, lng=CENTER_LNG, approaches=None):
    it = {"num": num, "lat": lat, "lng": lng}
    if approaches is not None:
        it["approaches"] = approaches
    return it


# ── Convention sanity ─────────────────────────────────────────────────────────
def test_approach_leg_bearing_matches_s6_convention():
    assert APPROACH_LEG_BEARING == {"NB": 180.0, "SB": 0.0, "EB": 270.0, "WB": 90.0}


# ── Clean 4-leg ───────────────────────────────────────────────────────────────
def _clean_four_leg_layer():
    # North leg (link FROM node → inbound to node is BA), South leg (link TO node
    # → inbound is AB), and so on — mixes both AB/BA orientations on purpose.
    return _layer([
        _link("N", NODE, 1, CENTER_XY, _radial(1, 0.0),   ab_am=11, ba_am=12),   # SB approach, inbound=BA=12
        _link("S", 2, NODE, _radial(2, 180.0), CENTER_XY, ab_am=21, ba_am=22),   # NB approach, inbound=AB=21
        _link("E", NODE, 3, CENTER_XY, _radial(3, 90.0),  ab_am=31, ba_am=32),   # WB approach, inbound=BA=32
        _link("W", 4, NODE, _radial(4, 270.0), CENTER_XY, ab_am=41, ba_am=42),   # EB approach, inbound=AB=41
    ])


def test_clean_four_leg_all_matched():
    [r] = match_network_to_legs([_intersection()], _clean_four_leg_layer())
    assert r["snapped_node"] == NODE
    assert r["snap_distance_ft"] < 1.0
    assert {d: r["legs"][d]["status"] for d in ("NB", "SB", "EB", "WB")} == {
        "NB": "matched", "SB": "matched", "EB": "matched", "WB": "matched"}
    assert r["legs"]["SB"]["link_id"] == "N"
    assert r["legs"]["NB"]["link_id"] == "S"
    assert r["legs"]["WB"]["link_id"] == "E"
    assert r["legs"]["EB"]["link_id"] == "W"
    assert not r["unbound_links"]
    assert not r["flags"]


def test_inbound_reads_follow_ab_ba():
    [r] = match_network_to_legs([_intersection()], _clean_four_leg_layer())
    # SB leg is link "N" (from_node==NODE) → inbound is BA == 12.
    assert r["legs"]["SB"]["inbound"]["AM"] == 12
    # NB leg is link "S" (to_node==NODE) → inbound is AB == 21.
    assert r["legs"]["NB"]["inbound"]["AM"] == 21
    assert r["legs"]["WB"]["inbound"]["AM"] == 32   # link "E", BA
    assert r["legs"]["EB"]["inbound"]["AM"] == 41   # link "W", AB


# ── 3-leg T (one approach exists:false) ───────────────────────────────────────
def test_three_leg_absent_approach():
    # No west link; EB approach (west leg) marked DNE.
    layer = _layer([
        _link("N", NODE, 1, CENTER_XY, _radial(1, 0.0),   ab_am=1, ba_am=1),
        _link("S", 2, NODE, _radial(2, 180.0), CENTER_XY, ab_am=1, ba_am=1),
        _link("E", NODE, 3, CENTER_XY, _radial(3, 90.0),  ab_am=1, ba_am=1),
    ])
    approaches = {"NB": {"exists": True}, "SB": {"exists": True},
                  "WB": {"exists": True}, "EB": {"exists": False}}
    [r] = match_network_to_legs([_intersection(approaches=approaches)], layer)
    assert r["legs"]["EB"]["status"] == "absent"
    assert r["legs"]["NB"]["status"] == "matched"
    assert r["legs"]["SB"]["status"] == "matched"
    assert r["legs"]["WB"]["status"] == "matched"
    assert not r["unbound_links"]


# ── Skew beyond threshold → ambiguous ─────────────────────────────────────────
def test_skewed_leg_flagged_ambiguous():
    # N-S corridor skewed 40° (links at 40° and 220°); only NB/SB exist.
    layer = _layer([
        _link("A", NODE, 1, CENTER_XY, _radial(1, 40.0),  ab_am=1, ba_am=1),   # → SB (dev 40)
        _link("B", 2, NODE, _radial(2, 220.0), CENTER_XY, ab_am=1, ba_am=1),   # → NB (dev 40)
    ])
    approaches = {"NB": {"exists": True}, "SB": {"exists": True},
                  "EB": {"exists": False}, "WB": {"exists": False}}
    [r] = match_network_to_legs([_intersection(approaches=approaches)], layer)
    assert r["legs"]["SB"]["status"] == "ambiguous"
    assert r["legs"]["SB"]["deviation_deg"] == 40.0
    assert r["legs"]["SB"]["candidates"] == ["A"]
    assert r["legs"]["NB"]["status"] == "ambiguous"


# ── Two links contest one slot within the band → ambiguous w/ candidates ──────
def test_two_links_contest_slot():
    # Two east-ish links at 85° and 100° both near WB (exp 90), within 20°.
    layer = _layer([
        _link("N",  NODE, 1, CENTER_XY, _radial(1, 0.0),   ab_am=1, ba_am=1),
        _link("S",  2, NODE, _radial(2, 180.0), CENTER_XY, ab_am=1, ba_am=1),
        _link("E1", NODE, 3, CENTER_XY, _radial(3, 85.0),  ab_am=1, ba_am=1),
        _link("E2", NODE, 4, CENTER_XY, _radial(4, 100.0), ab_am=1, ba_am=1),
    ])
    [r] = match_network_to_legs([_intersection()], layer)
    assert r["legs"]["WB"]["status"] == "ambiguous"
    assert set(r["legs"]["WB"]["candidates"]) == {"E1", "E2"}
    # No genuine west link → EB unmatched. Contenders are candidates, not unbound.
    assert r["legs"]["EB"]["status"] == "unmatched"
    assert not r["unbound_links"]


# ── Unbound ramp ──────────────────────────────────────────────────────────────
def test_unbound_ramp():
    layer = _layer([
        _link("N", NODE, 1, CENTER_XY, _radial(1, 0.0),   ab_am=1, ba_am=1),
        _link("S", 2, NODE, _radial(2, 180.0), CENTER_XY, ab_am=1, ba_am=1),
        _link("E", NODE, 3, CENTER_XY, _radial(3, 90.0),  ab_am=1, ba_am=1),
        _link("W", 4, NODE, _radial(4, 270.0), CENTER_XY, ab_am=1, ba_am=1),
        _link("RAMP", NODE, 5, CENTER_XY, _radial(5, 45.0), ab_am=1, ba_am=1, fc="Ramp"),
    ])
    [r] = match_network_to_legs([_intersection()], layer)
    assert all(r["legs"][d]["status"] == "matched" for d in ("NB", "SB", "EB", "WB"))
    assert len(r["unbound_links"]) == 1
    assert r["unbound_links"][0]["link_id"] == "RAMP"
    assert r["unbound_links"][0]["functional_class"] == "Ramp"


# ── Large snap distance → flag, no binding ────────────────────────────────────
def test_large_snap_distance_flags_and_skips_binding():
    layer = _clean_four_leg_layer()
    # Intersection 250 ft north of the node (> 150 ft tolerance).
    far_lng, far_lat = _dest(CENTER_LNG, CENTER_LAT, 0.0, 250.0)
    [r] = match_network_to_legs([_intersection(lat=far_lat, lng=far_lng)], layer)
    assert any(f["code"] == "SNAP-DISTANCE" for f in r["flags"])
    assert all(r["legs"][d]["status"] == "unmatched" for d in ("NB", "SB", "EB", "WB"))


# ── Snap collision: two intersections, one node ───────────────────────────────
def test_snap_collision():
    layer = _clean_four_leg_layer()
    a = _intersection(num=1)                                   # at CENTER
    b_lng, b_lat = _dest(CENTER_LNG, CENTER_LAT, 90.0, 50.0)   # 50 ft east, still nearest NODE
    b = _intersection(num=2, lat=b_lat, lng=b_lng)
    results = match_network_to_legs([a, b], layer)
    for r in results:
        assert r["snapped_node"] == NODE
        assert any(f["code"] == "SNAP-COLLISION" for f in r["flags"])


# ── Integration: real SANDAG node (gated) ─────────────────────────────────────
REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_node_matches_and_reads_inbound():
    from forecasting.adapters.sandag import ingest_sandag
    node_lat, node_lng = 32.624067, -116.959736          # DISCOVERY FALLS node
    layer = ingest_sandag(REAL_SHP, 2025, [{"num": 1, "lat": node_lat, "lng": node_lng}])
    [r] = match_network_to_legs([_intersection(lat=node_lat, lng=node_lng)], layer)
    assert r["snapped_node"] is not None
    assert r["snap_distance_ft"] <= SNAP_TOLERANCE_FT  # placed ON a real node
    bound = [d for d in ("NB", "SB", "EB", "WB")
             if r["legs"][d]["status"] in ("matched", "ambiguous")]
    assert bound, "expected at least one leg bound to a real link"
    for d in bound:
        assert r["legs"][d]["inbound"] is not None
