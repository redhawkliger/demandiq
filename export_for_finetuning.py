"""
DemandIQ — Export for Fine-tuning
==================================
Converts confirmed rows from labels_template.xlsx into JSONL format
suitable for Anthropic fine-tuning.

Only rows with confirmed=TRUE are exported.

Usage:
    py export_for_finetuning.py
    py export_for_finetuning.py <labels_file.xlsx> <output.jsonl>
"""

import sys, json
from pathlib import Path

try:
    from openpyxl import load_workbook
except ImportError:
    sys.exit("Run: pip install openpyxl --break-system-packages")

from count_agent import read_file, SYSTEM_PROMPT

MOVEMENTS = [
    'EBU','EBL','EBT','EBR',
    'WBU','WBL','WBT','WBR',
    'NBU','NBL','NBT','NBR',
    'SBU','SBL','SBT','SBR',
]

def row_to_extraction(row):
    """Convert an Excel row back into the extraction JSON structure."""
    volumes = {'AM': {}, 'PM': {}}
    for period in ('AM','PM'):
        for mv in MOVEMENTS:
            v = row.get(f'{mv}_{period}')
            volumes[period][mv] = v if v is not None else None

    extraction = {
        "vendor_detected": row.get('vendor'),
        "intersections": [{
            "name":           row.get('intersection'),
            "am_peak_start":  row.get('AM_peak'),
            "pm_peak_start":  row.get('PM_peak'),
            "volumes":        volumes,
            "phf":            {"AM": row.get('PHF_AM'), "PM": row.get('PHF_PM')},
            "hv_pct":         {"AM": row.get('HV_AM_pct'), "PM": row.get('HV_PM_pct')},
            "hv_method":      row.get('HV_method',''),
            "notes":          row.get('notes','') or '',
        }]
    }
    return extraction

def build_training_example(file_content, filename, extraction):
    """
    Anthropic fine-tuning format — messages list.
    https://docs.claude.com/en/docs/build-with-claude/fine-tuning
    """
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Filename: {filename}\n\nFile content:\n{file_content}"},
            {"role": "assistant", "content": json.dumps(extraction, indent=None)}
        ]
    }

def export(labels_path, output_path, files_root=None):
    wb = load_workbook(labels_path)
    ws = wb['Labels']

    # Build header -> column index map
    header = {}
    for ci in range(1, ws.max_column + 1):
        h = ws.cell(row=1, column=ci).value
        if h: header[h] = ci

    if 'file_name' not in header or 'confirmed' not in header:
        sys.exit("Labels file missing required columns (file_name, confirmed)")

    confirmed_rows = []
    for r in range(2, ws.max_row + 1):
        if not ws.cell(row=r, column=header['file_name']).value:
            continue
        if ws.cell(row=r, column=header['confirmed']).value is not True:
            continue

        row = {h: ws.cell(row=r, column=ci).value for h, ci in header.items()}
        confirmed_rows.append(row)

    if not confirmed_rows:
        sys.exit("No confirmed rows found. Set confirmed=TRUE on rows you want to export.")

    print(f"Found {len(confirmed_rows)} confirmed rows")

    if files_root is None:
        files_root = input("Path to folder containing the source count files: ").strip().strip('"')

    files_root = Path(files_root) if files_root else None

    written = 0
    missing = 0
    with open(output_path, 'w', encoding='utf-8') as out:
        for row in confirmed_rows:
            fname = row['file_name']
            if files_root:
                fp = files_root / fname
                if not fp.exists():
                    # Try searching subdirectories
                    found = list(files_root.rglob(fname))
                    if found:
                        fp = found[0]
                    else:
                        print(f"  ✗ Not found: {fname}")
                        missing += 1
                        continue

                try:
                    content, _ = read_file(str(fp))
                except Exception as e:
                    print(f"  ✗ Read failed for {fname}: {e}")
                    missing += 1
                    continue
            else:
                content = "[FILE CONTENT NOT LOADED]"

            extraction = row_to_extraction(row)
            example = build_training_example(content, fname, extraction)
            out.write(json.dumps(example) + '\n')
            written += 1

    print(f"\n✓ Wrote {written} training examples to {output_path}")
    if missing:
        print(f"⚠  {missing} files missing — skipped")
    print(f"\nNext step: Upload {output_path} to Anthropic fine-tuning.")
    print(f"See https://docs.claude.com/en/docs/build-with-claude/fine-tuning")

def main():
    labels = sys.argv[1] if len(sys.argv) >= 2 else "labels_template.xlsx"
    output = sys.argv[2] if len(sys.argv) >= 3 else "training_data.jsonl"

    if not Path(labels).exists():
        sys.exit(f"Labels file not found: {labels}")

    export(labels, output)

if __name__ == "__main__":
    main()
