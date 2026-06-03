"""
DemandIQ Web App — Phase A
==========================
Local FastAPI wrapper around count_agent.extract().

Run locally:
    cd ~/Desktop/demandiq
    python3.12 app.py
    # then open http://127.0.0.1:8000

On Render: Dockerfile sets up Poppler; set ANTHROPIC_API_KEY and
APP_PASSWORD in the Environment tab.
"""

import os
import io
import re
import base64
import secrets
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from count_agent import extract, MOVEMENTS
from balancer import balance_corridor, run_qc
from balancer import balance_nchrp, fractional_volume_flags, source_outlier_flags
from line_diagram import (
    render_single_diagram,
    render_diagram_grid,
    render_corridor_diagram,
    VIEW_MODES,
    FIG_INCHES,
    DPI,
)
from excel_export import build_workbook
from forecasting.api import router as forecasting_router

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY not set. Add it to ~/.bash_profile and reopen terminal."
    )

# If APP_PASSWORD is set, all routes require basic auth.
# If unset (local dev), no auth — app works exactly as before.
APP_PASSWORD = os.getenv("APP_PASSWORD")

ALLOWED_EXT = {".xlsx", ".xls", ".pdf", ".csv"}

app = FastAPI(title="DemandIQ", version="0.1.0")

# CORS — allow the Vite React dev server (localhost:3000) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic(auto_error=False)


def require_auth(creds: HTTPBasicCredentials = Depends(security)):
    """Optional auth — only enforced when APP_PASSWORD env var is set."""
    if not APP_PASSWORD:
        return None  # local dev: auth disabled
    if creds is None or not secrets.compare_digest(
        creds.password.encode("utf-8"), APP_PASSWORD.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="DemandIQ"'},
        )
    return creds.username


# ── Forecasting routes (Method 1 / NCHRP 765) — mounted under /forecast ───────
# The import above is geo-free (the adapter's geopandas import is lazy), so the
# app starts under any interpreter; only /forecast/ingest-match needs the geo
# deps at call time (503 otherwise). Auth matches the rest of the app.
app.include_router(forecasting_router, prefix="/forecast",
                   dependencies=[Depends(require_auth)])


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/extract", dependencies=[Depends(require_auth)])
async def extract_endpoint(files: list[UploadFile] = File(...)):
    """Process uploaded files. Returns extracted JSON + errors."""
    results = []
    errors = []

    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            errors.append({"file": f.filename, "error": f"Unsupported file type: {ext}"})
            continue

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(await f.read())
            tmp_path = tmp.name

        try:
            data = extract(tmp_path, API_KEY)
            data["source_file"] = f.filename
            results.append(data)
        except Exception as e:
            errors.append({"file": f.filename, "error": str(e)})
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return JSONResponse({"results": results, "errors": errors})


@app.post("/excel", dependencies=[Depends(require_auth)])
async def excel_endpoint(payload: dict):
    """Generate Excel workbook from extraction results."""
    results = payload.get("results", [])
    if not results:
        raise HTTPException(status_code=400, detail="No results to export")

    wb = Workbook()
    ws = wb.active
    ws.title = "Extracted Counts"

    headers = ["Source File", "Vendor", "Intersection", "AM Peak", "PM Peak"]
    headers += [f"AM_{m}" for m in MOVEMENTS]
    headers += [f"PM_{m}" for m in MOVEMENTS]
    headers += ["PHF_AM", "PHF_PM", "HV%_AM", "HV%_PM", "HV Method", "Notes"]
    ws.append(headers)

    hdr_fill = PatternFill("solid", fgColor="2F3640")
    hdr_font = Font(bold=True, color="FFFFFF", size=10)
    for cell in ws[1]:
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in results:
        source = r.get("source_file", "")
        vendor = r.get("vendor_detected", "")
        for inter in r.get("intersections", []):
            am_vol = (inter.get("volumes") or {}).get("AM", {}) or {}
            pm_vol = (inter.get("volumes") or {}).get("PM", {}) or {}
            phf = inter.get("phf") or {}
            hv = inter.get("hv_pct") or {}

            row = [
                source,
                vendor,
                inter.get("name", ""),
                inter.get("am_peak_start", ""),
                inter.get("pm_peak_start", ""),
            ]
            row += [am_vol.get(m) for m in MOVEMENTS]
            row += [pm_vol.get(m) for m in MOVEMENTS]
            row += [
                phf.get("AM"),
                phf.get("PM"),
                hv.get("AM"),
                hv.get("PM"),
                inter.get("hv_method", ""),
                inter.get("notes", ""),
            ]
            ws.append(row)

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 36
    ws.column_dimensions["D"].width = 10
    ws.column_dimensions["E"].width = 10
    for col_idx in range(6, 6 + 32):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = 9
    for col_idx in range(6 + 32, 6 + 32 + 6):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = 11

    ws.freeze_panes = "D2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="demandiq_results.xlsx"'},
    )


@app.post("/balance", dependencies=[Depends(require_auth)])
async def balance_endpoint(payload: dict):
    """Run Furness balancing for both AM and PM, plus QC checks.

    Wraps backend/balancer.balance_corridor + run_qc in the response shape
    the S6 frontend expects. Validates JSON shape but does not deeply
    validate movement values (frontend constrains via number inputs).
    """
    # ── Parse / validate ─────────────────────────────────────────────────────
    intersections = payload.get("intersections")
    if not isinstance(intersections, list) or not intersections:
        raise HTTPException(status_code=400, detail="intersections must be a non-empty list")
    for it in intersections:
        if not isinstance(it, dict) or "num" not in it:
            raise HTTPException(status_code=400, detail="each intersection needs a num field")

    unbalanced = payload.get("unbalanced_volumes", {})
    if not isinstance(unbalanced, dict):
        raise HTTPException(status_code=400, detail="unbalanced_volumes must be a dict")

    corridor_dir = payload.get("corridor_dir", "EB/WB")
    if corridor_dir not in ("EB/WB", "NB/SB"):
        raise HTTPException(status_code=400, detail="corridor_dir must be 'EB/WB' or 'NB/SB'")

    try:
        convergence = float(payload.get("convergence_threshold", 0.01))
        max_iter = int(payload.get("max_iterations", 200))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="convergence_threshold/max_iterations must be numeric")

    if not (0 < convergence <= 1):
        raise HTTPException(status_code=400, detail="convergence_threshold must be in (0, 1]")
    if not (1 <= max_iter <= 10000):
        raise HTTPException(status_code=400, detail="max_iterations must be in [1, 10000]")

    # Convert balance_config keys "1-2" → both (1,2) and (2,1) so the reverse
    # link can find its config without forcing the frontend to send both.
    raw_bc = payload.get("balance_config") or {}
    balance_config = {}
    for k, v in raw_bc.items():
        try:
            up_str, dn_str = str(k).split("-")
            up, dn = int(up_str), int(dn_str)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid balance_config key: {k}")
        balance_config[(up, dn)] = v
        balance_config[(dn, up)] = v

    # Cast volume + extracted_meta keys from str → int
    def _cast_vols(period_vols):
        return {int(n): mv for n, mv in (period_vols or {}).items()}

    am_unbal = _cast_vols(unbalanced.get("AM", {}))
    pm_unbal = _cast_vols(unbalanced.get("PM", {}))

    extracted_meta_raw = payload.get("extracted_meta") or {}
    extracted_meta = {int(n): meta for n, meta in extracted_meta_raw.items()}

    # ── Balance ──────────────────────────────────────────────────────────────
    am_balanced, am_log, am_adj = balance_corridor(
        intersections, am_unbal, corridor_dir, "AM",
        balance_config=balance_config,
        max_iterations=max_iter,
        convergence_threshold=convergence,
    )
    pm_balanced, pm_log, pm_adj = balance_corridor(
        intersections, pm_unbal, corridor_dir, "PM",
        balance_config=balance_config,
        max_iterations=max_iter,
        convergence_threshold=convergence,
    )

    def _conv_summary(log):
        last_gap = log[-1]["max_relative_gap"] if log else 0.0
        return {
            "iterations_used": len(log),
            "converged": last_gap <= convergence,
            "final_gap": last_gap,
            "log": log,
        }

    # ── QC ───────────────────────────────────────────────────────────────────
    qc_flags = run_qc(
        intersections,
        {"AM": am_unbal, "PM": pm_unbal},
        extracted_meta,
        {"AM": am_balanced, "PM": pm_balanced},
        corridor_dir,
    )

    # ── Response — string keys so JSON round-trips cleanly ───────────────────
    return {
        "balanced": {
            "AM": {str(n): vols for n, vols in am_balanced.items()},
            "PM": {str(n): vols for n, vols in pm_balanced.items()},
        },
        "convergence": {
            "AM": _conv_summary(am_log),
            "PM": _conv_summary(pm_log),
        },
        "adjustments": {
            "AM": am_adj,
            "PM": pm_adj,
        },
        "qc_flags": qc_flags,
    }


@app.post("/balance-nchrp", dependencies=[Depends(require_auth)])
async def balance_nchrp_endpoint(payload: dict):
    """Stage 4: real NCHRP 255/765 turning-movement refinement.

    Replaces a previous cascade-prone link-by-link balancer (now removed).
    The algorithm:
      A) resolve_link_volumes — collapse adjacent intersection counts on the
         same link into one volume per directed edge (larger or average)
      B) Per-intersection 4×4 Fratar factoring against link-resolved and
         raw-derived row/col targets
      C) Floor — clamp balanced ≥ raw on every nonzero movement
      D) Round up to next 5

    Payload:
      {
        "intersections": [{"num": int, "name": str,
                           "lat": float, "lng": float}, ...],  # lat/lng optional
                                                               # (used to set
                                                               # leg orientation)
        "unbalanced_volumes": {"AM": {num_str: {mv: val}}, "PM": {...}},
        "links": [{"fromNum", "toNum", "direction", "mode"}],
        "link_resolution_method": "larger" | "average",   # default 'larger'
        "tolerance": float,                               # default 0.5 (veh)
        "max_iterations": int                             # per-int, default 100
      }

    Response (spec §9 + resolved_links for transparency):
      {
        "balanced": {"AM": {num_str: {mv: val}}, "PM": {...}},
        "resolved_links": {
            "AM": [{"fromNum","toNum","direction","volume"}, ...],
            "PM": [...]
        },
        "iterations": {"AM": {num_str: int}, "PM": {num_str: int}},
        "converged":  {"AM": {num_str: bool}, "PM": {num_str: bool}},
        "qc_flags": [...],
        "method": "larger" | "average",
      }
    """
    intersections = payload.get("intersections")
    if not isinstance(intersections, list) or not intersections:
        raise HTTPException(status_code=400, detail="intersections must be a non-empty list")

    coords = {}
    for it in intersections:
        if not isinstance(it, dict) or "num" not in it:
            raise HTTPException(status_code=400, detail="each intersection needs a num field")
        n = int(it["num"])
        if "lat" in it and "lng" in it and it["lat"] is not None and it["lng"] is not None:
            coords[n] = {"lat": float(it["lat"]), "lng": float(it["lng"])}

    unbalanced = payload.get("unbalanced_volumes", {})
    if not isinstance(unbalanced, dict):
        raise HTTPException(status_code=400, detail="unbalanced_volumes must be a dict")

    links_in = payload.get("links", [])
    if not isinstance(links_in, list):
        raise HTTPException(status_code=400, detail="links must be a list")

    method = payload.get("link_resolution_method", "larger")
    if method not in ("larger", "average"):
        raise HTTPException(
            status_code=400,
            detail="link_resolution_method must be 'larger' or 'average'",
        )

    try:
        tol = float(payload.get("tolerance", 0.5))
        max_iter = int(payload.get("max_iterations", 500))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="tolerance/max_iterations must be numeric")

    # Stage 4c.3: pass ALL links through (including mode='None') so they
    # appear in the link_conservation output as informational. Filtering by
    # mode happens internally in balance_nchrp (None skipped from leg-total
    # balancing + reconciliation; Land Use balanced but not reconciled;
    # Full balanced + reconciled to canonical).
    # F1: validate link.direction up front. resolve_link_volumes only accepts
    # the corridor-axis form ('EB/WB' or 'NB/SB'); anything else (e.g. the
    # cardinal 'NB') is silently skipped, producing an empty resolved_links
    # array and a "0/0 links conserve ✓" hero on the frontend. Reject loud.
    VALID_DIRECTIONS = ('EB/WB', 'NB/SB')
    active_links = []
    for L in links_in:
        if not isinstance(L, dict):
            raise HTTPException(status_code=400, detail="each link must be a dict")
        direction = L.get("direction")
        if direction not in VALID_DIRECTIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"link {L.get('fromNum')}→{L.get('toNum')} has invalid direction "
                    f"{direction!r} — expected one of {list(VALID_DIRECTIONS)}. "
                    "If you exported state from an older DemandIQ build, re-create "
                    "the link via S2 so suggestDirection assigns the corridor axis."
                ),
            )
        active_links.append({
            "fromNum": int(L["fromNum"]),
            "toNum":   int(L["toNum"]),
            "direction": direction,
            "mode":    L.get("mode", "Full"),
        })

    def _cast_period(period_vols):
        out = {}
        for n_str, mv_dict in (period_vols or {}).items():
            n = int(n_str)
            full = {k: 0.0 for k in ALL_MOVEMENTS}
            for mv, val in (mv_dict or {}).items():
                if mv in full and val is not None:
                    full[mv] = float(val)
            out[n] = full
        return out

    am_raw = _cast_period(unbalanced.get("AM", {}))
    pm_raw = _cast_period(unbalanced.get("PM", {}))

    am_result = balance_nchrp(am_raw, active_links, method=method, coords=coords,
                              tol=tol, max_iter=max_iter)
    pm_result = balance_nchrp(pm_raw, active_links, method=method, coords=coords,
                              tol=tol, max_iter=max_iter)

    def _serialize_resolved(resolved, raw_pairs):
        """F7: each resolved-link entry now also carries the raw upstream and
        downstream counts that fed it, plus the absolute reconciliation
        delta. Lets the frontend surface 'algorithm smoothed away 300 veh of
        disagreement' instead of just the smoothed result."""
        out = []
        for (u, d, dirn), v in resolved.items():
            pair = raw_pairs.get((u, d, dirn)) or {}
            raw_up = pair.get('raw_upstream')
            raw_dn = pair.get('raw_downstream')
            entry = {
                "fromNum": u, "toNum": d, "direction": dirn, "volume": v,
                "raw_upstream":   raw_up if raw_up is not None else None,
                "raw_downstream": raw_dn if raw_dn is not None else None,
                "reconciliation_delta": (
                    abs(raw_dn - raw_up)
                    if raw_up is not None and raw_dn is not None
                    else None
                ),
            }
            out.append(entry)
        return out

    # Tag QC flags by period
    qc_all = []
    # Stage 10.1: source-data fractional-volume warnings (read-only check on
    # RAW inputs, before balancing). Surfaced alongside the NCHRP-* flags.
    qc_all += fractional_volume_flags(am_raw, period='AM')
    qc_all += fractional_volume_flags(pm_raw, period='PM')
    # F3 — source-data outlier warnings: flag intersections whose leg-approach
    # total is statistically implausible against the rest of the corridor (e.g.
    # an SBT count typed as 12 instead of 1200). Furness silently absorbs
    # these without this check.
    qc_all += source_outlier_flags(am_raw, period='AM')
    qc_all += source_outlier_flags(pm_raw, period='PM')

    # GEOMETRY-FALLBACK is corridor-level (geometry, not volumes) — AM and PM
    # share the same coords + links, so the flag would repeat. Dedupe by
    # (fromNum, toNum) and stamp period only on flags that didn't already
    # set one (flags with explicit period=None, like GEOMETRY-FALLBACK, are
    # left as-is so S6 renders them once corridor-wide).
    seen_geometry_pairs = set()

    def _append_flag(f, default_period):
        if f.get('check') == 'GEOMETRY-FALLBACK':
            pair = (f.get('fromNum'), f.get('toNum'))
            if pair in seen_geometry_pairs:
                return
            seen_geometry_pairs.add(pair)
            qc_all.append(dict(f))
            return
        if 'period' in f:
            qc_all.append(dict(f))
        else:
            qc_all.append({**f, 'period': default_period})

    for f in am_result['qc_flags']:
        _append_flag(f, 'AM')
    for f in pm_result['qc_flags']:
        _append_flag(f, 'PM')

    return {
        "balanced": {
            "AM": {str(n): vols for n, vols in am_result['balanced'].items()},
            "PM": {str(n): vols for n, vols in pm_result['balanced'].items()},
        },
        "resolved_links": {
            "AM": _serialize_resolved(am_result['resolved_links'], am_result.get('raw_link_pairs', {})),
            "PM": _serialize_resolved(pm_result['resolved_links'], pm_result.get('raw_link_pairs', {})),
        },
        "iterations": {
            "AM": {str(n): i for n, i in am_result['iterations'].items()},
            "PM": {str(n): i for n, i in pm_result['iterations'].items()},
        },
        "converged": {
            "AM": {str(n): c for n, c in am_result['converged'].items()},
            "PM": {str(n): c for n, c in pm_result['converged'].items()},
        },
        "final_residual": {
            "AM": {str(n): r for n, r in am_result['final_residual'].items()},
            "PM": {str(n): r for n, r in pm_result['final_residual'].items()},
        },
        "link_conservation": {
            "AM": am_result['link_conservation'],
            "PM": pm_result['link_conservation'],
        },
        "movements_review": {
            "AM": am_result['movements_review'],
            "PM": pm_result['movements_review'],
        },
        "qc_flags": qc_all,
        "method": method,
    }


# 16 movement keys including U-turns
ALL_MOVEMENTS = [
    'EBL', 'EBT', 'EBR', 'EBU',
    'WBL', 'WBT', 'WBR', 'WBU',
    'NBL', 'NBT', 'NBR', 'NBU',
    'SBL', 'SBT', 'SBR', 'SBU',
]


@app.post("/intersection-diagram", dependencies=[Depends(require_auth)])
async def intersection_diagram_endpoint(payload: dict):
    """Render one intersection as a PNG line diagram.

    Wraps backend/line_diagram.render_single_diagram. Returns the PNG as
    base64 inside JSON so the frontend can drop it into an <img src=...>
    without an extra round-trip.
    """
    intersection = payload.get("intersection")
    if not isinstance(intersection, dict) or "num" not in intersection:
        raise HTTPException(status_code=400, detail="intersection must be a dict with 'num'")

    u_vols = payload.get("u_vols", {}) or {}
    b_vols = payload.get("b_vols", {}) or {}
    if not isinstance(u_vols, dict) or not isinstance(b_vols, dict):
        raise HTTPException(status_code=400, detail="u_vols and b_vols must be dicts")

    # Stage 5: optional per-cell engineer overrides for this intersection +
    # period. Shape: {movement_key: number_value}. Replaces b_vols value for
    # that cell and adds "*" suffix to the rendered label.
    overrides = payload.get("overrides", {}) or {}
    if not isinstance(overrides, dict):
        raise HTTPException(status_code=400, detail="overrides must be a dict")

    view_mode = payload.get("view_mode", "combined")
    if view_mode not in VIEW_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"view_mode must be one of {VIEW_MODES}",
        )

    # Stage 10.4: optional free-text annotation, rendered as a caption strip.
    annotation = payload.get("annotation")
    if annotation is not None and not isinstance(annotation, str):
        raise HTTPException(status_code=400, detail="annotation must be a string")

    try:
        png_bytes = render_single_diagram(intersection, u_vols, b_vols, view_mode,
                                          overrides=overrides, annotation=annotation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"render failed: {e}")

    px = int(FIG_INCHES * DPI)
    return {
        "intersection_num": intersection["num"],
        "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "width": px,
        "height": px,
    }


@app.post("/export-diagram-grid", dependencies=[Depends(require_auth)])
async def export_diagram_grid_endpoint(payload: dict):
    """Stage 10.5: render every intersection diagram into ONE composite PNG
    grid. Reuses render_single_diagram's cell engine via render_diagram_grid.

    Payload:
      {
        "cells": [ {"intersection": {...geo}, "u_vols": {}, "b_vols": {},
                    "overrides": {}, "period_label": "AM"|"PM"|null }, ... ],
        "view_mode": "combined" | "balanced" | "unbalanced" | "delta",
        "cols": int,                # optional, default 3
        "title": str,               # optional banner
      }
    Returns: image/png (binary).
    """
    cells_in = payload.get("cells")
    if not isinstance(cells_in, list) or not cells_in:
        raise HTTPException(status_code=400, detail="cells must be a non-empty list")

    view_mode = payload.get("view_mode", "combined")
    if view_mode not in VIEW_MODES:
        raise HTTPException(status_code=400, detail=f"view_mode must be one of {VIEW_MODES}")

    cols = payload.get("cols", 3)
    try:
        cols = int(cols)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="cols must be an integer")

    cells = []
    for c in cells_in:
        if not isinstance(c, dict):
            raise HTTPException(status_code=400, detail="each cell must be a dict")
        geo = c.get("intersection")
        if not isinstance(geo, dict) or "num" not in geo:
            raise HTTPException(status_code=400, detail="each cell.intersection needs 'num'")
        cells.append({
            "geo": geo,
            "u_vols": c.get("u_vols") or {},
            "b_vols": c.get("b_vols") or {},
            "overrides": c.get("overrides") or {},
            "period_label": c.get("period_label"),
        })

    try:
        png_bytes = render_diagram_grid(
            cells, view_mode=view_mode, cols=cols, title=payload.get("title"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"grid render failed: {e}")

    return StreamingResponse(
        io.BytesIO(png_bytes),
        media_type="image/png",
        headers={"Content-Disposition": 'attachment; filename="demandiq_diagrams.png"'},
    )


@app.post("/corridor-diagram", dependencies=[Depends(require_auth)])
async def corridor_diagram_endpoint(payload: dict):
    """PRD-03: render the corridor's two line-diagram figures (AM + PM) with
    per-segment link-volume labels between adjacent intersections.

    Returns both image bytes in one round-trip — base64 inside JSON so the
    frontend can drop each into an <img src=...> and bundle both into the
    Excel/zip export without an extra fetch.

    Payload:
      {
        "cells": [ {"intersection": {...geo}, "u_vols": {}, "b_vols": {},
                    "overrides": {} }, ... ],            # in corridor order
        "resolved_links": {
            "AM": [{"fromNum","toNum","direction","volume"}, ...],
            "PM": [...],
        },
        "corridor_dir": "EB/WB" | "NB/SB",
        "view_mode": "combined" | "balanced" | "unbalanced" | "delta",
        "cols": int,                # optional, default 3
        "title": str,               # optional banner (rendered on BOTH figures)
        "b_vols": {                 # optional; if provided overrides cell.b_vols
            "AM": {num_str: {mv: val}}, "PM": {...}
        }
      }
    Returns:
      { "am": {png_base64, width, height}, "pm": {...},
        "segment_counts": {"AM": int, "PM": int}  // count of segment labels drawn,
                                                  // for FE/QA visibility
      }
    """
    cells_in = payload.get("cells")
    if not isinstance(cells_in, list) or not cells_in:
        raise HTTPException(status_code=400, detail="cells must be a non-empty list")

    view_mode = payload.get("view_mode", "combined")
    if view_mode not in VIEW_MODES:
        raise HTTPException(status_code=400, detail=f"view_mode must be one of {VIEW_MODES}")

    corridor_dir = payload.get("corridor_dir")
    if corridor_dir not in ("EB/WB", "NB/SB"):
        raise HTTPException(
            status_code=400,
            detail="corridor_dir must be 'EB/WB' or 'NB/SB'",
        )

    resolved_in = payload.get("resolved_links") or {}
    if not isinstance(resolved_in, dict):
        raise HTTPException(status_code=400, detail="resolved_links must be a dict")
    am_resolved = resolved_in.get("AM") or []
    pm_resolved = resolved_in.get("PM") or []
    if not isinstance(am_resolved, list) or not isinstance(pm_resolved, list):
        raise HTTPException(
            status_code=400,
            detail="resolved_links.AM and resolved_links.PM must be lists",
        )

    cols = payload.get("cols", 3)
    try:
        cols = int(cols)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="cols must be an integer")

    title = payload.get("title")

    # Optional per-period balanced volumes — when provided, replace the
    # cell-level b_vols so AM and PM figures differ on the per-cell numbers
    # too (not just the segment labels). The frontend always sends both.
    period_b_vols = payload.get("b_vols") or {}
    am_b = period_b_vols.get("AM") or {}
    pm_b = period_b_vols.get("PM") or {}

    def _build_cells(period_b):
        out = []
        for c in cells_in:
            if not isinstance(c, dict):
                raise HTTPException(status_code=400, detail="each cell must be a dict")
            geo = c.get("intersection")
            if not isinstance(geo, dict) or "num" not in geo:
                raise HTTPException(status_code=400, detail="each cell.intersection needs 'num'")
            num_str = str(geo["num"])
            b_vols = period_b.get(num_str) if period_b else None
            out.append({
                "geo": geo,
                "u_vols": c.get("u_vols") or {},
                "b_vols": b_vols if b_vols is not None else (c.get("b_vols") or {}),
                "overrides": c.get("overrides") or {},
            })
        return out

    try:
        am_cells = _build_cells(am_b)
        pm_cells = _build_cells(pm_b)
        am_png = render_corridor_diagram(
            am_cells, am_resolved, corridor_dir, "AM",
            view_mode=view_mode, cols=cols, title=title,
        )
        pm_png = render_corridor_diagram(
            pm_cells, pm_resolved, corridor_dir, "PM",
            view_mode=view_mode, cols=cols, title=title,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"corridor render failed: {e}")

    # segment-label counts: one per same-row adjacent pair that found a
    # matching resolved-link entry. Useful for the AC test + FE QA.
    def _count_segments(cells, resolved):
        from line_diagram import _segment_label_for_pair as _seg
        n_cells = len(cells)
        cols_eff = max(1, min(int(cols), n_cells))
        c = 0
        for i in range(n_cells - 1):
            if (i // cols_eff) != ((i + 1) // cols_eff):
                continue
            t, _ = _seg(
                int(cells[i]['geo']['num']), int(cells[i + 1]['geo']['num']),
                resolved, corridor_dir,
            )
            if t is not None:
                c += 1
        return c

    import math as _math
    cell_px = int(FIG_INCHES * DPI)
    def _dims(n_cells):
        cols_eff = max(1, min(int(cols), n_cells))
        rows_eff = _math.ceil(n_cells / cols_eff)
        return cols_eff * cell_px, rows_eff * cell_px

    am_w, am_h = _dims(len(am_cells))
    pm_w, pm_h = _dims(len(pm_cells))

    return {
        "am": {
            "png_base64": base64.b64encode(am_png).decode("ascii"),
            "width": am_w,
            "height": am_h,
        },
        "pm": {
            "png_base64": base64.b64encode(pm_png).decode("ascii"),
            "width": pm_w,
            "height": pm_h,
        },
        "segment_counts": {
            "AM": _count_segments(am_cells, am_resolved),
            "PM": _count_segments(pm_cells, pm_resolved),
        },
    }


@app.post("/export-excel", dependencies=[Depends(require_auth)])
async def export_excel_endpoint(payload: dict):
    """Generate the full 8-sheet Excel workbook from the project snapshot.

    Accepts the same shape the frontend persists to localStorage as
    'demandiq:project'. Returns an .xlsx as a binary stream.
    """
    project = payload.get("project") or {}
    name = (project.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="project.name required")

    try:
        xlsx_bytes = build_workbook(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"workbook build failed: {e}")

    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "project"

    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.xlsx"',
        },
    )


@app.get("/health")
async def health():
    """Open endpoint — used by Render health checks."""
    return {"status": "ok"}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    # DEMANDIQ_DEV=1 turns on uvicorn auto-reload for local development (restarts
    # on source edits). Reload requires the "module:app" import string rather than
    # the app object. Production (Render) leaves DEMANDIQ_DEV unset, so the server
    # never watches the filesystem.
    reload = os.getenv("DEMANDIQ_DEV") == "1"
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=reload)
