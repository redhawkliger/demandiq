"""Synthetic SANDAG fixtures for the adapter unit tests.

Builds an in-memory GeoDataFrame that mirrors the real hwyLoad.shp schema
(lowercase column names, EPSG:2230 feet) with representative rows, writes it to
a temp shapefile, and supplies project intersections (EPSG:4326) positioned so
the spatial filter has something to keep and something to drop.

Coordinates are anchored to a real San Diego lat/lng transformed into EPSG:2230,
so the 4326→2230→4326 round-trip the adapter performs is exercised end to end.
"""

import pytest

# Project anchor — downtown San Diego. The near-cluster nodes are small foot
# offsets from this point's EPSG:2230 projection.
ANCHOR_LNG, ANCHOR_LAT = -117.161, 32.715


@pytest.fixture
def anchor_2230():
    """Anchor lat/lng projected to EPSG:2230 (easting, northing) in feet."""
    from pyproj import Transformer
    t = Transformer.from_crs(4326, 2230, always_xy=True)
    return t.transform(ANCHOR_LNG, ANCHOR_LAT)   # (easting, northing)


@pytest.fixture
def synthetic_sandag_gdf(anchor_2230):
    """A 7-row GeoDataFrame mirroring the SANDAG schema in EPSG:2230.

    Rows 1-6 are the representative classes (near the anchor, all kept by a
    300 ft filter); row 7 sits ~20,000 ft away as the spatial-filter control.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    e, n = anchor_2230
    # Near cluster — all endpoints within ~180 ft of the anchor.
    N1 = (e, n)
    N2 = (e + 100.0, n)
    N3 = (e + 150.0, n)
    N5 = (e + 100.0, n + 100.0)
    # Far cluster — ~20,000 ft east (well outside any sane filter radius).
    NF1 = (e + 20000.0, n)
    NF2 = (e + 20100.0, n)

    rows = [
        # 1. Freeway, bidirectional.
        dict(hwycov_id=58, from_node=11014, to_node=11419, link_name="I-805 NB",
             fc_desc="Freeway", ab_am_lane=4, ba_am_lane=4, post_speed=65,
             ab=dict(EA=800, AM=2451.47, MD=1500, PM=3000, EV=1200),
             ba=dict(EA=700, AM=2100, MD=1400, PM=2800, EV=1100),
             geometry=LineString([N1, N2])),
        # 2. Major Arterial.
        dict(hwycov_id=101, from_node=200, to_node=201, link_name="El Camino Real",
             fc_desc="Major Arterial", ab_am_lane=3, ba_am_lane=3, post_speed=45,
             ab=dict(EA=300, AM=900, MD=700, PM=1100, EV=500),
             ba=dict(EA=280, AM=850, MD=680, PM=1050, EV=480),
             geometry=LineString([N2, N3])),
        # 3. Collector (Local Collector → Collector).
        dict(hwycov_id=102, from_node=201, to_node=202, link_name="Oakwood Dr",
             fc_desc="Local Collector", ab_am_lane=2, ba_am_lane=2, post_speed=30,
             ab=dict(EA=100, AM=300, MD=250, PM=350, EV=150),
             ba=dict(EA=90, AM=280, MD=240, PM=330, EV=140),
             geometry=LineString([N3, N5])),
        # 4. Zone Connector — adapter must NOT drop it (faithful passthrough).
        dict(hwycov_id=900, from_node=11014, to_node=202, link_name="",
             fc_desc="Zone Connector", ab_am_lane=1, ba_am_lane=1, post_speed=15,
             ab=dict(EA=50, AM=120, MD=80, PM=140, EV=60),
             ba=dict(EA=45, AM=110, MD=75, PM=130, EV=55),
             geometry=LineString([N1, N5])),
        # 5. HOV-directional — all flow AB, BA = 0.
        dict(hwycov_id=59, from_node=11419, to_node=11014, link_name="I-805 HOV NB",
             fc_desc="Freeway", ab_am_lane=1, ba_am_lane=0, post_speed=70,
             ab=dict(EA=900, AM=2451.47, MD=5555.55, PM=5089.05, EV=800),
             ba=dict(EA=0, AM=0, MD=0, PM=0, EV=0),
             geometry=LineString([N2, N1])),
        # 6. All-zero flows (Local road) — still ingested when near.
        dict(hwycov_id=103, from_node=202, to_node=201, link_name="Stub Ct",
             fc_desc="Local (non-circulation element) Road",
             ab_am_lane=1, ba_am_lane=1, post_speed=25,
             ab=dict(EA=0, AM=0, MD=0, PM=0, EV=0),
             ba=dict(EA=0, AM=0, MD=0, PM=0, EV=0),
             geometry=LineString([N5, N3])),
        # 7. FAR link (~20,000 ft) — spatial-filter / fail-loud control.
        dict(hwycov_id=500, from_node=70000, to_node=70001, link_name="Far Rd",
             fc_desc="Collector", ab_am_lane=2, ba_am_lane=2, post_speed=40,
             ab=dict(EA=10, AM=20, MD=15, PM=25, EV=12),
             ba=dict(EA=10, AM=20, MD=15, PM=25, EV=12),
             geometry=LineString([NF1, NF2])),
    ]

    records = []
    for r in rows:
        ab = r.pop("ab")
        ba = r.pop("ba")
        rec = dict(r)
        for per in ("ea", "am", "md", "pm", "ev"):
            rec[f"ab_{per}_flow"] = float(ab[per.upper()])
            rec[f"ba_{per}_flow"] = float(ba[per.upper()])
        rec["total_flow"] = float(sum(ab.values()) + sum(ba.values()))
        rec["vmt"] = rec["total_flow"] * 0.1
        records.append(rec)

    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:2230")


@pytest.fixture
def synthetic_sandag_shp(tmp_path, synthetic_sandag_gdf):
    """Write the synthetic network to a temp hwyLoad.shp; return its path."""
    path = tmp_path / "hwyLoad.shp"
    synthetic_sandag_gdf.to_file(path)   # pyogrio writes .shp/.dbf/.shx/.prj/.cpg
    return path


@pytest.fixture
def project_points_near():
    """One project intersection at the anchor — its 300 ft radius covers the
    whole near cluster (rows 1-6) but not the far link (row 7)."""
    return [{"num": 1, "lat": ANCHOR_LAT, "lng": ANCHOR_LNG}]


@pytest.fixture
def project_points_off_network():
    """A project intersection nowhere near the network (Kansas) — every link is
    outside the filter radius, so the adapter must fail loud."""
    return [{"num": 1, "lat": 39.0, "lng": -98.5}]


@pytest.fixture
def synthetic_sandag_shp_horizon(tmp_path, synthetic_sandag_gdf):
    """A horizon-year network: same link_ids + geometry as the base fixture,
    flows grown ~30% to simulate 2030 growth. Written to a distinct filename so
    base + horizon can coexist in one test's tmp dir."""
    gdf = synthetic_sandag_gdf.copy()
    for c in [c for c in gdf.columns if c.endswith("_flow")]:
        gdf[c] = gdf[c] * 1.3
    path = tmp_path / "hwyLoad_2030.shp"
    gdf.to_file(path)
    return path


@pytest.fixture
def synthetic_sandag_shp_disjoint(tmp_path, synthetic_sandag_gdf):
    """Same geometry/area as the base fixture (so the spatial filter still keeps
    the near cluster) but a disjoint link_id space — drives the base↔horizon
    overlap check to 0%."""
    gdf = synthetic_sandag_gdf.copy()
    gdf["hwycov_id"] = gdf["hwycov_id"] + 100000
    path = tmp_path / "hwyLoad_disjoint.shp"
    gdf.to_file(path)
    return path
