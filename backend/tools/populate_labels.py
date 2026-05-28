"""
DemandIQ — Populate Labels (labeling-assist harness)
====================================================
Batch-processes count files in a folder. For each file:
  1. Runs Claude extraction (count_agent.py) — optionally with an explicit
     --vendor hint so image PDFs get vendor-matched reference examples.
  2. Runs Python verification (count_verifier.py).
  3. Appends one PRE-FILLED row to a COPY of labels_template.xlsx with
     confirmed = FALSE on every row (the engineer flips to TRUE on review).
  4. Sets a REVIEW triage flag + cell highlight wherever the verifier
     didn't cleanly VERIFY, so the engineer's eye goes there first.

This turns new-vendor labeling from type-48-fields-from-scratch into a
review-and-correct pass. It NEVER auto-confirms anything.

Usage (named — preferred):
    python3 populate_labels.py --vendor "GRAM Traffic" \
        --input <pdf_dir> --output <prefilled.xlsx>

Usage (legacy positional, still supported):
    python3 populate_labels.py <folder_path> [<labels_file.xlsx>]
"""

import os, sys, json, shutil, argparse, datetime as dt
from pathlib import Path

try:
    from openpyxl import load_workbook
    from openpyxl.styles import PatternFill
except ImportError:
    sys.exit("Run: pip install openpyxl --break-system-packages")

from count_agent import extract
from count_verifier import verify

DEFAULT_LABELS = "labels_template.xlsx"
TEMPLATE       = Path(__file__).parent / "labels_template.xlsx"
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
# Stage 8: extra triage column appended after the template's columns.
REVIEW_COL = 'review'

# Verifier outcomes that DON'T need the engineer's eye first.
_CLEAN_STATUSES = {'VERIFIED'}
# Hard problems (red highlight) vs soft/unverified (amber).
_FAIL_STATUSES = {'MISMATCH', 'EXTRACT_ERROR', 'ERROR', 'NO_DATA',
                  'NO_SHEET', 'NO_STRUCTURE'}

_FILL_FAIL  = PatternFill(start_color='FFF4CCCC', end_color='FFF4CCCC', fill_type='solid')  # red-ish
_FILL_CHECK = PatternFill(start_color='FFFCE5CD', end_color='FFFCE5CD', fill_type='solid')  # amber-ish


def review_flag(verification_status):
    """Map a verification_status to a REVIEW triage value.
    Returns '' for cleanly-verified rows, else 'FAIL' / 'CHECK' / 'UNVERIFIED'.
    Pure function — unit-tested without the API."""
    s = (verification_status or '').upper()
    if s in _CLEAN_STATUSES:
        return ''
    if s in _FAIL_STATUSES:
        return 'FAIL'
    if s in ('CHECK', 'PARTIAL'):
        return 'CHECK'
    # SKIPPED (PDFs / legacy .xls) and anything else — needs human eyes,
    # but isn't a hard verifier failure.
    return 'UNVERIFIED'


def build_row(filepath, extraction, verification):
    """Convert Claude + verification output into a single row dict.
    Pre-fill only — confirmed is ALWAYS False here."""
    row = {c: None for c in COLUMNS}
    row['file_name'] = Path(filepath).name
    row['vendor']    = extraction.get('vendor_detected')
    row['extracted_at'] = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    row['confirmed'] = False

    intersections = extraction.get('intersections', [])
    if not intersections:
        row['verification_status'] = 'NO_DATA'
        row['notes'] = 'Claude returned no intersections'
        row[REVIEW_COL] = review_flag(row['verification_status'])
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

    row[REVIEW_COL] = review_flag(row['verification_status'])
    return row


def _ensure_review_header(ws):
    """Return the column index for the REVIEW column, adding the header if
    the sheet doesn't already have it."""
    header_cells = next(ws.iter_rows(min_row=1, max_row=1))
    for cell in header_cells:
        if cell.value == REVIEW_COL:
            return cell.column
    col = ws.max_column + 1
    ws.cell(row=1, column=col, value=REVIEW_COL)
    return col


def append_row(ws, row_dict, review_col_idx):
    """Find next empty row and write values in the right columns.
    Highlights the row's verification_status + review cells on a flag."""
    next_row = 2
    while ws.cell(row=next_row, column=1).value:
        next_row += 1

    for ci, col in enumerate(COLUMNS, 1):
        ws.cell(row=next_row, column=ci, value=row_dict.get(col))

    flag = row_dict.get(REVIEW_COL, '')
    ws.cell(row=next_row, column=review_col_idx, value=flag)

    if flag in ('FAIL', 'CHECK'):
        fill = _FILL_FAIL if flag == 'FAIL' else _FILL_CHECK
        # highlight the review + verification_status cells
        ws.cell(row=next_row, column=review_col_idx).fill = fill
        vs_idx = COLUMNS.index('verification_status') + 1
        ws.cell(row=next_row, column=vs_idx).fill = fill


def already_processed(ws, filename):
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=1).value == filename:
            return True
    return False


def _prepare_output(output_path):
    """Ensure the output workbook exists. If it doesn't, copy the template
    so the engineer's prefilled file carries the dashboards + formatting.
    Returns the loaded workbook."""
    out = Path(output_path)
    if not out.exists():
        if not TEMPLATE.exists():
            sys.exit(f"Template not found: {TEMPLATE}")
        shutil.copyfile(TEMPLATE, out)
        print(f"  Created {out.name} from template")
    return load_workbook(output_path)


def process_folder(folder, output_path, api_key, vendor_hint=None):
    folder = Path(folder)
    if not folder.is_dir():
        sys.exit(f"Not a folder: {folder}")

    files = [f for f in folder.iterdir()
             if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
             and not f.name.startswith('~$')]
    if not files:
        sys.exit(f"No supported files in {folder}")

    print(f"\nFound {len(files)} files in {folder}"
          + (f"  (vendor hint: {vendor_hint})" if vendor_hint else ""))

    wb = _prepare_output(output_path)
    ws = wb['Labels']
    review_col_idx = _ensure_review_header(ws)

    processed = skipped = flagged = 0
    for i, fp in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {fp.name}")
        if already_processed(ws, fp.name):
            print("  ⏭  Already in labels file — skipping")
            skipped += 1
            continue

        try:
            print("  Extracting...")
            extraction = extract(str(fp), api_key, vendor_hint=vendor_hint)
        except Exception as e:
            print(f"  ✗ Extraction failed: {e}")
            error_row = {c: None for c in COLUMNS}
            error_row['file_name'] = fp.name
            error_row['vendor'] = vendor_hint
            error_row['verification_status'] = 'EXTRACT_ERROR'
            error_row['notes'] = str(e)[:200]
            error_row['confirmed'] = False
            error_row['extracted_at'] = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
            error_row[REVIEW_COL] = review_flag('EXTRACT_ERROR')
            append_row(ws, error_row, review_col_idx)
            flagged += 1
            wb.save(output_path)
            continue

        print("  Verifying...")
        verification = verify(str(fp), extraction)
        row = build_row(str(fp), extraction, verification)
        append_row(ws, row, review_col_idx)

        status = row['verification_status']
        flag = row[REVIEW_COL]
        sym = "✓" if status == "VERIFIED" else "⚠" if flag == "CHECK" else "✗" if flag == "FAIL" else "•"
        print(f"  {sym} Status: {status}" + (f"  [REVIEW: {flag}]" if flag else ""))
        processed += 1
        if flag:
            flagged += 1
        wb.save(output_path)

    print(f"\n{'═'*60}")
    print(f"  Done. Processed: {processed}  Skipped: {skipped}  Flagged for review: {flagged}")
    print(f"  Output: {output_path}")
    print(f"  All rows confirmed=FALSE — review, correct, then set confirmed=TRUE.")
    print(f"{'═'*60}")


def main():
    p = argparse.ArgumentParser(description="DemandIQ labeling-assist harness")
    p.add_argument('--vendor', help="Explicit vendor hint (e.g. 'GRAM Traffic') "
                                     "— improves reference-example matching for PDFs")
    p.add_argument('--input',  help="Folder of count files to process")
    p.add_argument('--output', help="Prefilled output .xlsx (copied from template if absent)")
    # Legacy positional: <folder> [<labels.xlsx>]
    p.add_argument('pos', nargs='*', help=argparse.SUPPRESS)
    args = p.parse_args()

    folder = args.input or (args.pos[0] if args.pos else None)
    output = args.output or (args.pos[1] if len(args.pos) >= 2 else DEFAULT_LABELS)
    if not folder:
        p.error("provide --input <folder> (or a positional folder path)")

    api_key = os.environ.get("ANTHROPIC_API_KEY","") or input("ANTHROPIC_API_KEY: ").strip()
    if not api_key:
        sys.exit("API key required")

    process_folder(folder, output, api_key, vendor_hint=args.vendor)


if __name__ == "__main__":
    main()
