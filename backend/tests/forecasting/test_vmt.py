"""Tests for corridor VMT (Milestone 1) — the deterministic math + failure modes.

Run from backend/ with the forecasting venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting/test_vmt.py -v
"""

import pytest

from forecasting.contract import DirectionalFlow, NetworkLayer, NetworkLink, Period
from forecasting.vmt import corridor_vmt

# Two intersections (1 west, 2 east) on an EB/WB corridor. The model splits the
# segment into TWO links via mid-block node 150 — so a correct trace must sum
# both (length 1.0 mi), not just the incident link (0.5).
COORDS = {1: {"lat": 32.72, "lng": -117.20}, 2: {"lat": 32.72, "lng": -117.10}}
CORRIDOR = [{"fromNum": 1, "toNum": 2, "direction": "EB/WB"}]
MATCHES = [{"intersection_num": 1, "snapped_node": 100, "legs": {}},
           {"intersection_num": 2, "snapped_node": 200, "legs": {}}]


def _nl(lid, fn, tn, *, len_mile, total_flow, ab_am, ba_am):
    return NetworkLink(
        link_id=lid, from_node=fn, to_node=tn,
        geometry=[(0.0, 0.0), (0.01, 0.0)], from_node_xy=(0.0, 0.0), to_node_xy=(0.01, 0.0),
        flow=DirectionalFlow(),
        source_attributes={"len_mile": len_mile, "total_flow": total_flow,
                           "ab_am_flow": ab_am, "ba_am_flow": ba_am},
    )


def _layer(links):
    return NetworkLayer(region="SANDAG", source_crs_epsg=2230, crs_epsg=4326,
                        scenario_year=2025, links=links)


def _two_link_layer(total_flow=10000, ab_am=1000, ba_am=1000):
    # 100 → 150 → 200, each 0.5 mi.
    return _layer([
        _nl("L1", 100, 150, len_mile=0.5, total_flow=total_flow, ab_am=ab_am, ba_am=ba_am),
        _nl("L2", 150, 200, len_mile=0.5, total_flow=total_flow, ab_am=ab_am, ba_am=ba_am),
    ])


# int1: EB outflow (EBT) = 1000, WB approach (WBT) = 800.
# int2: EB approach (EBT) = 1000, WB outflow (WBT) = 800. → EB 1000 + WB 800 = 1800.
EXISTING = {1: {"EBT": 1000, "WBT": 800}, 2: {"EBT": 1000, "WBT": 800}}
FUTURE = {1: {"EBT": 1500, "WBT": 1200}, 2: {"EBT": 1500, "WBT": 1200}}  # ×1.5


def _run(base=None, horizon=None, existing=EXISTING, future=FUTURE, refinement=None, **kw):
    base = base or _two_link_layer()
    horizon = horizon or _two_link_layer()
    return corridor_vmt(CORRIDOR, COORDS, MATCHES, base, horizon,
                        existing, future, refinement or [], Period.AM, **kw)


# ── A. Length in miles, chain traced (not incident-only, not degrees/feet) ────
def test_length_is_miles_chain_summed():
    out = _run()
    c = out["corridor"]
    assert c["corridor_length_mi"] == pytest.approx(1.0)        # 0.5 + 0.5, both chain links
    assert out["links"][0]["chain_link_ids"] == ["L1", "L2"]    # traced, not incident-only
    assert c["unit"] == "veh-mi"


# ── B(peak). Peak-hour VMT — always clean ─────────────────────────────────────
def test_peak_hour_vmt_existing_future_delta():
    c = _run()["corridor"]
    assert c["basis"] == "peak_hour"
    assert c["existing_vmt"] == pytest.approx(1800.0)           # (1000+800) × 1.0
    assert c["future_vmt"] == pytest.approx(2700.0)             # (1500+1200) × 1.0
    assert c["delta"] == pytest.approx(900.0)


# ── B(daily a). Daily from data — count-anchored ratio, NO asterisk ───────────
def test_daily_from_data_no_asterisk():
    # ratio = Σtotal_flow / Σ(ab_am+ba_am) = 20000 / 4000 = 5.0
    c = _run()["corridor"]
    assert c["daily_existing_vmt"] == pytest.approx(9000.0)     # 1800 × 5
    assert c["daily_future_vmt"] == pytest.approx(13500.0)      # 2700 × 5
    assert c["daily_estimated"] is False
    assert c["expansion_factor"] is None


# ── B(daily b). Engineer factor fallback — asterisk set ───────────────────────
def test_daily_from_factor_sets_asterisk():
    # No period flow in the model → no data-derived ratio; factor supplied.
    flat = _two_link_layer(total_flow=0, ab_am=0, ba_am=0)
    c = _run(base=flat, horizon=flat, expansion_factor=0.1)["corridor"]
    assert c["daily_estimated"] is True
    assert c["expansion_factor"] == 0.1
    assert c["daily_existing_vmt"] == pytest.approx(180.0)      # 1800 × 0.1


# ── B(daily c). No daily data, no factor → omitted (peak still clean) ─────────
def test_daily_omitted_when_no_data_no_factor():
    flat = _two_link_layer(total_flow=0, ab_am=0, ba_am=0)
    c = _run(base=flat, horizon=flat)["corridor"]
    assert c["daily_existing_vmt"] is None
    assert c["daily_estimated"] is False
    assert c["existing_vmt"] == pytest.approx(1800.0)           # peak-hour unaffected


# ── C. Gap rule — hold-flat-and-flag ──────────────────────────────────────────
def test_gap_flag_from_held_refinement():
    refinement = [{"intersection_num": 1,
                   "approaches": {"NB": {"status": "pending"},
                                  "SB": {"status": "bound",
                                         "inbound": {"status": "refined"},
                                         "outbound": {"status": "refined"}}}}]
    assert _run(refinement=refinement)["corridor"]["gap_flag"] is True


def test_gap_flag_from_untraceable_chain():
    # snapped node 200 isn't in this single-link layer → chain untraceable.
    broken = _layer([_nl("X", 100, 999, len_mile=0.5, total_flow=0, ab_am=0, ba_am=0)])
    out = _run(base=broken, horizon=broken)
    assert out["corridor"]["gap_flag"] is True
    assert out["links"][0]["held"] is True


def test_no_gap_when_clean():
    assert _run()["corridor"]["gap_flag"] is False


# ── Per-link segment volumes (additive — fed to the Excel per-link breakdown) ──
def test_links_carry_segment_volumes():
    lk = _run()["links"][0]
    # EB outflow 1000 + WB approach 800 = 1800 existing; ×1.5 = 2700 future.
    assert lk["existing_vol"] == pytest.approx(1800.0)
    assert lk["future_vol"] == pytest.approx(2700.0)
    # vol × length(1.0 mi) reconciles with the VMT fields (no double-count).
    assert lk["existing_vmt"] == pytest.approx(lk["existing_vol"] * lk["length_mi"])
    assert lk["future_vmt"] == pytest.approx(lk["future_vol"] * lk["length_mi"])


# ── Network rollup (link → corridor → network) ────────────────────────────────
def test_network_rollup_equals_corridor():
    out = _run()
    assert out["network"]["existing_vmt"] == out["corridor"]["existing_vmt"]
    assert out["network"]["future_vmt"] == out["corridor"]["future_vmt"]
    assert out["corridor"]["link_count"] == 1


# ── Integration: real SANDAG pipeline (gated) ─────────────────────────────────
from pathlib import Path  # noqa: E402

REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"
_ALL12 = ["NBL", "NBT", "NBR", "SBL", "SBT", "SBR", "EBL", "EBT", "EBR", "WBL", "WBT", "WBR"]


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_vmt_smoke():
    # Single intersection (no corridor segments) — VMT machinery runs cleanly and
    # returns a zero-length, zero-VMT corridor without error on real data.
    from forecasting.adapters.sandag import ingest_sandag
    from forecasting.matcher import match_network_to_legs
    lat, lng = 32.624067, -116.959736
    layer = ingest_sandag(REAL_SHP, 2025, [{"num": 1, "lat": lat, "lng": lng}])
    mr = match_network_to_legs([{"num": 1, "lat": lat, "lng": lng}], layer)
    counts = {1: {m: 100 for m in _ALL12}}
    out = corridor_vmt([], {1: {"lat": lat, "lng": lng}}, mr, layer, layer,
                       counts, counts, [], Period.AM)
    assert out["corridor"]["existing_vmt"] == 0.0   # no segments → no through-link VMT
    assert out["corridor"]["link_count"] == 0
