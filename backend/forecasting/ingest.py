"""
DemandIQ Forecasting — Module 3: network ingest orchestration.

A thin layer over the region adapters. The adapter (forecasting.adapters.sandag)
already does the heavy lifting — CRS reprojection (4326↔2230), the spatial filter
to the project area, and the canonical transform. This module:

  1. Resolves server-side network asset paths (role → shapefile).
  2. Calls the region adapter once per supplied model year.
  3. Runs a base↔horizon link_id overlap sanity check when both are present.

Filter-first ordering is the whole point: each returned NetworkLayer is already
spatially filtered to the 3-5 project intersections, so it is KB-scale and
serializes straight into the project model. The 90+ MB shapefile is read,
filtered, and discarded per call — never persisted whole.

Two-model-year note: NCHRP 765 Method 1 needs a BASE and a HORIZON loaded
network (refinement in module 5 joins them by link_id). This function accepts 1
or 2 networks so the second year can slot in when available. With both, the
overlap check doubles as a link_id-stability check across model years — if
SANDAG renumbered links between series, it fails loud here rather than silently
corrupting the refinement join.
"""

from pathlib import Path

from forecasting.adapters.sandag import ingest_sandag

# Server-side SANDAG network assets live under the repo's data/ dir (gitignored).
REPO_ROOT = Path(__file__).resolve().parents[2]
SANDAG_DATA_DIR = REPO_ROOT / "data" / "sandag"

# role → shapefile path. A network's year is engineer-tagged at ingest
# (scenario_year), NOT inferred from the filename. Left unpopulated until it's
# confirmed which file is which model year; callers pass an explicit `path` per
# network meanwhile (e.g. tests, or the eventual ingest endpoint).
SANDAG_ASSET_REGISTRY = {
    # "base":    SANDAG_DATA_DIR / "hwyLoad.shp",
    # "horizon": SANDAG_DATA_DIR / "hwyLoad.shp",
}


def _resolve_path(spec):
    """Explicit `path` wins; otherwise resolve `role` via the asset registry."""
    path = spec.get("path")
    if path is not None:
        return path
    role = spec.get("role")
    if role in SANDAG_ASSET_REGISTRY:
        return SANDAG_ASSET_REGISTRY[role]
    raise ValueError(
        f"ingest_networks: no path for network role {role!r} — pass an explicit "
        "'path' or register it in SANDAG_ASSET_REGISTRY."
    )


def _base_horizon_overlap(base_layer, horizon_layer):
    """Fraction of base-year links whose link_id also appears in the horizon
    network. ~1.0 when IDs are stable and the corridor is unchanged; ~0 when the
    wrong files were tagged or IDs were renumbered across model series."""
    base_ids = {l.link_id for l in base_layer.links}
    horizon_ids = {l.link_id for l in horizon_layer.links}
    if not base_ids:
        return 0.0
    return len(base_ids & horizon_ids) / len(base_ids)


def ingest_networks(
    project_intersections_4326,
    networks,
    *,
    region="SANDAG",
    filter_radius_ft=300,
    min_overlap=0.5,
):
    """Ingest one or two SANDAG model-year networks, filtered to the project.

    Args:
        project_intersections_4326: iterable of {lat, lng, ...} (EPSG:4326).
        networks: list of specs, each:
            { "role": "base"|"horizon", "scenario_year": int, "path"?: shp_path }
            `path` is optional if `role` is in SANDAG_ASSET_REGISTRY.
        region: only "SANDAG" is built in v1.
        filter_radius_ft: passed through to the adapter (default 300).
        min_overlap: minimum base→horizon link_id overlap fraction required when
            both roles are present (default 0.5). Below it → fail loud.

    Returns:
        { role: NetworkLayer } — one filtered NetworkLayer per supplied network.

    Raises:
        NotImplementedError: region other than SANDAG.
        ValueError: empty networks, missing role/scenario_year, duplicate role,
            unresolvable path, or base↔horizon overlap below min_overlap.
    """
    if region != "SANDAG":
        raise NotImplementedError(f"region {region!r} has no adapter (v1 is SANDAG-only)")
    if not networks:
        raise ValueError("ingest_networks: no networks supplied")

    layers = {}
    for spec in networks:
        role = spec.get("role")
        if role is None:
            raise ValueError(f"ingest_networks: network spec missing 'role': {spec}")
        if role in layers:
            raise ValueError(f"ingest_networks: duplicate network role {role!r}")
        if "scenario_year" not in spec:
            raise ValueError(f"ingest_networks: network role {role!r} missing 'scenario_year'")
        path = _resolve_path(spec)
        layers[role] = ingest_sandag(
            path, spec["scenario_year"], project_intersections_4326,
            filter_radius_ft=filter_radius_ft,
        )

    if "base" in layers and "horizon" in layers:
        frac = _base_horizon_overlap(layers["base"], layers["horizon"])
        if frac < min_overlap:
            raise ValueError(
                f"ingest_networks: base↔horizon link_id overlap {frac:.0%} is below "
                f"{min_overlap:.0%} — the two networks likely aren't the same corridor "
                "across model years (wrong files tagged, or SANDAG renumbered link IDs "
                "between series). Refinement joins by link_id and would be unreliable."
            )

    return layers
