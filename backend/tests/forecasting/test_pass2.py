"""Tests for Pass 2 — the corridor balancer (module 7).

Pass 2 is pure reuse of balancer.balance_nchrp (already exhaustively tested in
test_balancer_nchrp / test_e2e_bodger). These tests verify the glue: link
validation, both-period threading, and that Pass-1 futures come out conserved
and rounded.

Run from backend/ with the forecasting venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting/test_pass2.py -v
"""

from pathlib import Path

import pytest

from forecasting.pass2 import balance_future, balance_future_corridor

_ALL12 = ["NBL", "NBT", "NBR", "SBL", "SBT", "SBR",
          "EBL", "EBT", "EBR", "WBL", "WBT", "WBR"]


def _mv(**ov):
    d = {m: 0.0 for m in _ALL12}
    d.update(ov)
    return d


# Two intersections on an EB/WB corridor; EB through movements deliberately
# disagree (1003 vs 998) so Pass 2 has something to conserve.
def _two_int_futures():
    return {
        1: _mv(NBL=100, NBT=500, NBR=50, SBL=80, SBT=480, SBR=40,
               EBL=60, EBT=1003, EBR=30, WBL=70, WBT=320, WBR=35),
        2: _mv(NBL=90, NBT=460, NBR=45, SBL=75, SBT=470, SBR=35,
               EBL=55, EBT=998, EBR=25, WBL=65, WBT=310, WBR=30),
    }


_LINKS = [{"fromNum": 1, "toNum": 2, "direction": "EB/WB", "mode": "Full"}]
_COORDS = {1: {"lat": 32.720, "lng": -117.160},     # 1 is west of 2
           2: {"lat": 32.720, "lng": -117.150}}


# ── Conservation + rounding ───────────────────────────────────────────────────
def test_pass2_conserves_and_rounds():
    res = balance_future(_two_int_futures(), _LINKS, coords=_COORDS)
    balanced = res["balanced"]
    assert set(balanced) == {1, 2}
    # Every balanced movement is a multiple of 5.
    for vols in balanced.values():
        for v in vols.values():
            assert v % 5 == 0, f"{v} not a multiple of 5"
    # Every Full link conserves exactly (delta == 0) after reconciliation.
    full = [c for c in res["link_conservation"] if c["mode"] == "Full"]
    assert full, "expected at least one Full link"
    assert all(c["delta"] == 0 for c in full)


# ── Link validation (fail loud) ───────────────────────────────────────────────
def test_pass2_rejects_bad_direction():
    bad = [{"fromNum": 1, "toNum": 2, "direction": "NB", "mode": "Full"}]
    with pytest.raises(ValueError, match="invalid direction"):
        balance_future(_two_int_futures(), bad, coords=_COORDS)


# ── mode='None' link is skipped (Q3 off-network exclusion) ────────────────────
def test_pass2_none_mode_link_not_conserved():
    links = [{"fromNum": 1, "toNum": 2, "direction": "EB/WB", "mode": "None"}]
    res = balance_future(_two_int_futures(), links, coords=_COORDS)
    full = [c for c in res["link_conservation"] if c["mode"] == "Full"]
    assert not full          # the only link is mode='None' → nothing forced to conserve


# ── Both periods threaded ─────────────────────────────────────────────────────
def test_pass2_both_periods():
    am = _two_int_futures()
    pm = _two_int_futures()
    pm[1]["EBT"] = 1200          # make PM differ
    out = balance_future_corridor({"AM": am, "PM": pm}, _LINKS, coords=_COORDS)
    assert set(out) == {"AM", "PM"}
    assert set(out["AM"]["balanced"]) == {1, 2}
    assert out["AM"]["method"] == "larger"


# ── Integration: full pipeline ingest → match → refine → Pass 1 → Pass 2 ──────
REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_full_pipeline():
    from forecasting.adapters.sandag import ingest_sandag
    from forecasting.matcher import match_network_to_legs
    from forecasting.refinement import refine_corridor
    from forecasting.pass1 import forecast_corridor
    from forecasting.contract import Period

    lat, lng = 32.624067, -116.959736                  # DISCOVERY FALLS node
    counts = {1: {m: 100 for m in _ALL12}}
    layer = ingest_sandag(REAL_SHP, 2025, [{"num": 1, "lat": lat, "lng": lng}])
    mr = match_network_to_legs([{"num": 1, "lat": lat, "lng": lng}], layer)
    rr = refine_corridor(mr, layer, layer, counts, Period.AM)        # identity growth
    futures, _ = forecast_corridor(rr, counts)

    # Single intersection → no corridor links; Pass 2 still balances + rounds.
    res = balance_future(futures, [], coords={1: {"lat": lat, "lng": lng}})
    assert 1 in res["balanced"]
    for v in res["balanced"][1].values():
        assert v % 5 == 0


def _build_2030_from_real(dst_dir, growth):
    """Derive a synthetic horizon network from the real base file: same geometry
    and link_ids, every period flow scaled by `growth`. Lets the full pipeline
    run on REAL geometry with non-identity growth (we have no real 2030 file)."""
    import geopandas as gpd
    d = gpd.read_file(REAL_SHP)
    for c in [c for c in d.columns if c.endswith("_flow")]:
        d[c] = d[c] * growth
    path = dst_dir / "hwyLoad_2030.shp"
    d.to_file(path)
    return path


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_growth_full_pipeline(tmp_path):
    from forecasting.ingest import ingest_networks
    from forecasting.matcher import match_network_to_legs
    from forecasting.refinement import refine_corridor
    from forecasting.pass1 import forecast_corridor
    from forecasting.contract import Period

    GROWTH = 1.25
    horizon = _build_2030_from_real(tmp_path, GROWTH)
    lat, lng = 32.624067, -116.959736                      # DISCOVERY FALLS node
    pts = [{"num": 1, "lat": lat, "lng": lng}]

    layers = ingest_networks(pts, [
        {"role": "base", "scenario_year": 2025, "path": str(REAL_SHP)},
        {"role": "horizon", "scenario_year": 2030, "path": str(horizon)},
    ])
    mr = match_network_to_legs(pts, layers["base"])
    counts = {1: {m: 100 for m in _ALL12}}
    rr = refine_corridor(mr, layers["base"], layers["horizon"], counts, Period.AM)

    # Uniform ×1.25 scaling → every bound leg's model growth factor is ~1.25
    # (and refined inbound ~125 = count × growth), proving real growth — not
    # identity — flows through refinement.
    [r] = rr
    bound = [d for d in ("NB", "SB", "EB", "WB") if r["approaches"][d]["status"] == "bound"]
    assert bound, "expected at least one bound leg on the real node"
    grew = False
    for d in bound:
        gf = r["approaches"][d]["inbound"].get("growth_factor")
        if gf is not None:                                  # None = held-flat (Mb=0)
            sub = r["approaches"][d]["inbound"]
            assert gf == pytest.approx(GROWTH, abs=0.01)
            # refined = approach-total count (L+T+R) × growth.
            assert sub["refined"] == pytest.approx(sub["count_base"] * GROWTH, abs=1.0)
            grew = True
    assert grew, "expected at least one leg with a real (non-zero) model base"

    # Full pipeline → future TMCs exceed the flat base count of 100.
    futures, _ = forecast_corridor(rr, counts)
    res = balance_future(futures, [], coords={1: {"lat": lat, "lng": lng}})
    assert max(res["balanced"][1].values()) > 100
