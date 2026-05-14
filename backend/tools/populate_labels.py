"""
DemandIQ — Populate Labels
==========================
Batch-processes count files in a folder. For each file:
  1. Runs Claude extraction (count_agent.py)
  2. Runs Python verification (count_verifier.py)
  3. Appends one row to labels_template.xlsx

Each row pre-filled with Claude's output. Verification status tells you
which ones need your attention.

Usage:
    py populate_labels.py <folder_path>
    py populate_labels.py <folder_path> <labels_file.xlsx>

Defaults to labels_template.xlsx in the current directory.
"""

import os, sys, json, datetime as dt
from pathlib import Path

try:
    from openpyxl import load_workbook
except ImportError:
    sys.exit("Run: pip install openpyxl --break-system-packages")

from count_agent import extract
from count_verifier import verify

DEFAULT_LABELS = "labels_template.xlsx"
SUPPORTED_EXT  = {'.xlsx', '.xls', '.pdf', '.csv'}

MOVEMENTS = [
    'EBU','EBL','EBT','EBR',
    'WBU','WBL','WBT','WBR',
    'NBU','NBL','NBT','NBR',
    'SBU','SBL','SBT','SBR',
]

# Column names in labels Excel — must match template exactly
COLUMNS = [
    'file_name','vendor','intersection','control_type','count_date',
    'AM_peak','PM_peak',
    'EBU_AM','EBL_AM','EBT_AM','EBR_AM',
    'WBU_AM','WBL_AM','WBT_AM','WBR_AM',
    'NBU_AM','NBL_AM','NBT_AM','NBR_AM',
    'SBU_AM','SBL_AM','SBT_AM','SBR_AM',
    'EBU_PM','EBL_PM','EBT_PM','EBR_PM',
    'WBU_PM','WBL_PM','WBT_PM','WBR_PM',
    'NBU_PM','NBL_PM','NBT_PM','NBR_PM',
    'SBU_PM','SBL_PM','SBT_PM','SBR_PM',
    'PHF_AM','PHF_PM','HV_AM_pct','HV_PM_pct','HV_method',
    'verification_status','confirmed','notes','extracted_at',
]

def build_row(filepath, extraction, verification):
    """Convert Claude + verification output into a single row dict."""
    row = {c: None for c in COLUMNS}
    row['file_name'] = Path(filepath).name
    row['vendor']    = extraction.get('vendor_detected')
    row['extracted_at'] = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    row['confirmed'] = False

    intersections = extraction.get('intersections', [])
    if not intersections:
        row['verification_status'] = 'NO_DATA'
        row['notes'] = 'Claude returned no intersections'
        return row

    intr = intersections[0]
    row['intersection']  = intr.get('name')
    row['control_type']  = intr.get('control_type','')
    row['count_date']    = intr.get('count_date','')
    row['AM_peak']       = intr.get('am_peak_start')
    row['PM_peak']       = intr.get('pm_peak_start')

    vols = intr.get('volumes', {})
    for period in ('AM','PM'):
        pv = vols.get(period, {}) or {}
        for mv in MOVEMENTS:
            row[f'{mv}_{period}'] = pv.get(mv)

    phf = intr.get('phf', {}) or {}
    row['PHF_AM'] = phf.get('AM')
    row['PHF_PM'] = phf.get('PM')

    hv = intr.get('hv_pct', {}) or {}
    row['HV_AM_pct'] = hv.get('AM')
    row['HV_PM_pct'] = hv.get('PM')
    row['HV_method'] = intr.get('hv_method','')

    # Verification status
    if verification.get('status') == 'OK' and verification.get('intersections'):
        overall = verification['intersections'][0].get('overall','UNKNOWN')
        row['verification_status'] = overall
    else:
        row['verification_status'] = verification.get('status','SKIPPED')

    notes = intr.get('notes','') or ''
    if verification.get('reason'):
        notes = (notes + ' | ' + verification['reason']).strip(' |')
    row['notes'] = notes

    return row

def append_row(ws, row_dict):
    """Find next empty row and write values in the right columns."""
    # Find next empty row after header
    next_row = 2
    while ws.cell(row=next_row, column=1).value:
        next_row += 1

    for ci, col in enumerate(COLUMNS, 1):
        val = row_dict.get(col)
        ws.cell(row=next_row, column=ci, value=val)

def already_processed(ws, filename):
    """Check if a file has already been processed."""
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == filename:
            return True
    return False

def process_folder(folder, labels_path, api_key):
    folder = Path(folder)
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")

    files = [f for f in folder.iterdir()
             if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
             and not f.name.startswith('~$')]   # skip Excel lock files

    if not files:
        sys.exit(f"No supported files in {folder}")

    print(f"\nFound {len(files)} files in {folder}")

    # Load labels workbook
    if not Path(labels_path).exists():
        sys.exit(f"Labels file not found: {labels_path}\nDownload labels_template.xlsx first.")

    wb = load_workbook(labels_path)
    ws = wb['Labels']

    processed = 0
    skipped   = 0
    for i, fp in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {fp.name}")

        if already_processed(ws, fp.name):
            print(f"  ⏭  Already in labels file — skipping")
            skipped += 1
            continue

        try:
            print("  Extracting...")
            extraction = extract(str(fp), api_key)
        except Exception as e:
            print(f"  ✗ Extraction failed: {e}")
            # Add row with error status
            error_row = {c: None for c in COLUMNS}
            error_row['file_name'] = fp.name
            error_row['verification_status'] = 'EXTRACT_ERROR'
            error_row['notes'] = str(e)[:200]
            error_row['confirmed'] = False
            error_row['extracted_at'] = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
            append_row(ws, error_row)
            continue

        print("  Verifying...")
        verification = verify(str(fp), extraction)

        row = build_row(str(fp), extraction, verification)
        append_row(ws, row)

        status = row['verification_status']
        sym = "✓" if status == "VERIFIED" else "⚠" if status == "CHECK" else "✗" if status == "MISMATCH" else "•"
        print(f"  {sym} Status: {status}")
        processed += 1

        # Save after every file (so you don't lose progress on crash)
        wb.save(labels_path)

    print(f"\n{'═'*60}")
    print(f"  Done. Processed: {processed}  Skipped: {skipped}  Total in sheet: processed+skipped")
    print(f"  Labels file: {labels_path}")
    print(f"{'═'*60}")

def main():
    if len(sys.argv) < 2:
        print("Usage: py populate_labels.py <folder_path> [<labels_file.xlsx>]")
        sys.exit(1)

    folder = sys.argv[1]
    labels = sys.argv[2] if len(sys.argv) >= 3 else DEFAULT_LABELS

    api_key = os.environ.get("ANTHROPIC_API_KEY","") or input("ANTHROPIC_API_KEY: ").strip()
    if not api_key:
        sys.exit("API key required")

    process_folder(folder, labels, api_key)

if __name__ == "__main__":
    main()
