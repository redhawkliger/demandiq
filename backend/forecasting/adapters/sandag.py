"""
DemandIQ Forecasting — SANDAG region adapter.

Transforms a SANDAG loaded-highway shapefile (hwyLoad.shp, EPSG:2230, ~40,720
directional links, 96 attributes) into a canonical NetworkLayer in the project
map CRS (EPSG:4326).

Faithful transformer. Every source link that survives the spatial filter is
emitted, unchanged in meaning. We do NOT drop Zone Connectors or any class here
— the 300 ft spatial filter removes most naturally, and the matcher
deprioritizes Connector class against real approaches. Faithfulness over
cleverness at this layer.

Geo dependencies (geopandas/pyogrio/shapely/pyproj) are imported INSIDE
ingest_sandag, never at module load, so importing this module costs the lean app
nothing. They live in requirements-forecasting.txt, not requirements.txt.

CRS handling (locked):
  - Project intersections arrive in EPSG:4326 ({lat, lng} decimal degrees).
  - Reproject project points 4326 → source CRS (2230, feet) for the filter —
    "300 ft" is only meaningful in feet.
  - Keep links whose endpoint lies within filter_radius_ft of any project point.
  - Reproject surviving links + node coords source → 4326 for output.
  - The returned NetworkLayer carries crs_epsg=4326, source_crs_epsg=2230.

Coordinate order: Coord is (x, y). In EPSG:4326 that is (lng, lat) per the
shapely/GeoJSON convention — NOT (lat, lng). The matcher adapts.
"""

from forecasting.contract import (
    DirectionalFlow,
    NetworkLayer,
    NetworkLink,
    Period,
)
from forecasting.geo import polyline_length_mi

# ── SANDAG field map — verified against the real hwyLoad.shp (40,720 records). ─
# The ONE schema-coupled place in the module. If a future SANDAG vintage renames
# columns, this is what changes; nothing downstream re-derives field names.
COL_LINK_ID = "hwycov_id"
COL_FROM_NODE = "from_node"
COL_TO_NODE = "to_node"
COL_NAME = "link_name"
COL_FC = "fc_desc"
COL_AB_AM_LANE = "ab_am_lane"
COL_BA_AM_LANE = "ba_am_lane"
COL_LEN_MILE = "len_mile"     # model-native link length, miles
COL_TOTAL_FLOW = "total_flow" # daily total volume (both dirs, all periods)

# Period → (AB column, BA column). SANDAG pattern: {ab|ba}_{period}_flow.
FLOW_COLS = {
    Period.EA: ("ab_ea_flow", "ba_ea_flow"),
    Period.AM: ("ab_am_flow", "ba_am_flow"),
    Period.MD: ("ab_md_flow", "ba_md_flow"),
    Period.PM: ("ab_pm_flow", "ba_pm_flow"),
    Period.EV: ("ab_ev_flow", "ba_ev_flow"),
}

# fc_desc → canonical functional_class. Anything unmapped → "Other".
SANDAG_FC_MAP = {
    "Freeway":                              "Freeway",
    "Freeway Connector Ramp":               "Ramp",
    "Local Ramp":                           "Ramp",
    "Major Arterial":                       "Major Arterial",
    "Prime Arterial":                       "Prime Arterial",
    "Collector":                            "Collector",
    "Local Collector":                      "Collector",
    "Rural Collector":                      "Collector",
    "Local (non-circulation element) Road": "Local",
    "Zone Connector":                       "Connector",
}

DEFAULT_SOURCE_EPSG = 2230   # State Plane CA Zone VI, US feet — SANDAG network CRS
PROJECT_EPSG = 4326          # WGS84 lat/lng — DemandIQ project map CRS


# ── Scalar coercion helpers — numpy/pandas → plain Python ─────────────────────
def _py(v):
    """Coerce a numpy/pandas scalar to a plain Python scalar; NaN/NA → None."""
    import math
    if v is None:
        return None
    if hasattr(v, "item"):           # numpy scalar → python scalar
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _int_or(v, default=0):
    """Cast to int (source ids/nodes/lanes are floats in SANDAG); NaN/None →
    default."""
    pv = _py(v)
    return default if pv is None else int(pv)


def _float0(v):
    """Cast to float; NaN/None → 0.0 (SANDAG flows use 0 for no flow)."""
    pv = _py(v)
    return 0.0 if pv is None else float(pv)


def _coords_list(geom):
    """Full vertex list of a link geometry as [(x, y), ...]."""
    t = geom.geom_type
    if t == "LineString":
        return list(geom.coords)
    if t == "MultiLineString":
        out = []
        for part in geom.geoms:
            out.extend(part.coords)
        return out
    raise ValueError(f"unexpected link geometry type: {t}")


def _endpoints(geom):
    """First and last vertex of a link geometry, as (x, y) tuples.
    SANDAG digitizes from_node → to_node, so coords[0] is the from_node end."""
    cs = _coords_list(geom)
    return cs[0], cs[-1]


def ingest_sandag(
    shp_path,
    scenario_year,
    project_intersections_4326,
    *,
    filter_radius_ft=300,
):
    """Ingest a SANDAG loaded-highway shapefile into a canonical NetworkLayer.

    Args:
        shp_path: path to hwyLoad.shp (siblings .dbf/.shx/.prj/.cpg alongside).
        scenario_year: engineer-supplied model year for this network (e.g. 2025,
            2030). Stamped on the layer; base/horizon are two separate calls.
        project_intersections_4326: iterable of mappings carrying 'lat' and 'lng'
            (decimal degrees, EPSG:4326) — the project intersections to scope the
            network around. Extra keys (num, name, ...) are ignored.
        filter_radius_ft: keep links with an endpoint within this many feet of
            any project intersection. Default 300.

    Returns:
        NetworkLayer(region='SANDAG', source_crs_epsg=2230, crs_epsg=4326,
                     scenario_year=..., links=[...]) in EPSG:4326.

    Raises:
        ValueError: if no project intersections carry lat/lng, or if zero links
            survive the spatial filter — fail loud, never return an empty
            network silently.
    """
    # Lazy geo imports — importing this module must cost the lean app nothing.
    import geopandas as gpd
    from shapely.geometry import Point

    pts = [
        (float(p["lng"]), float(p["lat"]))
        for p in project_intersections_4326
        if p.get("lat") is not None and p.get("lng") is not None
    ]
    if not pts:
        raise ValueError(
            "ingest_sandag: no project intersections with lat/lng provided — "
            "cannot scope the network."
        )

    gdf = gpd.read_file(shp_path)
    source_epsg = gdf.crs.to_epsg() if gdf.crs else None
    if source_epsg is None:
        source_epsg = DEFAULT_SOURCE_EPSG
        gdf = gdf.set_crs(DEFAULT_SOURCE_EPSG)

    # Project points → source CRS (feet) so the radius is measured in real feet.
    proj_pts = gpd.GeoDataFrame(
        geometry=[Point(lng, lat) for (lng, lat) in pts],
        crs=PROJECT_EPSG,
    ).to_crs(gdf.crs)

    # Two-points-per-link endpoint frame in the source CRS, tagged with the
    # link's row index. Keep links with an endpoint within the radius of a point.
    link_idx = []
    ep_geoms = []
    for idx, geom in zip(gdf.index, gdf.geometry):
        a, b = _endpoints(geom)
        link_idx.append(idx); ep_geoms.append(Point(a))
        link_idx.append(idx); ep_geoms.append(Point(b))
    endpoints = gpd.GeoDataFrame({"link_idx": link_idx}, geometry=ep_geoms, crs=gdf.crs)

    matched = gpd.sjoin_nearest(
        endpoints, proj_pts, max_distance=filter_radius_ft, how="inner"
    )
    keep = sorted(set(matched["link_idx"]))
    if not keep:
        raise ValueError(
            f"ingest_sandag: zero SANDAG links within {filter_radius_ft} ft of any "
            f"of the {len(pts)} project intersection(s). Check the network covers "
            "the project area and that intersection coords are EPSG:4326."
        )

    # Reproject only the survivors to the project CRS for output coords.
    filtered = gdf.loc[keep].to_crs(PROJECT_EPSG)
    attr_cols = [c for c in filtered.columns if c != filtered.geometry.name]

    links = []
    for _, row in filtered.iterrows():
        coords = [(float(x), float(y)) for (x, y) in _coords_list(row.geometry)]
        name = _py(row.get(COL_NAME))
        # Canonical length: model-native len_mile when positive, else great-circle
        # from the (already reprojected, 4326) geometry. The engine reads this, not
        # the raw SANDAG column.
        len_native = _float0(row.get(COL_LEN_MILE))
        length_mi = len_native if len_native > 0 else polyline_length_mi(coords)
        links.append(NetworkLink(
            link_id=str(_int_or(row[COL_LINK_ID])),
            from_node=_int_or(row[COL_FROM_NODE]),
            to_node=_int_or(row[COL_TO_NODE]),
            geometry=coords,
            from_node_xy=coords[0],
            to_node_xy=coords[-1],
            length_mi=length_mi,
            name=str(name) if name is not None else None,
            functional_class=SANDAG_FC_MAP.get(_py(row.get(COL_FC)), "Other"),
            lanes=max(_int_or(row.get(COL_AB_AM_LANE)), _int_or(row.get(COL_BA_AM_LANE))),
            flow=DirectionalFlow(
                ab={p: _float0(row[ab]) for p, (ab, ba) in FLOW_COLS.items()},
                ba={p: _float0(row[ba]) for p, (ab, ba) in FLOW_COLS.items()},
            ),
            daily_total=_float0(row.get(COL_TOTAL_FLOW)),
            source_attributes={c: _py(row[c]) for c in attr_cols},
        ))

    return NetworkLayer(
        region="SANDAG",
        source_crs_epsg=source_epsg,
        crs_epsg=PROJECT_EPSG,
        scenario_year=int(scenario_year),
        links=links,
    )
