"""
DemandIQ — Count Verifier
==========================
Dynamic Python math verifier. Independently re-calculates volumes from the
raw Excel file and compares to Claude's extraction.

NO vendor hardcoding. Auto-detects:
  - Which sheet has the vehicle data
  - Which column has time values
  - Which columns are L/T/R/U movements
  - Where AM/PM sections begin/end

Works across NDS, GRAM, Counts Unlimited, any Excel with 15-min intervals.

PDFs are not verified — Claude-only output flagged for human review.
"""

import datetime as dt
from pathlib import Path

MOVEMENTS = [
    'EBU','EBL','EBT','EBR',
    'WBU','WBL','WBT','WBR',
    'NBU','NBL','NBT','NBR',
    'SBU','SBL','SBT','SBR',
]

# Maps ANY file column label → standard movement code
COL_PATTERNS = {
    # Short-form (NDS, ATC)
    'NL':'NBL','NT':'NBT','NR':'NBR','NU':'NBU',
    'SL':'SBL','ST':'SBT','SR':'SBR','SU':'SBU',
    'EL':'EBL','ET':'EBT','ER':'EBR','EU':'EBU',
    'WL':'WBL','WT':'WBT','WR':'WBR','WU':'WBU',
    # Already standard
    'NBL':'NBL','NBT':'NBT','NBR':'NBR','NBU':'NBU',
    'SBL':'SBL','SBT':'SBT','SBR':'SBR','SBU':'SBU',
    'EBL':'EBL','EBT':'EBT','EBR':'EBR','EBU':'EBU',
    'WBL':'WBL','WBT':'WBT','WBR':'WBR','WBU':'WBU',
}

VOL_TOLERANCE = 5        # vehicles — within = VERIFIED
PHF_TOLERANCE = 0.02

# ── PUBLIC API ────────────────────────────────────────────────────────────────
def verify(filepath, claude_result):
    ext = Path(filepath).suffix.lower()
    if ext == '.pdf':
        return {"status":"SKIPPED","reason":"PDF — Claude-only extraction, engineer review recommended"}
    if ext == '.xls':
        return {"status":"SKIPPED","reason":"Legacy .xls — convert to .xlsx for auto-verification"}
    if ext != '.xlsx':
        return {"status":"SKIPPED","reason":f"Unsupported format: {ext}"}

    try:
        import openpyxl
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    except Exception as e:
        return {"status":"ERROR","reason":str(e)}

    report = {"status":"OK","intersections":[]}
    for intr in claude_result.get("intersections", []):
        report["intersections"].append(_verify_intersection(wb, intr))
    return report

# ── VERIFY ONE INTERSECTION ───────────────────────────────────────────────────
def _verify_intersection(wb, intr):
    report = {
        "name": intr.get("name","?"),
        "movements": {},
        "phf": {},
        "overall": "UNKNOWN"
    }

    sheet = _find_vehicle_sheet(wb)
    if not sheet:
        report["overall"] = "NO_SHEET"
        report["reason"] = "No sheet with interval data found"
        return report

    structure = _analyze_sheet(wb[sheet])
    if not structure:
        report["overall"] = "NO_STRUCTURE"
        report["reason"] = f"Could not parse '{sheet}'"
        return report

    for period in ("AM","PM"):
        peak = intr.get(f"{period.lower()}_peak_start")
        if not peak: continue
        result = _verify_period(structure, intr, period, peak)
        if result:
            report["movements"][period] = result["movements"]
            if result.get("phf"):
                report["phf"][period] = result["phf"]

    # Overall status
    statuses = []
    for mvs in report["movements"].values():
        statuses += [d["status"] for d in mvs.values() if d["status"] != "NO_DATA"]
    for p in report["phf"].values():
        statuses.append(p["status"])

    if any(s=="MISMATCH" for s in statuses):
        report["overall"] = "MISMATCH"
    elif any(s=="CHECK" for s in statuses):
        report["overall"] = "CHECK"
    elif statuses and all(s in ("VERIFIED","NULL") for s in statuses):
        report["overall"] = "VERIFIED"
    else:
        report["overall"] = "PARTIAL"

    return report

# ── DYNAMIC STRUCTURE DETECTION ───────────────────────────────────────────────
def _find_vehicle_sheet(wb):
    """Find sheet most likely to have total vehicle interval data."""
    TOTAL_HINTS = ['total', 'all', 'vehicles', 'turning']
    EXCLUDE = ['bike','ped','truck','heavy','ht ','car','passenger',
               'bank','unshifted','peak summary','summary','cover']

    best = []
    for name in wb.sheetnames:
        sn = name.lower()
        if any(e in sn for e in EXCLUDE):
            continue
        ws = wb[name]
        time_count = _count_time_rows(ws)
        bonus = 1000 if any(h in sn for h in TOTAL_HINTS) else 0
        best.append((time_count + bonus, time_count, name))

    best.sort(reverse=True)
    return best[0][2] if best and best[0][1] > 0 else None

def _count_time_rows(ws):
    count = 0
    for row in ws.iter_rows(values_only=True, max_row=500):
        if not row: continue
        t = row[0]
        if isinstance(t, (dt.time, dt.datetime)):
            count += 1
        elif isinstance(t, str) and _parse_time(t):
            count += 1
    return count

def _parse_time(s):
    if not isinstance(s, str): return None
    s = s.strip()
    for fmt in ("%I:%M %p","%I:%M%p","%H:%M","%H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None

def _analyze_sheet(ws):
    """
    Auto-detect structure:
      1. Find column-header row (L/T/R/U labels)
      2. Scan ENTIRE sheet for AM/PM section labels (they may appear
         before OR after the header row — both happen across vendors)
      3. Assign each time-row to the right section based on position
    """
    all_rows = list(ws.iter_rows(values_only=True, max_row=500))

    # Step 1: Find movement column headers
    col_map = {}
    for i, row in enumerate(all_rows[:30]):
        matches = {}
        for ci, val in enumerate(row):
            if val is None: continue
            key = str(val).strip().upper().rstrip(':').strip()
            if key in COL_PATTERNS:
                matches[COL_PATTERNS[key]] = ci
        if len(matches) >= 3:
            col_map = matches
            break

    if not col_map:
        return None

    # Step 2: Scan WHOLE sheet for AM/PM section labels
    boundaries = []  # [(row_idx, 'AM'|'PM')]
    for i, row in enumerate(all_rows):
        if not row: continue
        first = row[0]
        if isinstance(first, str):
            u = first.strip().upper()
            if u == 'AM':
                boundaries.append((i, 'AM'))
            elif u == 'PM':
                boundaries.append((i, 'PM'))

    # Step 3: Assign each time-row to its section
    sections = {'AM': [], 'PM': []}

    def section_at(row_idx):
        """Most recent AM/PM boundary at or before row_idx."""
        current = None
        for bi, label in boundaries:
            if bi <= row_idx:
                current = label
            else:
                break
        return current

    for i, row in enumerate(all_rows):
        if not row: continue
        first = row[0]

        t = None
        if isinstance(first, dt.time):
            t = first
        elif isinstance(first, dt.datetime):
            t = first.time()
        elif isinstance(first, str):
            t = _parse_time(first)
        if t is None: continue

        # Skip rows where all movement columns are empty — these are padding rows
        # (midnight, pre-count hours, etc.) that shouldn't belong to any section
        has_data = any(
            isinstance(row[ci], (int, float)) and row[ci] is not None
            for ci in col_map.values()
            if ci < len(row)
        )
        if not has_data: continue

        if boundaries:
            section = section_at(i)
        else:
            # No explicit labels — use hour-based fallback
            if 5 <= t.hour <= 12:
                section = 'AM'
            elif 13 <= t.hour <= 20:
                section = 'PM'
            else:
                section = None

        if section in ('AM','PM'):
            sections[section].append((t, row))

    return {"col_map": col_map, "sections": sections}

# ── VERIFY ONE PERIOD ─────────────────────────────────────────────────────────
def _verify_period(structure, intr, period, peak_start):
    col_map = structure["col_map"]
    rows = structure["sections"].get(period, [])
    if not rows: return None

    try:
        ph, pm = map(int, peak_start.split(":"))
        peak_t = dt.time(ph, pm)
    except Exception:
        return None

    sorted_rows = sorted(rows, key=lambda x: (x[0].hour, x[0].minute))
    peak_idx = next((i for i,(t,_) in enumerate(sorted_rows)
                     if t.hour == peak_t.hour and t.minute == peak_t.minute), None)
    if peak_idx is None or peak_idx + 4 > len(sorted_rows):
        return None

    peak_rows = sorted_rows[peak_idx:peak_idx+4]

    # Sum each movement
    py_vols = {}
    for mv, ci in col_map.items():
        total = 0
        for _, row in peak_rows:
            v = row[ci] if ci < len(row) else None
            if isinstance(v, (int, float)):
                total += v
        py_vols[mv] = int(total)

    # Compare
    claude_vols = (intr.get("volumes") or {}).get(period) or {}
    results = {}
    for mv in MOVEMENTS:
        c = claude_vols.get(mv)
        p = py_vols.get(mv)
        if p is None:
            status = "NO_DATA"
        elif c is None:
            status = "NULL"
        elif abs(c - p) <= VOL_TOLERANCE:
            status = "VERIFIED"
        elif abs(c - p) <= 20:
            status = "CHECK"
        else:
            status = "MISMATCH"
        results[mv] = {
            "claude": c, "python": p, "status": status,
            "diff": (c - p) if (c is not None and p is not None) else None
        }

    # PHF
    iv_totals = []
    for _, row in peak_rows:
        iv = sum(row[ci] or 0 for ci in col_map.values()
                 if ci < len(row) and isinstance(row[ci], (int, float)))
        iv_totals.append(iv)

    phf_result = None
    if iv_totals and max(iv_totals) > 0:
        py_phf = round(sum(iv_totals) / (4 * max(iv_totals)), 3)
        c_phf = (intr.get("phf") or {}).get(period)
        if c_phf is None:
            status = "NULL"
        elif abs(c_phf - py_phf) <= PHF_TOLERANCE:
            status = "VERIFIED"
        elif abs(c_phf - py_phf) <= 0.05:
            status = "CHECK"
        else:
            status = "MISMATCH"
        phf_result = {"claude": c_phf, "python": py_phf, "status": status}

    return {"movements": results, "phf": phf_result}

# ── DISPLAY ───────────────────────────────────────────────────────────────────
def print_report(report):
    if report.get("status") != "OK":
        print(f"\n  Verification: {report.get('status')} — {report.get('reason','')}")
        return

    print(f"\n  {'─'*56}")
    print(f"  PYTHON VERIFICATION")
    print(f"  {'─'*56}")

    for iv in report.get("intersections", []):
        overall = iv.get("overall","?")
        sym = "✓" if overall == "VERIFIED" else "⚠" if overall == "CHECK" else "✗"
        print(f"\n  {sym} {iv['name']}  →  {overall}")

        for period, mvs in iv.get("movements", {}).items():
            active = [d for d in mvs.values() if d["status"] != "NO_DATA"]
            verified = sum(1 for d in active if d["status"] == "VERIFIED")
            print(f"    {period}: {verified}/{len(active)} verified")
            flags = [(mv,d) for mv,d in mvs.items() if d["status"] in ("MISMATCH","CHECK")]
            for mv, d in flags:
                s = "✗" if d["status"]=="MISMATCH" else "⚠"
                print(f"      {s} {mv}: Claude={d['claude']} Python={d['python']} diff={d['diff']}")

        for period, data in iv.get("phf", {}).items():
            s = "✓" if data["status"]=="VERIFIED" else "⚠" if data["status"]=="CHECK" else "✗"
            print(f"    {s} PHF {period}: Claude={data['claude']} Python={data['python']}")
