"""Unit tests for the SANDAG adapter against a synthetic fixture, plus one
integration test gated on the real hwyLoad.shp being present locally.

Run from backend/ with the forecasting venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting -v
"""

from pathlib import Path

import pytest

from forecasting.adapters.sandag import ingest_sandag, SANDAG_FC_MAP
from forecasting.contract import NetworkLayer, Period


def _by_id(layer):
    return {l.link_id: l for l in layer.links}


# ── Layer envelope & spatial filter ───────────────────────────────────────────
def test_returns_networklayer_in_4326(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    assert isinstance(layer, NetworkLayer)
    assert layer.region == "SANDAG"
    assert layer.crs_epsg == 4326
    assert layer.source_crs_epsg == 2230
    assert layer.scenario_year == 2030
    # 6 near links kept, the far link dropped.
    assert len(layer.links) == 6


def test_filter_drops_far_link(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    assert "500" not in _by_id(layer)   # the ~20,000 ft control link


def test_fail_loud_when_zero_survivors(synthetic_sandag_shp, project_points_off_network):
    with pytest.raises(ValueError, match="zero SANDAG links"):
        ingest_sandag(synthetic_sandag_shp, 2030, project_points_off_network)


def test_fail_loud_when_no_project_points(synthetic_sandag_shp):
    with pytest.raises(ValueError, match="no project intersections"):
        ingest_sandag(synthetic_sandag_shp, 2030, [])


# ── Field mapping ─────────────────────────────────────────────────────────────
def test_field_mapping_freeway(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    lk = _by_id(layer)["58"]
    assert lk.from_node == 11014
    assert lk.to_node == 11419
    assert lk.name == "I-805 NB"
    assert lk.functional_class == "Freeway"
    assert lk.lanes == 4
    assert lk.flow.ab[Period.AM] == pytest.approx(2451.47)
    assert lk.flow.ba[Period.AM] == pytest.approx(2100.0)
    assert lk.flow.ab[Period.PM] == pytest.approx(3000.0)


def test_link_id_is_string(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    assert all(isinstance(l.link_id, str) for l in layer.links)


def test_lanes_is_am_max(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    # HOV link: max(ab_am_lane=1, ba_am_lane=0) == 1.
    assert _by_id(layer)["59"].lanes == 1


# ── Functional-class normalization ────────────────────────────────────────────
def test_fc_normalization(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    by = _by_id(layer)
    assert by["102"].functional_class == "Collector"   # Local Collector → Collector
    assert by["900"].functional_class == "Connector"   # Zone Connector → Connector
    assert by["103"].functional_class == "Local"
    assert by["101"].functional_class == "Major Arterial"


def test_fc_map_covers_verified_classes():
    # The verified SANDAG fc_desc set collapses to these canonical classes.
    assert SANDAG_FC_MAP["Freeway Connector Ramp"] == "Ramp"
    assert SANDAG_FC_MAP["Local Ramp"] == "Ramp"
    assert SANDAG_FC_MAP["Rural Collector"] == "Collector"
    assert SANDAG_FC_MAP["Prime Arterial"] == "Prime Arterial"


def test_unmapped_fc_maps_to_other(tmp_path, anchor_2230, project_points_near):
    # A class not in SANDAG_FC_MAP must normalize to "Other".
    import geopandas as gpd
    from shapely.geometry import LineString
    e, n = anchor_2230
    rec = {"hwycov_id": 7, "from_node": 1, "to_node": 2, "link_name": "Trail",
           "fc_desc": "Bike Path", "ab_am_lane": 0, "ba_am_lane": 0}
    for per in ("ea", "am", "md", "pm", "ev"):
        rec[f"ab_{per}_flow"] = 0.0
        rec[f"ba_{per}_flow"] = 0.0
    rec["geometry"] = LineString([(e, n), (e + 50.0, n)])
    gdf = gpd.GeoDataFrame([rec], geometry="geometry", crs="EPSG:2230")
    path = tmp_path / "hwyLoad.shp"
    gdf.to_file(path)

    layer = ingest_sandag(path, 2030, project_points_near)
    assert layer.links[0].functional_class == "Other"


# ── Flows ─────────────────────────────────────────────────────────────────────
def test_hov_directional_ba_all_zero(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    lk = _by_id(layer)["59"]
    assert lk.flow.ab[Period.MD] == pytest.approx(5555.55)
    assert lk.flow.ab[Period.PM] == pytest.approx(5089.05)
    assert all(v == 0 for v in lk.flow.ba.values())


def test_all_zero_flow_link_still_ingested(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    lk = _by_id(layer)["103"]
    assert all(v == 0 for v in lk.flow.ab.values())
    assert all(v == 0 for v in lk.flow.ba.values())


def test_all_five_periods_present(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    lk = _by_id(layer)["58"]
    assert set(lk.flow.ab) == set(Period)
    assert set(lk.flow.ba) == set(Period)


# ── AB/BA inbound read (contract method, through adapter output) ───────────────
def test_inbound_read_follows_ab_ba_convention(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    lk = _by_id(layer)["58"]          # from_node 11014 → to_node 11419
    assert lk.inbound_to(11419) == lk.flow.ab    # inbound to head = AB
    assert lk.inbound_to(11014) == lk.flow.ba    # inbound to tail = BA


# ── Provenance & geometry ─────────────────────────────────────────────────────
def test_source_attributes_passthrough(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    sa = _by_id(layer)["58"].source_attributes
    # Extra (non-canonical) columns survive...
    assert "post_speed" in sa
    assert "total_flow" in sa
    assert "vmt" in sa
    # ...as do the mapped source columns, and geometry is excluded.
    assert sa["from_node"] == 11014
    assert sa["fc_desc"] == "Freeway"
    assert "geometry" not in sa


def test_geometry_reprojected_to_4326(synthetic_sandag_shp, project_points_near):
    layer = ingest_sandag(synthetic_sandag_shp, 2030, project_points_near)
    lk = _by_id(layer)["58"]
    lng, lat = lk.from_node_xy
    assert -118.0 < lng < -116.0       # San Diego longitude (Coord is (lng, lat))
    assert 32.0 < lat < 33.0
    assert len(lk.geometry) >= 2
    assert lk.geometry[0] == lk.from_node_xy
    assert lk.geometry[-1] == lk.to_node_xy


# ── Integration: real SANDAG file (skipped when absent, e.g. on Render/CI) ─────
REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_sandag_ingest():
    # A verified real network node (a Major Arterial endpoint, "DISCOVERY FALLS")
    # so the 300 ft filter is guaranteed to find the links sharing that node.
    pts = [{"num": 1, "lat": 32.624067, "lng": -116.959736}]
    layer = ingest_sandag(REAL_SHP, 2025, pts, filter_radius_ft=300)
    assert layer.region == "SANDAG"
    assert layer.crs_epsg == 4326
    assert layer.source_crs_epsg == 2230
    assert len(layer.links) > 0
    valid_classes = {"Freeway", "Ramp", "Major Arterial", "Prime Arterial",
                     "Collector", "Local", "Connector", "Other"}
    for l in layer.links:
        assert l.functional_class in valid_classes
        assert l.inbound_to(l.to_node) == l.flow.ab
        assert set(l.flow.ab) == set(Period)
