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
from line_diagram import render_single_diagram, VIEW_MODES, FIG_INCHES, DPI
from excel_export import build_workbook

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


@app.post("/line-diagram", dependencies=[Depends(require_auth)])
async def line_diagram_endpoint(payload: dict):
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

    view_mode = payload.get("view_mode", "combined")
    if view_mode not in VIEW_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"view_mode must be one of {VIEW_MODES}",
        )

    try:
        png_bytes = render_single_diagram(intersection, u_vols, b_vols, view_mode)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"render failed: {e}")

    px = int(FIG_INCHES * DPI)
    return {
        "intersection_num": intersection["num"],
        "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "width": px,
        "height": px,
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
    uvicorn.run(app, host="0.0.0.0", port=port)
