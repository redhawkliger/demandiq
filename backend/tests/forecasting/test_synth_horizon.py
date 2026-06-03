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
