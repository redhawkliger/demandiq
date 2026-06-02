"""
DemandIQ Forecasting — HTTP API (two endpoints).

An APIRouter, mounted by app.py under /forecast. Kept separate from app.py so it
carries no dependency on the app's ANTHROPIC_API_KEY / auth and can be tested in
isolation on a bare FastAPI() with TestClient.

Endpoints:
  POST /forecast/ingest-match  — the ONLY geo-dependent route. Ingests the SANDAG
                                 network(s) around the project intersections and
                                 matches the base layer to the legs. Returns the
                                 filtered layers (KB-scale) + match results for
                                 the review UI. Returns 503 if the geo deps aren't
                                 installed (lean image); the rest of the app works.
  POST /forecast/run           — pure Python. refine → Pass 1 → Pass 2 → future TMCs.

Validation mirrors app.py's style: dict payloads + HTTPException. Round-tripped
layers are validated through the NetworkLayer Pydantic model.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from forecasting.contract import NetworkLayer, Period
from forecasting.ingest import ingest_networks, SANDAG_DATA_DIR
from forecasting.matcher import match_network_to_legs
from forecasting.refinement import refine_corridor
from forecasting.pass1 import forecast_corridor
from forecasting.pass2 import balance_future

router = APIRouter()


def _int_keys(d):
    return {int(k): v for k, v in (d or {}).items()}


def _str_keys(d):
    return {str(k): v for k, v in (d or {}).items()}


def _serialize_pass2(p2):
    """JSON-safe view of balance_nchrp's result (resolved_links is tuple-keyed)."""
    return {
        "balanced": _str_keys(p2.get("balanced", {})),
        "link_conservation": p2.get("link_conservation", []),
        "iterations": _str_keys(p2.get("iterations", {})),
        "converged": _str_keys(p2.get("converged", {})),
        "final_residual": _str_keys(p2.get("final_residual", {})),
        "qc_flags": p2.get("qc_flags", []),
        "movements_review": p2.get("movements_review", []),
        "method": p2.get("method"),
        "resolved_links": [
            {"fromNum": u, "toNum": d, "direction": dirn, "volume": v}
            for (u, d, dirn), v in p2.get("resolved_links", {}).items()
        ],
    }


@router.post("/ingest-match")
def ingest_match(payload: dict):
    """Ingest the SANDAG network(s) around the project intersections and match the
    base layer to the legs. Geo-dependent — 503 if geopandas et al. are absent."""
    intersections = payload.get("intersections")
    if not isinstance(intersections, list) or not intersections:
        raise HTTPException(status_code=400, detail="intersections must be a non-empty list")

    networks = payload.get("networks")
    if not isinstance(networks, list) or not networks:
        raise HTTPException(status_code=400, detail="networks must be a non-empty list")

    # Security: an explicit shapefile path must resolve under the server's
    # SANDAG data dir — never let a client read arbitrary server files.
    data_root = str(SANDAG_DATA_DIR.resolve())
    for n in networks:
        path = n.get("path") if isinstance(n, dict) else None
        if path is not None and not str(Path(path).resolve()).startswith(data_root):
            raise HTTPException(status_code=400,
                                detail=f"network path must be under {data_root}")

    try:
        radius = float(payload.get("filter_radius_ft", 300))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="filter_radius_ft must be numeric")

    try:
        layers = ingest_networks(intersections, networks, filter_radius_ft=radius)
    except ModuleNotFoundError:
        raise HTTPException(
            status_code=503,
            detail=("ingest requires the forecasting geo dependencies "
                    "(geopandas/shapely/pyproj) — run the app under the combined "
                    "venv (requirements.txt + requirements-forecasting.txt)."),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base = layers.get("base")
    if base is None:
        raise HTTPException(status_code=400,
                            detail="a network with role 'base' is required to match")

    matches = match_network_to_legs(intersections, base)
    return {
        "layers": {role: lyr.model_dump(mode="json") for role, lyr in layers.items()},
        "matches": matches,
    }


@router.post("/run")
def run_forecast(payload: dict):
    """refine → Pass 1 → Pass 2 for each period. Pure Python; no geo deps."""
    layers_in = payload.get("layers") or {}
    if "base" not in layers_in or "horizon" not in layers_in:
        raise HTTPException(
            status_code=400,
            detail="layers must include both 'base' and 'horizon' "
                   "(forecasting needs two model years).")
    try:
        base_layer = NetworkLayer.model_validate(layers_in["base"])
        horizon_layer = NetworkLayer.model_validate(layers_in["horizon"])
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"invalid layer payload: {e}")

    matches = payload.get("matches") or []
    links = payload.get("links") or []
    method = payload.get("method", "larger")
    refine_method = payload.get("refine_method", "ratio")
    peak_hour_factor = payload.get("peak_hour_factor")
    coords = _int_keys(payload.get("coords") or {})
    balanced = payload.get("balanced_tmcs") or {}
    periods = payload.get("periods") or ["AM", "PM"]

    manual = payload.get("manual_targets")
    manual_targets = {int(k): v for k, v in manual.items()} if manual else None

    out = {}
    for p in periods:
        if p not in ("AM", "PM"):
            raise HTTPException(status_code=400, detail=f"period must be 'AM' or 'PM', got {p!r}")
        period = Period[p]
        tmcs = _int_keys(balanced.get(p) or {})
        try:
            rr = refine_corridor(matches, base_layer, horizon_layer, tmcs, period,
                                 peak_hour_factor=peak_hour_factor, method=refine_method)
            futures, p1_meta = forecast_corridor(rr, tmcs, manual_targets=manual_targets)
            p2 = balance_future(futures, links, coords=coords, method=method)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        out[p] = {
            "refinement": rr,
            "pass1": {"futures": _str_keys(futures), "meta": _str_keys(p1_meta)},
            "pass2": _serialize_pass2(p2),
        }
    return out
