"""
DemandIQ Forecasting — synthetic horizon-network generator (readiness tool).

Derives an EXPLICITLY SYNTHETIC horizon-year SANDAG network from a real base
loaded-highway shapefile by scaling each link's volumes by a per-functional-class
growth factor. Lets the NCHRP-765 pipeline be validated on real, DIFFERENTIAL
(non-identity) growth while no real 2030 network is available, and makes the real
2030 network a one-file swap (drop it in, point F1 at it).

NOT a SANDAG projection. FACTORS are illustrative readiness values chosen to
exercise differential refinement — replace with a real horizon network when one
arrives. Schema (SANDAG_FC_MAP, FLOW_COLS) is reused from adapters.sandag; this
tool is SANDAG-schema-coupled by design. Geo deps are imported lazily inside
synthesize_horizon_shp only; synthesize_horizon_gdf is pure (operates on a frame).
"""

from forecasting.adapters.sandag import SANDAG_FC_MAP, FLOW_COLS

# Per canonical functional class (see SANDAG_FC_MAP values). EXPLICITLY SYNTHETIC.
FACTORS = {
    "Freeway":        1.35,
    "Ramp":           1.35,
    "Prime Arterial": 1.20,
    "Major Arterial": 1.20,
    "Collector":      1.10,
    "Local":          1.05,
    "Connector":      1.00,
    "Other":          1.10,
}

# Columns scaled: the 10 directional period flows + total_flow.
FLOW_COLUMNS = [col for pair in FLOW_COLS.values() for col in pair] + ["total_flow"]


def _factor_for(fc_desc, factors):
    """Map a raw SANDAG fc_desc → canonical class → growth factor."""
    return factors.get(SANDAG_FC_MAP.get(fc_desc, "Other"), factors["Other"])


def synthesize_horizon_gdf(gdf, factors=FACTORS):
    """Return a COPY of a SANDAG GeoDataFrame with each link's FLOW_COLUMNS scaled
    by its functional-class factor. link_id, nodes, geometry, len_mile, lanes, and
    fc_desc are untouched — base↔horizon link_ids stay identical (so ingest's
    overlap/ID-stability check passes at ~100%)."""
    out = gdf.copy()
    fac = out["fc_desc"].map(lambda d: _factor_for(d, factors))
    for c in (c for c in FLOW_COLUMNS if c in out.columns):
        out[c] = out[c] * fac
    return out


def synthesize_horizon_shp(src, dst, *, factors=FACTORS, force=False):
    """Read a SANDAG shapefile at `src`, scale flows per class, write to `dst`.
    Lazy-imports geopandas (the only geo touch). Refuses to overwrite an existing
    `dst` unless force=True (protects what may be a real network already there)."""
    import os
    import geopandas as gpd

    if os.path.exists(dst) and not force:
        raise FileExistsError(
            f"{dst} already exists — pass force=True/--force to overwrite "
            "(refusing to clobber what may be a real network).")
    gdf = gpd.read_file(src)
    required = FLOW_COLUMNS + ["fc_desc"]
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        raise ValueError(f"{src} missing required SANDAG columns {missing} — "
                         "not a SANDAG loaded-highway network?")
    out = synthesize_horizon_gdf(gdf, factors=factors)
    out.to_file(dst)
    return dst


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    data = Path(__file__).resolve().parents[2] / "data" / "sandag"
    ap = argparse.ArgumentParser(
        description="Generate an EXPLICITLY-SYNTHETIC horizon SANDAG network "
                    "(per-functional-class growth). Not a SANDAG projection.")
    ap.add_argument("--src", default=str(data / "hwyLoad.shp"))
    ap.add_argument("--dst", default=str(data / "hwyLoad_2030_synthetic.shp"))
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing destination file")
    args = ap.parse_args()
    out = synthesize_horizon_shp(args.src, args.dst, force=args.force)
    print(f"wrote synthetic horizon network: {out}")
