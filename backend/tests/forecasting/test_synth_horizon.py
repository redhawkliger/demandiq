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
    # Use a single-link subset of the base network to avoid the ambiguity that
    # arises when links 58 and 59 (both Freeway, both bearing ~90° from node
    # 11014) contest the WB slot. The per-class scaling itself is proven in (a);
    # here we only need refinement to bind one leg so we can check growth_factor.
    freeway_link = synthetic_sandag_gdf[synthetic_sandag_gdf["hwycov_id"] == 58]
    freeway_hor  = synthesize_horizon_gdf(freeway_link)
    fwy_base_shp = tmp_path / "fwy_base.shp"
    fwy_hor_shp  = tmp_path / "fwy_hor.shp"
    freeway_link.to_file(fwy_base_shp)
    freeway_hor.to_file(fwy_hor_shp)
    layers_fwy = ingest_networks(pts, [
        {"role": "base",    "scenario_year": 2025, "path": str(fwy_base_shp)},
        {"role": "horizon", "scenario_year": 2030, "path": str(fwy_hor_shp)},
    ])
    mr = match_network_to_legs(pts, layers_fwy["base"])
    counts = {n: {m: 100 for m in _ALL12}}
    rr = refine_corridor(mr, layers_fwy["base"], layers_fwy["horizon"], counts, Period.AM)
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
                       layers_fwy["base"], layers_fwy["horizon"], counts, res["balanced"], rr, Period.AM)
    assert vmt["unit"] == "veh-mi"

    # (e) An extreme class factor (> 4x) trips REFINE-GROWTH-OUTLIER.
    extreme_shp = tmp_path / "hwyLoad_2030_extreme.shp"
    synthesize_horizon_shp(str(fwy_base_shp), str(extreme_shp), factors=dict(FACTORS, Freeway=5.0))
    layers_x = ingest_networks(pts, [
        {"role": "base",    "scenario_year": 2025, "path": str(fwy_base_shp)},
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
