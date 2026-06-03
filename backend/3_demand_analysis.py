"""
Existing Demand Analysis Tool
WSP Traffic Engineering
Version 2.0

Usage:
    py demand_analysis_v2.py

Changes from v1.0:
    - Reads all settings from Project_Template.xlsx
    - U-turns removed — volumes added to left turns at extraction
    - Per-link balance mode (Full / Land Use / None)
    - Prohibited movement QC from LaneConfig tab
    - File validation: template vs raw folder must match
    - Seasonal factor applied if set in template

Balancing Method:
    Furness / Fratar — NCHRP 255 Chapter 8
    Balance to Average. 1% convergence threshold.
    Land Use mode: stops when link imbalance <= allowed threshold.
"""

import os, sys, re, glob, datetime, io
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as XLImage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Constants ──────────────────────────────────────────────────────────────
# No U-turns — movements are L, T, R only per approach
MOVEMENTS = [
    'NBL','NBT','NBR',
    'SBL','SBT','SBR',
    'EBL','EBT','EBR',
    'WBL','WBT','WBR',
]

# Raw file column order (0-based from col B): NL,NT,NR,NU,SL,ST,SR,SU,EL,ET,ER,EU,WL,WT,WR,WU
# U-turn (NU,SU,EU,WU) volumes are added to corresponding Left turns
RAW_COL_MAP = {
    0:'NBL', 1:'NBT', 2:'NBR', 3:'NBU_to_L',   # NBU added to NBL
    4:'SBL', 5:'SBT', 6:'SBR', 7:'SBU_to_L',   # SBU added to SBL
    8:'EBL', 9:'EBT', 10:'EBR', 11:'EBU_to_L', # EBU added to EBL
    12:'WBL', 13:'WBT', 14:'WBR', 15:'WBU_to_L' # WBU added to WBL
}

PED_LEG_MAP = {
    'N_leg': [0,1], 'S_leg': [2,3], 'E_leg': [4,5], 'W_leg': [6,7]
}

# ── Line diagram constants ─────────────────────────────────────────────────
# Styling — locked from v26 approval
DG_BLACK  = '#000000'
DG_WHITE  = '#FFFFFF'
DG_GREY   = '#969696'   # RGB 150,150,150 — road arms + arrows
DG_ARM    = 0.38        # road arm length (normalized, fixed)
DG_C      = 0.10        # arrow curve radius
DG_SP_F   = 1.5         # arrow cluster spacing factor (× s)
DG_VOL_NS = 0.9         # volume offset factor NB/SB (× s)
DG_VOL_EW = 0.7         # volume offset factor EB/WB (× s)
# Cluster centers — locked positions (SB cy+0.15 to clear title)
DG_CLUSTERS = {
    'NB': (+0.22, -0.20),   # SE quadrant
    'SB': (-0.22, +0.15),   # NW quadrant
    'EB': (-0.20, -0.20),   # SW quadrant
    'WB': (+0.20, +0.20),   # NE quadrant
}
# Base values at reference cell size (16/3" × 12/2" = 5.33" × 6.00")
DG_REF_CELL_W = 16 / 3
DG_REF_CELL_H = 12 / 2
DG_FIG_W      = 20      # fixed figure width inches
DG_FIG_H      = 15      # fixed figure height inches
DG_BASE = {
    's':        0.062,  # arrow shaft
    'lw':       2.5,    # line weight
    'hw':       0.019,  # head width
    'hl':       0.019,  # head length
    'fs_vol':   12,     # volume font
    'fs_street':10,     # street name font
    'fs_name':  12,     # intersection name font
    'fs_num':   12,     # intersection number font
    'fs_title': 16,     # page title font
}

def _dg_get_grid(n):
    """Return (cols, rows) grid that fits n intersections on one page."""
    if   n <= 4:  return 2, 2
    elif n <= 6:  return 3, 2
    elif n <= 9:  return 3, 3
    elif n <= 12: return 4, 3
    elif n <= 16: return 4, 4
    else:         return 5, 4   # max 20/page; paginate beyond

def _dg_get_preset(cols, rows):
    """Scale all parameters from reference cell size to current grid."""
    sf = min(DG_FIG_W / cols / DG_REF_CELL_W,
             DG_FIG_H / rows / DG_REF_CELL_H)
    sf = max(0.4, min(sf, 1.2))   # clamp — never too tiny or too huge
    b  = DG_BASE
    return {
        'cols':     cols,
        'rows':     rows,
        'figsize':  (DG_FIG_W, DG_FIG_H),
        's':        round(b['s']        * sf, 4),
        'lw':       max(1.2, b['lw']    * sf),
        'hw':       round(b['hw']       * sf, 4),
        'hl':       round(b['hl']       * sf, 4),
        'fs_vol':   max(6,  round(b['fs_vol']    * sf, 1)),
        'fs_street':max(5,  round(b['fs_street'] * sf, 1)),
        'fs_name':  max(6,  round(b['fs_name']   * sf, 1)),
        'fs_num':   max(6,  round(b['fs_num']    * sf, 1)),
        'fs_title': max(10, round(b['fs_title']  * sf, 1)),
        'title_y':  0.970,
        'top':      0.940,
        'sf':       sf,
    }

MAX_ITERATIONS = 200
CONVERGENCE_THRESHOLD = 0.01   # 1% relative gap — matches rounding resolution
# Rationale: rounding to nearest 5 introduces max 2.5-veh error per movement.
# At typical volumes (250-1000 veh), this equals 0.25-1.0% — within threshold.
# Tightening below 0.01 wastes iterations with no benefit after rounding.

# ── Colors ─────────────────────────────────────────────────────────────────
C_HEADER = "2F3640"; C_SUBHDR = "CFD8DC"; C_WHITE = "FFFFFF"
C_BLACK  = "000000"; C_GREEN  = "006400"; C_RED   = "CC0000"
C_AM     = "E3F2FD"; C_PM     = "FFF3E0"; C_FLAG  = "FFCCCC"
C_FORMULA= "F5F5F5"; C_INPUT  = "FFFDE7"; C_BLUE  = "0000FF"

def _fill(h): return PatternFill("solid", start_color=h, fgColor=h)
def _font(bold=False, color=C_BLACK, sz=10, italic=False):
    return Font(name="Arial", bold=bold, color=color, size=sz, italic=italic)
def _border():
    s = Side(style='thin', color="AAAAAA")
    return Border(left=s, right=s, top=s, bottom=s)
def _center(): return Alignment(horizontal='center', vertical='center', wrap_text=True)
def _left():   return Alignment(horizontal='left',   vertical='center')
def _style(cell, bg=None, font=None, align=None):
    if bg:    cell.fill = _fill(bg)
    if font:  cell.font = font
    if align: cell.alignment = align
    cell.border = _border()
def _hdr(ws, row, col, value, span=1, bg=C_HEADER, fc=C_WHITE, sz=10, bold=True):
    if span > 1:
        ws.merge_cells(start_row=row, start_column=col,
                       end_row=row, end_column=col+span-1)
    c = ws.cell(row=row, column=col, value=value)
    _style(c, bg=bg, font=_font(bold=bold, color=fc, sz=sz), align=_center())
def _subhdr(ws, row, col, value, span=1):
    _hdr(ws, row, col, value, span=span, bg=C_SUBHDR, fc=C_BLACK)
def _data(ws, row, col, value, bg=C_WHITE, color=C_BLACK, bold=False, align=None, fmt=None):
    c = ws.cell(row=row, column=col, value=value)
    _style(c, bg=bg, font=_font(bold=bold, color=color),
           align=align or _center())
    if fmt: c.number_format = fmt
    return c

# ── Step 0: CMD prompt ─────────────────────────────────────────────────────
def get_paths():
    print("\n" + "="*60)
    print("  EXISTING DEMAND ANALYSIS TOOL  |  WSP Traffic")
    print("  All project settings are read from the template.")
    print("  Only the template path is required at startup.")
    print("="*60)
    tmpl = input("\nProject template path (.xlsx): ").strip().strip('"')
    if not os.path.exists(tmpl):
        sys.exit(f"ERROR: Template not found: {tmpl}")
    return tmpl

# ── Step 1: Read template ──────────────────────────────────────────────────
def read_template(tmpl_path):
    wb = openpyxl.load_workbook(tmpl_path, data_only=True)
    cfg = {}

    # --- 1_Project ---
    ws = wb['1_Project']
    rows = {r: list(ws.iter_rows(min_row=r, max_row=r, values_only=True))[0]
            for r in range(1, 30)}
    cfg['project_name']     = rows[4][2]
    cfg['project_number']   = str(rows[5][2]) if rows[5][2] else ''
    cfg['client']           = rows[6][2]
    cfg['preparer']         = rows[7][2]
    cfg['checker']          = rows[8][2]
    cfg['date']             = rows[9][2]
    cfg['scenario']         = rows[10][2] or 'Existing'
    cfg['corridor_dir']     = rows[13][2]
    cfg['balance']          = str(rows[14][2]).strip().lower() == 'yes'
    cfg['corridor_peak']    = str(rows[15][2]).strip().lower() == 'corridor'
    cfg['bikped_method']    = rows[16][2] or 'Peak Hour'
    cfg['multiday_method']  = rows[17][2] or 'Use Highest'
    cfg['am_start']         = rows[20][2]
    cfg['am_end']           = rows[21][2]
    cfg['pm_start']         = rows[22][2]
    cfg['pm_end']           = rows[23][2]
    cfg['raw_folder']       = rows[26][2]
    cfg['output_folder']    = rows[27][2]

    print(f"\nTemplate loaded: {Path(tmpl_path).name}")
    print(f"  Project:   {cfg['project_name']}  |  Scenario: {cfg['scenario']}")
    print(f"  Corridor:  {cfg['corridor_dir']}  |  Balance: {'Yes' if cfg['balance'] else 'No'}  |  Peak: {'Corridor' if cfg['corridor_peak'] else 'Independent'}")
    print(f"  Raw data:  {cfg['raw_folder']}")
    print(f"  Output:    {cfg['output_folder']}")

    if not cfg['raw_folder']:
        sys.exit("ERROR: Raw counts folder not set in template (1_Project > Section D).")
    if not cfg['output_folder']:
        sys.exit("ERROR: Output folder not set in template (1_Project > Section D).")
    os.makedirs(cfg['output_folder'], exist_ok=True)

    # --- 2_Intersections ---
    # Corridor order = row order (row 6 = first intersection in travel direction).
    # For EB/WB: row 6 = westernmost. For NB/SB: row 6 = northernmost.
    ws2 = wb['2_Intersections']
    intersections = []
    prohibited = {}   # {int_num: [list of prohibited approach codes]}
    balance_config = {}  # {(up_int, dn_int): {'mode': str, 'threshold': int}}

    for row in ws2.iter_rows(min_row=6, values_only=True):
        if not row[0] or not isinstance(row[0], int):
            continue
        n = row[0]
        if not row[1] or str(row[1]).strip() in ('—', ''):
            continue   # blank row — stop reading
        def g(i): return row[i] if len(row) > i else None
        inter = {
            'num':           n,
            'name':          str(g(1)).strip(),
            'city':          g(2),
            'major':         g(3),
            'minor':         g(4),
            'control':       g(5),
            'lat':           g(6),
            'long':          g(7),
            'count_date':    g(8),
            'count_file':    str(g(9)).strip() if g(9) else None,
            'hv_override':   g(10),
            'am_override':   g(11),
            'pm_override':   g(12),
            'stop_detail':   g(13),
            'stopped_app':   g(14),
            'leg_N':         g(15),
            'leg_S':         g(16),
            'leg_E':         g(17),
            'leg_W':         g(18),
            'atypical':      g(26),
            # col 28 (g(27)) was old Balance Override — deprecated, ignored
            'seasonal':      g(28),
            # cols 30-31: balance config (moved from separate tab into 2_Intersections)
            'balance_mode':  str(g(29)).strip() if g(29) and str(g(29)).strip() not in ('—','') else 'Full',
            'bal_threshold': g(30),
        }
        intersections.append(inter)

    # Build balance_config from consecutive intersection pairs (corridor order = row order)
    # Each intersection's balance_mode applies to the link FROM it TO the next intersection.
    # Last intersection has no downstream link — ignored automatically.
    for i in range(len(intersections) - 1):
        up  = intersections[i]
        dn  = intersections[i + 1]
        mode = up['balance_mode'] or 'Full'
        if mode not in ('Full', 'Land Use', 'None'):
            print(f"  WARNING: Int {up['num']} balance mode '{mode}' invalid — defaulting to Full")
            mode = 'Full'
        raw_thresh = up['bal_threshold']
        threshold  = int(raw_thresh) if raw_thresh and str(raw_thresh).strip() not in ('—','') else 0
        balance_config[(up['num'], dn['num'])] = {
            'mode':      mode,
            'threshold': threshold,
        }

    # --- 3_LaneConfig ---
    ws3 = wb['3_LaneConfig']
    lane_configs = {}
    # Column layout: Int#(1), Name(2), then per-approach groups of 9 columns
    # NB: cols 3-11 | SB: cols 12-20 | EB: cols 21-29 | WB: cols 30-38
    # Each group order: L, LT, LTR, LR, T, TR, R, FreeR, Prohib?
    AP_STARTS  = {'NB': 3, 'SB': 13, 'EB': 23, 'WB': 33}
    MVMT_ORDER = ['L', 'LT', 'LTR', 'LR', 'T', 'TR', 'R', 'FreeR', 'Prohib']

    for row in ws3.iter_rows(min_row=7, values_only=True):
        if not row[0] or not isinstance(row[0], int):
            continue
        n = row[0]
        lane_configs[n] = {}
        prohib_list = []
        for ap, cs in AP_STARTS.items():
            ap_data = {}
            for mi, mvmt in enumerate(MVMT_ORDER):
                val = row[cs - 1 + mi]   # 0-based index
                ap_data[mvmt] = None if val == '—' else val
            if ap_data.get('Prohib') == 'Yes':
                prohib_list.append(ap)
            lane_configs[n][ap] = ap_data
        if prohib_list:
            prohibited[n] = prohib_list

    cfg['prohibited']    = prohibited
    cfg['balance_config'] = balance_config
    cfg['lane_configs']   = lane_configs
    return cfg, intersections

# ── Step 2: Validate files ─────────────────────────────────────────────────
def validate_files(intersections, raw_folder):
    print(f"\nValidating files in: {raw_folder}")
    if not os.path.exists(raw_folder):
        sys.exit(f"ERROR: Raw folder does not exist: {raw_folder}")

    all_files = glob.glob(os.path.join(raw_folder, "*.xlsx"))
    raw_files = sorted([f for f in all_files
                        if re.match(r'int_[0-9]+_', Path(f).stem, re.IGNORECASE)])

    errors = []
    matched = {}

    for inter in intersections:
        n = inter['num']
        # Find file matching Int_XX pattern
        pattern = re.compile(rf'^int_{n:02d}_', re.IGNORECASE)
        matches = [f for f in raw_files if pattern.match(Path(f).stem)]
        if not matches:
            errors.append(f"  MISSING: No raw file found for Int {n:02d} ({inter['name']})")
        elif len(matches) > 1:
            errors.append(f"  AMBIGUOUS: Multiple files match Int {n:02d}: {[Path(f).name for f in matches]}")
        else:
            matched[n] = matches[0]
            inter['file'] = matches[0]

    # Check for extra files not in template
    template_nums = {i['num'] for i in intersections}
    for f in raw_files:
        m = re.match(r'int_(\d+)_', Path(f).stem, re.IGNORECASE)
        if m and int(m.group(1)) not in template_nums:
            errors.append(f"  EXTRA: File {Path(f).name} has no matching intersection in template")

    if errors:
        print("\nFILE VALIDATION ERRORS:")
        for e in errors: print(e)
        sys.exit("\nFix the above errors before continuing.")

    print(f"  {len(matched)} files matched to {len(intersections)} intersections ✓")

    # Check template intersection count vs files
    if len(matched) != len(intersections):
        sys.exit(f"ERROR: Template has {len(intersections)} intersections but only {len(matched)} files matched.")

    return matched

# ── Step 3: Parse raw count file ───────────────────────────────────────────
def parse_raw_file(filepath):
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)

    def extract_interval_data(sheet_name):
        if sheet_name not in wb.sheetnames:
            return {'AM': {}, 'PM': {}}
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        sections = {}
        for i, row in enumerate(rows):
            val = row[0]
            if isinstance(val, str) and val.strip() in ['AM','NOON','PM']:
                sections[val.strip()] = i
        result = {'AM': {}, 'PM': {}}
        for period in ['AM','PM']:
            if period not in sections:
                continue
            for i in range(sections[period]+1, len(rows)):
                row = rows[i]
                val = row[0]
                if isinstance(val, datetime.time):
                    t = f"{val.hour:02d}:{val.minute:02d}"
                    mvmt = {}
                    for raw_col, mvmt_name in RAW_COL_MAP.items():
                        v = row[raw_col+1] or 0
                        # U-turn volumes → add to Left
                        if 'U_to_L' in mvmt_name:
                            left_mv = mvmt_name.replace('U_to_L','L')
                            mvmt[left_mv] = mvmt.get(left_mv, 0) + int(v)
                        else:
                            mvmt[mvmt_name] = mvmt.get(mvmt_name, 0) + int(v)
                    result[period][t] = mvmt
                elif isinstance(val, str) and val.strip() in ['AM','NOON','PM']:
                    break
        return result

    def extract_ped_data():
        if 'Data - Pedestrians (Crosswalks)' not in wb.sheetnames:
            return {'AM': {}, 'PM': {}}
        ws = wb['Data - Pedestrians (Crosswalks)']
        rows = list(ws.iter_rows(values_only=True))
        sections = {}
        for i, row in enumerate(rows):
            val = row[0]
            if isinstance(val, str) and val.strip() in ['AM','NOON','PM']:
                sections[val.strip()] = i
        result = {'AM': {}, 'PM': {}}
        for period in ['AM','PM']:
            if period not in sections:
                continue
            for i in range(sections[period]+1, len(rows)):
                row = rows[i]
                val = row[0]
                if isinstance(val, datetime.time):
                    t = f"{val.hour:02d}:{val.minute:02d}"
                    ped = {}
                    for leg, cols in PED_LEG_MAP.items():
                        ped[leg] = sum(int(row[c+1]) if row[c+1] else 0 for c in cols)
                    result[period][t] = ped
                elif isinstance(val, str) and val.strip() in ['AM','NOON','PM']:
                    break
        return result

    def sum_approach_bikes(bikes_period):
        approach = {}
        for t, mvmt in bikes_period.items():
            nb = sum(mvmt.get(f'NB{m}', 0) for m in ['L','T','R'])
            sb = sum(mvmt.get(f'SB{m}', 0) for m in ['L','T','R'])
            eb = sum(mvmt.get(f'EB{m}', 0) for m in ['L','T','R'])
            wb_v = sum(mvmt.get(f'WB{m}', 0) for m in ['L','T','R'])
            approach[t] = {'NB': nb, 'SB': sb, 'EB': eb, 'WB': wb_v}
        return approach

    ws_total = wb['Data - Total']
    meta_rows = list(ws_total.iter_rows(max_row=4, values_only=True))
    meta = {
        'location':   meta_rows[0][1] if meta_rows[0][1] else '',
        'control':    meta_rows[2][1] if meta_rows[2][1] else '',
        'date':       meta_rows[2][15] if len(meta_rows[2]) > 15 else None,
        'project_id': meta_rows[1][16] if len(meta_rows[1]) > 16 else ''
    }

    raw    = extract_interval_data('Data - Total')
    trucks = extract_interval_data('Data - Total Trucks') \
             if 'Data - Total Trucks' in wb.sheetnames else {'AM': {}, 'PM': {}}
    bikes  = extract_interval_data('Data - Total Bikes') \
             if 'Data - Total Bikes'  in wb.sheetnames else {'AM': {}, 'PM': {}}
    peds   = extract_ped_data()

    return {
        'meta':      meta,
        'am_raw':    raw['AM'],
        'pm_raw':    raw['PM'],
        'am_trucks': trucks['AM'],
        'pm_trucks': trucks['PM'],
        'am_bikes':  sum_approach_bikes(bikes['AM']),
        'pm_bikes':  sum_approach_bikes(bikes['PM']),
        'am_peds':   peds['AM'],
        'pm_peds':   peds['PM'],
    }

# ── Step 4: Candidate peak hours ──────────────────────────────────────────
def get_candidate_windows(period_raw):
    times = sorted(period_raw.keys())
    if len(times) < 4:
        return []
    def to_min(t): h,m = map(int,t.split(':')); return h*60+m
    def to_str(m): return f"{m//60:02d}:{m%60:02d}"
    time_mins = [to_min(t) for t in times]
    results = []
    for i in range(len(times)-3):
        w = [time_mins[i]+j*15 for j in range(4)]
        if all(m in time_mins for m in w):
            total = sum(sum(period_raw[to_str(m)].values()) for m in w)
            label = f"{to_str(w[0])}-{to_str(w[3]+15)}"
            results.append((label, total))
    return results

# ── Step 5: Peak hour selection ────────────────────────────────────────────
def select_peak_hours(intersections, data_map, corridor_peak):
    print("\n" + "="*60)
    print("  PEAK HOUR SELECTION")
    print("="*60)
    am_choices = {}
    pm_choices = {}

    for period in ['AM','PM']:
        raw_key = f'{period.lower()}_raw'
        print(f"\n--- {period} CANDIDATES ---")
        all_windows = set()
        cand_by_int = {}
        for inter in intersections:
            n = inter['num']
            cands = get_candidate_windows(data_map[n][raw_key])
            cand_by_int[n] = {lbl: vol for lbl, vol in cands}
            all_windows.update(cand_by_int[n].keys())
        windows = sorted(all_windows)
        col_w = 14
        print(f"  {'Int':>4}  {'Name':<28}", end="")
        for w in windows: print(f"  {w:>{col_w}}", end="")
        print(f"  {'BEST':>{col_w}}")
        print("  " + "-"*(34+(col_w+2)*len(windows)+col_w+2))

        best_per_int = {}
        for inter in intersections:
            n = inter['num']
            cands = cand_by_int[n]
            best = max(cands, key=lambda k: cands[k]) if cands else 'N/A'
            best_per_int[n] = best
            print(f"  {n:>4}  {inter['name'][:26]:<28}", end="")
            for w in windows:
                vol = cands.get(w, 0)
                marker = " *" if w == best else "  "
                print(f"  {str(vol)+marker:>{col_w}}", end="")
            print(f"  {best:>{col_w}}")

        if corridor_peak:
            from collections import Counter
            suggested = Counter(best_per_int.values()).most_common(1)[0][0]
            print(f"\n  Suggested corridor {period} peak: {suggested}")
            chosen = input(f"  Press Enter to accept or type peak hour (e.g. 07:45-08:45): ").strip()
            if not chosen: chosen = suggested
        else:
            chosen = None

        for inter in intersections:
            n = inter['num']
            if period == 'AM':
                am_choices[n] = chosen if corridor_peak else best_per_int[n]
            else:
                pm_choices[n] = chosen if corridor_peak else best_per_int[n]

    return {n: {'AM': am_choices[n], 'PM': pm_choices[n]} for n in am_choices}

# ── Step 6: Extract peak hour volumes ─────────────────────────────────────
def extract_peak_volumes(period_raw, period_trucks, peak_label, hv_override=None):
    start_str = peak_label.split('-')[0]
    h, m = map(int, start_str.split(':'))
    start_min = h*60+m
    window_mins = [start_min+i*15 for i in range(4)]
    def min_to_str(mins): return f"{mins//60:02d}:{mins%60:02d}"

    veh_totals = {mv: 0 for mv in MOVEMENTS}
    trk_totals = {mv: 0 for mv in MOVEMENTS}
    interval_totals = []

    for wm in window_mins:
        t = min_to_str(wm)
        if t in period_raw:
            row = period_raw[t]
            interval_sum = 0
            for mv in MOVEMENTS:
                v = row.get(mv, 0) or 0
                veh_totals[mv] += v
                interval_sum   += v
            interval_totals.append(interval_sum)
        else:
            interval_totals.append(0)
        if t in period_trucks:
            row = period_trucks[t]
            for mv in MOVEMENTS:
                trk_totals[mv] += row.get(mv, 0) or 0

    total_vol = sum(veh_totals.values())
    total_trk = sum(trk_totals.values())
    peak_15   = max(interval_totals) if interval_totals else 1
    phf = round(total_vol/(4*peak_15), 4) if peak_15 > 0 else 0

    if hv_override is not None:
        hv_pct = float(hv_override)
    else:
        hv_pct = round(total_trk/total_vol*100, 1) if total_vol > 0 else 0.0

    return {'vehicles': veh_totals, 'trucks': trk_totals,
            'total_vol': total_vol, 'phf': phf, 'hv_pct': hv_pct}

def extract_peak_bikes(period_bikes, peak_label):
    start_str = peak_label.split('-')[0]
    h, m = map(int, start_str.split(':'))
    start_min = h*60+m
    window_mins = [start_min+i*15 for i in range(4)]
    def min_to_str(mins): return f"{mins//60:02d}:{mins%60:02d}"
    totals = {'NB': 0, 'SB': 0, 'EB': 0, 'WB': 0}
    for wm in window_mins:
        t = min_to_str(wm)
        if t in period_bikes:
            for k in totals: totals[k] += period_bikes[t].get(k,0) or 0
    return totals

def extract_peak_peds(period_peds, peak_label):
    start_str = peak_label.split('-')[0]
    h, m = map(int, start_str.split(':'))
    start_min = h*60+m
    window_mins = [start_min+i*15 for i in range(4)]
    def min_to_str(mins): return f"{mins//60:02d}:{mins%60:02d}"
    totals = {'N_leg': 0, 'S_leg': 0, 'E_leg': 0, 'W_leg': 0}
    for wm in window_mins:
        t = min_to_str(wm)
        if t in period_peds:
            for k in totals: totals[k] += period_peds[t].get(k,0) or 0
    return totals

# ── Step 7: Rounding ───────────────────────────────────────────────────────
def round_to_5(v, original=None):
    """Round v to nearest 5, minimum 5 for any non-zero movement.
    
    Args:
        v:        Scaled/balanced float volume to round.
        original: Original unbalanced integer volume before Furness scaling.
                  If original > 0, result is floored at 5 — a counted movement
                  can never be rounded to zero. If original is None, v itself
                  determines zero vs non-zero (v < 0.5 → 0).
    """
    # Determine if this movement is truly empty
    truly_empty = (original == 0) if original is not None else (v < 0.5)
    if truly_empty:
        return 0
    # Non-zero movement: round to nearest 5, minimum 5
    return max(5, int(round(v / 5.0)) * 5)

# ── Step 8: Furness balancing ──────────────────────────────────────────────
def balance_corridor(intersections, unbalanced_vols, corridor_dir, period,
                     balance_config=None):
    """
    Furness / Fratar — NCHRP 255 Chapter 8. Balance to Average.
    Per-link mode from balance_config: Full / Land Use / None.
    U-turns excluded (already removed from MOVEMENTS).
    """
    if corridor_dir == 'EB/WB':
        links = []
        for i in range(len(intersections)-1):
            up = intersections[i]['num']
            dn = intersections[i+1]['num']
            links.append((up, dn, 'EB', 'EB'))
            links.append((dn, up, 'WB', 'WB'))
    else:
        links = []
        for i in range(len(intersections)-1):
            up = intersections[i]['num']
            dn = intersections[i+1]['num']
            links.append((up, dn, 'NB', 'NB'))
            links.append((dn, up, 'SB', 'SB'))

    vols = {n: {mv: float(v) for mv, v in mvmt.items()}
            for n, mvmt in unbalanced_vols.items()}
    conv_log = []
    adjustments = []
    bc = balance_config or {}

    for iteration in range(1, MAX_ITERATIONS+1):
        max_gap = 0.0

        for (up_int, dn_int, out_dir, in_dir) in links:
            # Get link-specific balance config
            link_cfg = bc.get((up_int, dn_int), {'mode': 'Full', 'threshold': 0})
            mode      = link_cfg.get('mode', 'Full')
            threshold = link_cfg.get('threshold', 0)

            if mode == 'None':
                continue

            out_vol = vols[up_int].get(f'{out_dir}T', 0)
            in_vol  = vols[dn_int].get(f'{in_dir}T', 0)
            if out_vol + in_vol == 0:
                continue

            target = (out_vol + in_vol) / 2.0
            gap = abs(out_vol - in_vol) / target if target > 0 else 0

            # Land Use mode: stop if within allowed threshold
            if mode == 'Land Use' and abs(out_vol - in_vol) <= threshold:
                continue

            max_gap = max(max_gap, gap)
            if gap <= CONVERGENCE_THRESHOLD:
                continue

            # Row scaling: upstream approach (excl. U-turns — already removed)
            up_moves = [mv for mv in MOVEMENTS if mv.startswith(out_dir)]
            if out_vol > 0:
                rf = target / out_vol
                for mv in up_moves:
                    old = vols[up_int][mv]
                    vols[up_int][mv] = old * rf
                    if abs(old - vols[up_int][mv]) > 0.01:
                        adjustments.append((iteration, up_int, mv, vols[up_int][mv]-old))

            # Column scaling: downstream approach
            dn_moves = [mv for mv in MOVEMENTS if mv.startswith(in_dir)]
            if in_vol > 0:
                cf = target / in_vol
                for mv in dn_moves:
                    old = vols[dn_int][mv]
                    vols[dn_int][mv] = old * cf
                    if abs(old - vols[dn_int][mv]) > 0.01:
                        adjustments.append((iteration, dn_int, mv, vols[dn_int][mv]-old))

        conv_log.append({'iteration': iteration, 'max_relative_gap': round(max_gap, 6)})
        if max_gap <= CONVERGENCE_THRESHOLD:
            print(f"  [{period}] Converged at iteration {iteration} | gap = {max_gap:.4%}")
            break
    else:
        print(f"  [{period}] WARNING: Did not converge in {MAX_ITERATIONS} iterations | gap = {max_gap:.4%}")

    # Round to nearest 5, flooring at 5 for any movement with original vol > 0
    rounded = {
        n: {
            mv: round_to_5(v, original=unbalanced_vols[n].get(mv, 0))
            for mv, v in mvmt.items()
        }
        for n, mvmt in vols.items()
    }
    return rounded, conv_log, adjustments

# ── Step 9: QC ────────────────────────────────────────────────────────────
def run_qc(intersections, data_map, extracted, peak_choices,
           balanced_am, balanced_pm, corridor_peak, prohibited, corridor_dir):
    flags = []

    for inter in intersections:
        n = inter['num']

        # QC-01: Missing lat/long
        if not inter.get('lat') or not inter.get('long'):
            flags.append({'check':'QC-01','int':n,'period':'—',
                'message':f"Int {n}: Missing Lat/Long in template"})

        # QC-02: Atypical day
        if str(inter.get('atypical','')).lower() == 'yes':
            flags.append({'check':'QC-02','int':n,'period':'—',
                'message':f"Int {n}: Flagged as ATYPICAL count day — verify before use"})

        # QC-03: Peak hour deviation
        if corridor_peak:
            for period in ['AM','PM']:
                raw_key = f'{period.lower()}_raw'
                cands = get_candidate_windows(data_map[n][raw_key])
                if cands:
                    best_vol = max(v for _,v in cands)
                    chosen   = peak_choices[n][period]
                    chosen_vol = next((v for l,v in cands if l==chosen), 0)
                    if best_vol > 0 and chosen_vol > 0:
                        dev = abs(best_vol-chosen_vol)/best_vol
                        if dev > 0.10:
                            flags.append({'check':'QC-03','int':n,'period':period,
                                'message':f"Int {n} {period}: own peak deviates {dev:.1%} from corridor peak"})

        for period in ['AM','PM']:
            ext = extracted[n][period]
            # QC-04: HV% > 15%
            if ext['hv_pct'] > 15:
                flags.append({'check':'QC-04','int':n,'period':period,
                    'message':f"Int {n} {period}: HV% = {ext['hv_pct']:.1f}% > 15%"})
            # QC-05: PHF out of range
            if ext['phf'] < 0.60 or ext['phf'] > 1.00:
                flags.append({'check':'QC-05','int':n,'period':period,
                    'message':f"Int {n} {period}: PHF = {ext['phf']:.4f} out of range"})
            # QC-06: Zero approach volume
            vols = ext['vehicles']
            for direction in ['NB','SB','EB','WB']:
                dir_total = sum(vols.get(f'{direction}{m}',0) for m in ['L','T','R'])
                if dir_total == 0:
                    flags.append({'check':'QC-06','int':n,'period':period,
                        'message':f"Int {n} {period}: {direction} approach is zero — verify if stub"})

        # QC-07: Prohibited movement has non-zero volume
        if n in prohibited:
            for ap in prohibited[n]:
                for period in ['AM','PM']:
                    vols = extracted[n][period]['vehicles']
                    ap_total = sum(vols.get(f'{ap}{m}',0) for m in ['L','T','R'])
                    if ap_total > 0:
                        flags.append({'check':'QC-07','int':n,'period':period,
                            'message':f"Int {n} {period}: {ap} approach marked prohibited but has {ap_total} vehicles in count data"})

    # QC-08: Post-balance residual.
    # Corridor adjacency = ROW order (2_Intersections) — the same pairing
    # balance_config / balance_corridor use. NOT sorted(int numbers), which only
    # matched when IDs were entered in ascending corridor order.
    # Through-movement pair follows the corridor direction:
    #   EB/WB → forward=EBT (row order, west→east), reverse=WBT
    #   NB/SB → forward=NBT (row order, north→south), reverse=SBT
    if corridor_dir == 'NB/SB':
        fwd_mv, rev_mv, fwd_lbl, rev_lbl = 'NBT', 'SBT', 'NB', 'SB'
    else:  # EB/WB
        fwd_mv, rev_mv, fwd_lbl, rev_lbl = 'EBT', 'WBT', 'EB', 'WB'
    order = [it['num'] for it in intersections]      # row 6 = corridor origin
    for period, bal in [('AM',balanced_am),('PM',balanced_pm)]:
        if not bal: continue
        for i in range(len(order)-1):
            up, dn = order[i], order[i+1]             # up = upstream in corridor order
            if up not in bal or dn not in bal:        # skip ints that didn't balance
                continue
            fwd_gap = abs(bal[up].get(fwd_mv,0) - bal[dn].get(fwd_mv,0))
            rev_gap = abs(bal[dn].get(rev_mv,0) - bal[up].get(rev_mv,0))
            if fwd_gap > 5:
                flags.append({'check':'QC-08','int':up,'period':period,
                    'message':f"Int {up}→{dn} {period} {fwd_lbl}: residual gap {fwd_gap} veh after balancing"})
            if rev_gap > 5:
                flags.append({'check':'QC-08','int':dn,'period':period,
                    'message':f"Int {dn}→{up} {period} {rev_lbl}: residual gap {rev_gap} veh after balancing"})

    return flags

# ── Step 10: Write output Excel ────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# LINE DIAGRAM ENGINE — v26 APPROVED + DYNAMIC GRID + LEGEND BAR
# Arrow geometry, colours, cluster positions: locked from v26
# Grid and font scaling: auto from intersection count via _dg_get_preset()
# Legend: horizontal bar below grid on every page
# ══════════════════════════════════════════════════════════════════════════════

from matplotlib.patches import Polygon as MplPolygon, Circle as MplCircle

def _dg_arrow(ax, x0, y0, x1, y1, curve=0.0, lw=2.5, hw=0.019, hl=0.019):
    """Draw bezier arrow in DG_GREY with given line/head params."""
    if curve == 0:
        dx=x1-x0; dy=y1-y0; ln=np.sqrt(dx**2+dy**2)
        if ln < 1e-6: return
        sx=x1-(hl*dx/ln); sy=y1-(hl*dy/ln)
        ax.plot([x0,sx],[y0,sy], color=DG_GREY, lw=lw,
                solid_capstyle='round', zorder=8)
        a=np.arctan2(dy,dx); tip=np.array([x1,y1])
        L=tip+hw*np.array([-np.sin(a),np.cos(a)])-hl*np.array([np.cos(a),np.sin(a)])
        R=tip-hw*np.array([-np.sin(a),np.cos(a)])-hl*np.array([np.cos(a),np.sin(a)])
        ax.add_patch(MplPolygon([tip,L,R], closed=True,
                     facecolor=DG_GREY, edgecolor=DG_GREY, lw=0.5, zorder=9))
    else:
        mx=(x0+x1)/2; my=(y0+y1)/2; dx=x1-x0; dy=y1-y0
        px=-dy; py=dx; n=np.sqrt(px**2+py**2)
        if n > 0: px/=n; py/=n
        cx2=mx+curve*px; cy2=my+curve*py
        t=np.linspace(0, 0.85, 40)
        xs=(1-t)**2*x0+2*(1-t)*t*cx2+t**2*x1
        ys=(1-t)**2*y0+2*(1-t)*t*cy2+t**2*y1
        ax.plot(xs, ys, color=DG_GREY, lw=lw, solid_capstyle='round', zorder=8)
        te=0.92
        tx=2*(1-te)*(cx2-x0)+2*te*(x1-cx2)
        ty=2*(1-te)*(cy2-y0)+2*te*(y1-cy2)
        a=np.arctan2(ty,tx); tip=np.array([x1,y1])
        L=tip+hw*np.array([-np.sin(a),np.cos(a)])-hl*np.array([np.cos(a),np.sin(a)])
        R=tip-hw*np.array([-np.sin(a),np.cos(a)])-hl*np.array([np.cos(a),np.sin(a)])
        ax.add_patch(MplPolygon([tip,L,R], closed=True,
                     facecolor=DG_GREY, edgecolor=DG_GREY, lw=0.5, zorder=9))


def _dg_get_arrow(ap, mv, cx, cy, s):
    """Arrow geometry — approved from v26. s = arrow shaft scale."""
    c = DG_C
    if ap == 'NB':
        if mv == 'L': return cx,       cy-s*0.35, cx-s*0.9, cy+s*0.4, -c
        if mv == 'T': return cx,       cy-s*0.5,  cx,       cy+s*0.5,  0
        if mv == 'R': return cx,       cy-s*0.35, cx+s*0.9, cy+s*0.4, +c
    elif ap == 'SB':
        if mv == 'L': return cx,       cy+s*0.35, cx+s*0.9, cy-s*0.4, -c
        if mv == 'T': return cx,       cy+s*0.5,  cx,       cy-s*0.5,  0
        if mv == 'R': return cx,       cy+s*0.35, cx-s*0.9, cy-s*0.4, +c
    elif ap == 'EB':
        if mv == 'L': return cx-s*0.35, cy,        cx+s*0.4, cy+s*0.9, -c
        if mv == 'T': return cx-s*0.5,  cy,        cx+s*0.5, cy,        0
        if mv == 'R': return cx-s*0.35, cy,        cx+s*0.4, cy-s*0.9, +c
    elif ap == 'WB':
        if mv == 'L': return cx+s*0.35, cy,        cx-s*0.4, cy-s*0.9, -c
        if mv == 'T': return cx+s*0.5,  cy,        cx-s*0.5, cy,        0
        if mv == 'R': return cx+s*0.35, cy,        cx-s*0.4, cy+s*0.9, +c
    return None


def _dg_lane_positions(ap, qcx, qcy, sp):
    """Lane positions median→curb for each approach."""
    if ap == 'NB':   return [('L',qcx-sp,qcy), ('T',qcx,qcy), ('R',qcx+sp,qcy)]
    elif ap == 'SB': return [('L',qcx+sp,qcy), ('T',qcx,qcy), ('R',qcx-sp,qcy)]
    elif ap == 'EB': return [('L',qcx,qcy+sp),  ('T',qcx,qcy), ('R',qcx,qcy-sp)]
    elif ap == 'WB': return [('L',qcx,qcy-sp),  ('T',qcx,qcy), ('R',qcx,qcy+sp)]
    return []


def _dg_stop_sign(ax, ap, cx, cy):
    """Stop sign with bar facing approaching traffic. pos=0.06 from center."""
    r=0.016; sl=0.030; sk=0.020; off=0.038; pos=0.06; lw_s=1.3
    if ap == 'NB':
        ox,oy = cx+off, cy-pos
        ax.plot([ox,ox],[oy+r,oy+r+sk], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox,oy), r, facecolor=DG_WHITE,
                     edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox-sl,ox+sl],[oy-r,oy-r], color=DG_BLACK, lw=lw_s*1.4, zorder=9)
    elif ap == 'SB':
        ox,oy = cx-off, cy+pos
        ax.plot([ox,ox],[oy-r-sk,oy-r], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox,oy), r, facecolor=DG_WHITE,
                     edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox-sl,ox+sl],[oy+r,oy+r], color=DG_BLACK, lw=lw_s*1.4, zorder=9)
    elif ap == 'EB':
        ox,oy = cx-pos, cy-off
        ax.plot([ox+r,ox+r+sk],[oy,oy], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox,oy), r, facecolor=DG_WHITE,
                     edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox-r,ox-r],[oy-sl,oy+sl], color=DG_BLACK, lw=lw_s*1.4, zorder=9)
    elif ap == 'WB':
        ox,oy = cx+pos, cy+off
        ax.plot([ox-r-sk,ox-r],[oy,oy], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox,oy), r, facecolor=DG_WHITE,
                     edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox+r,ox+r],[oy-sl,oy+sl], color=DG_BLACK, lw=lw_s*1.4, zorder=9)


def _dg_draw_approach(ax, ap, cx, cy, u_vols, b_vols, p):
    """Draw 3 arrows + volume labels for one approach using preset p."""
    s   = p['s']
    sp  = s * DG_SP_F
    lw  = p['lw']; hw = p['hw']; hl = p['hl']
    dx, dy = DG_CLUSTERS[ap]
    qcx, qcy = cx + dx, cy + dy
    lanes = _dg_lane_positions(ap, qcx, qcy, sp)
    vns = s * DG_VOL_NS
    vew = s * DG_VOL_EW
    fs  = p['fs_vol']

    for mv, ax_, ay_ in lanes:
        geom = _dg_get_arrow(ap, mv, ax_, ay_, s)
        if geom is None: continue
        x0,y0,x1,y1,cv = geom
        _dg_arrow(ax, x0, y0, x1, y1, curve=cv, lw=lw, hw=hw, hl=hl)
        key = f"{ap}{mv}"
        u = int(u_vols.get(key, 0) or 0)
        b = int(b_vols.get(key, 0) or 0)
        lbl = f"{u} ({b})"
        if ap == 'NB':
            ax.text(ax_, ay_-vns, lbl, fontsize=fs, color=DG_BLACK,
                    rotation=90, ha='center', va='top', zorder=10)
        elif ap == 'SB':
            ax.text(ax_, ay_+vns, lbl, fontsize=fs, color=DG_BLACK,
                    rotation=90, ha='center', va='bottom', zorder=10)
        elif ap == 'EB':
            ax.text(ax_-vew, ay_, lbl, fontsize=fs, color=DG_BLACK,
                    ha='right', va='center', zorder=10)
        elif ap == 'WB':
            ax.text(ax_+vew, ay_, lbl, fontsize=fs, color=DG_BLACK,
                    ha='left', va='center', zorder=10)


def _dg_draw_cell(ax, geo, u_vols, b_vols, p):
    """Draw one intersection cell using preset p."""
    active  = geo.get('active_legs', ['NB','SB','EB','WB'])
    control = geo.get('control', 'Signalized')
    streets = geo.get('streets', {})
    n, name = geo['num'], geo['name']
    arm     = DG_ARM

    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_aspect('equal')
    ax.set_facecolor(DG_WHITE)
    for side in ['top','bottom','left','right']:
        ax.spines[side].set_visible(True)
        ax.spines[side].set_linewidth(0.8)
        ax.spines[side].set_color(DG_BLACK)
    ax.set_xticks([]); ax.set_yticks([])

    cx, cy = 0.5, 0.5
    rk = dict(color=DG_GREY, lw=2.8, solid_capstyle='butt', zorder=5)
    if 'NB' in active: ax.plot([cx,cx],[cy,cy-arm], **rk)
    if 'SB' in active: ax.plot([cx,cx],[cy,cy+arm], **rk)
    if 'EB' in active: ax.plot([cx,cx-arm],[cy,cy], **rk)
    if 'WB' in active: ax.plot([cx,cx+arm],[cy,cy], **rk)

    if 'Signal' in control:
        ax.add_patch(MplCircle((cx,cy), 0.022, facecolor=DG_WHITE,
                     edgecolor=DG_BLACK, lw=1.5, zorder=6))
    else:
        ax.plot(cx, cy, 'k.', markersize=4, zorder=6)
        for ap in geo.get('stopped_approaches', []):
            _dg_stop_sign(ax, ap, cx, cy)

    ns = streets.get('NS',''); ew = streets.get('EW','')
    nk = dict(fontsize=p['fs_street'], color=DG_BLACK, fontweight='bold',
              ha='center', va='center', zorder=7)
    if ns:
        if 'NB' in active: ax.text(cx-0.052, cy-arm*0.70, ns, rotation=90, **nk)
        if 'SB' in active: ax.text(cx+0.052, cy+arm*0.70, ns, rotation=90, **nk)
    if ew:
        if 'EB' in active: ax.text(cx-arm*0.70, cy+0.044, ew, **nk)
        if 'WB' in active: ax.text(cx+arm*0.70, cy-0.044, ew, **nk)

    for ap in active:
        _dg_draw_approach(ax, ap, cx, cy, u_vols, b_vols, p)

    ax.add_patch(MplCircle((0.082,0.922), 0.048, facecolor=DG_WHITE,
                 edgecolor=DG_BLACK, lw=1.0, zorder=10))
    ax.text(0.082, 0.922, str(n), fontsize=p['fs_num'], color=DG_BLACK,
            fontweight='bold', ha='center', va='center', zorder=11)
    ax.text(0.5, 0.955, name.replace(' & ', ' @ '), fontsize=p['fs_name'],
            color=DG_BLACK, fontweight='bold', ha='center', va='center')


def _dg_legend_bar(fig, p):
    """Horizontal legend bar below grid. Icons are square axes to ensure
    circles render as circles not ovals."""
    fs   = max(7, p['fs_street'])
    ly   = 0.032   # vertical center in figure coords
    lh   = 0.040   # icon height in figure coords
    # Square icon: width adjusted for figure aspect ratio
    lw_f = lh * (DG_FIG_H / DG_FIG_W)

    # Separator line
    fig.add_artist(plt.Line2D([0.02, 0.98],[0.058, 0.058],
                   transform=fig.transFigure, color='#AAAAAA', lw=0.8))

    # "Legend:" label
    fig.text(0.02, ly, 'Legend:', fontsize=fs, color=DG_BLACK,
             fontweight='bold', ha='left', va='center')

    icon_xs = [0.16, 0.33, 0.51, 0.69, 0.84]
    gap = 0.018   # gap between icon right edge and text

    # ── 1. Turn Lane arrow ────────────────────────────────────────────────
    ix = icon_xs[0]
    axa = fig.add_axes([ix-lw_f/2, ly-lh/2, lw_f, lh])
    axa.set_xlim(0,1); axa.set_ylim(0,1); axa.set_aspect('equal'); axa.axis('off')
    x0,y0,x1,y1 = 0.15,0.15,0.82,0.82
    mx=(x0+x1)/2; my=(y0+y1)/2; dx=x1-x0; dy=y1-y0
    px=-dy; py=dx; nn=np.sqrt(px**2+py**2)
    if nn > 0: px/=nn; py/=nn
    cv=-0.28; cx2=mx+cv*px; cy2=my+cv*py
    t=np.linspace(0,0.80,30)
    xs=(1-t)**2*x0+2*(1-t)*t*cx2+t**2*x1
    ys=(1-t)**2*y0+2*(1-t)*t*cy2+t**2*y1
    axa.plot(xs,ys,color=DG_GREY,lw=2.0,solid_capstyle='round')
    te=0.92
    tx=2*(1-te)*(cx2-x0)+2*te*(x1-cx2)
    tya=2*(1-te)*(cy2-y0)+2*te*(y1-cy2)
    a=np.arctan2(tya,tx); tip=np.array([x1,y1]); hw=0.20; hl=0.20
    L=tip+hw*np.array([-np.sin(a),np.cos(a)])-hl*np.array([np.cos(a),np.sin(a)])
    R=tip-hw*np.array([-np.sin(a),np.cos(a)])-hl*np.array([np.cos(a),np.sin(a)])
    axa.add_patch(MplPolygon([tip,L,R],closed=True,facecolor=DG_GREY,edgecolor=DG_GREY,lw=0.5))
    fig.text(ix+lw_f/2+gap, ly, 'Turn Lane',
             fontsize=fs, color=DG_BLACK, ha='left', va='center')

    # ── 2. Volume format ──────────────────────────────────────────────────
    ix = icon_xs[1]
    fig.text(ix-0.018, ly, 'XX (YY)', fontsize=fs, color=DG_BLACK,
             fontweight='bold', ha='left', va='center')
    fig.text(ix+0.028, ly, 'AM (PM) Peak Hour Volume',
             fontsize=fs, color=DG_BLACK, ha='left', va='center')

    # ── 3. Study Intersection ─────────────────────────────────────────────
    ix = icon_xs[2]
    axc = fig.add_axes([ix-lw_f/2, ly-lh/2, lw_f, lh])
    axc.set_xlim(0,1); axc.set_ylim(0,1); axc.set_aspect('equal'); axc.axis('off')
    axc.add_patch(MplCircle((0.5,0.5), 0.44, facecolor=DG_WHITE,
                  edgecolor=DG_BLACK, lw=1.2))
    axc.text(0.5,0.5,'1', fontsize=fs, color=DG_BLACK,
             fontweight='bold', ha='center', va='center')
    fig.text(ix+lw_f/2+gap, ly, 'Study Intersection',
             fontsize=fs, color=DG_BLACK, ha='left', va='center')

    # ── 4. Traffic Signal ─────────────────────────────────────────────────
    ix = icon_xs[3]
    axs = fig.add_axes([ix-lw_f/2, ly-lh/2, lw_f, lh])
    axs.set_xlim(0,1); axs.set_ylim(0,1); axs.set_aspect('equal'); axs.axis('off')
    axs.add_patch(MplCircle((0.5,0.5), 0.42, facecolor=DG_WHITE,
                  edgecolor=DG_BLACK, lw=1.5))
    fig.text(ix+lw_f/2+gap, ly, 'Traffic Signal',
             fontsize=fs, color=DG_BLACK, ha='left', va='center')

    # ── 5. Stop Sign ──────────────────────────────────────────────────────
    ix = icon_xs[4]
    axst = fig.add_axes([ix-lw_f/2, ly-lh/2, lw_f, lh])
    axst.set_xlim(0,1); axst.set_ylim(0,1); axst.set_aspect('equal'); axst.axis('off')
    axst.add_patch(MplCircle((0.5,0.52), 0.34, facecolor=DG_WHITE,
                   edgecolor=DG_BLACK, lw=1.2))
    axst.plot([0.5,0.5],[0.86,1.00], color=DG_BLACK, lw=1.2)   # pole
    axst.plot([0.20,0.80],[0.18,0.18], color=DG_BLACK, lw=2.0)  # bar (sign face)
    fig.text(ix+lw_f/2+gap, ly, 'Stop Sign',
             fontsize=fs, color=DG_BLACK, ha='left', va='center')


def _generate_page_figure(page_ints, geo_map, u_map, b_map,
                           period, project_name, scenario,
                           page_num, total_pages, p):
    """Render one page using dynamic preset p."""
    cols = p['cols']; rows = p['rows']
    fig, axes = plt.subplots(rows, cols, figsize=p['figsize'], facecolor=DG_WHITE)
    fig.patch.set_facecolor(DG_WHITE)
    if rows == 1 and cols == 1: axes = np.array([[axes]])
    elif rows == 1:              axes = axes.reshape(1,-1)
    elif cols == 1:              axes = axes.reshape(-1,1)

    for idx, n in enumerate(page_ints):
        r, c = divmod(idx, cols)
        geo  = geo_map.get(n)
        if not geo:
            axes[r][c].axis('off'); continue
        _dg_draw_cell(axes[r][c], geo,
                      u_map.get(n, {}),
                      b_map.get(n, u_map.get(n, {})), p)

    for idx in range(len(page_ints), rows * cols):
        r, c = divmod(idx, cols); axes[r][c].axis('off')

    plt.tight_layout(pad=0.3)
    plt.subplots_adjust(hspace=0.08, wspace=0.06,
                        top=p['top'], bottom=0.07)
    _dg_legend_bar(fig, p)

    title_str = (f"{project_name}  —  {scenario}  |  {period} Peak Hour  |  "
                 f"Page {page_num} of {total_pages}")
    plt.suptitle(title_str, fontsize=p['fs_title'], fontweight='bold',
                 y=p['title_y'], ha='center', va='center')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=220, bbox_inches='tight', facecolor=DG_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf


def _write_line_diagrams(wb, intersections, extracted, balanced_am, balanced_pm,
                          lane_configs, cfg):
    """Add line diagram sheets. Grid and scale auto-selected from intersection count."""
    import math

    # Build geometry map
    geo_map = {}
    for inter in intersections:
        n  = inter['num']
        lc = lane_configs.get(n, {})
        legs = []
        for ap in ['NB','SB','EB','WB']:
            ap_data = lc.get(ap, {})
            if ap_data and ap_data.get('L') != '—' and ap_data.get('L') is not None:
                legs.append(ap)
        if not legs:
            legs = ['NB','SB','EB','WB']

        control     = inter.get('control', 'Signalized')
        stopped_str = inter.get('stopped_app', '') or ''
        stopped     = [s.strip().upper() for s in str(stopped_str).split(',')
                       if s.strip().upper() in ['NB','SB','EB','WB']]

        geo_map[n] = {
            'num':                n,
            'name':               inter['name'],
            'control':            control,
            'active_legs':        legs,
            'stopped_approaches': stopped,
            'streets': {
                'NS': inter.get('minor', ''),
                'EW': inter.get('major', ''),
            }
        }

    # Dynamic grid — select once for the whole run based on total count
    total_ints  = len(intersections)
    cols, rows  = _dg_get_grid(total_ints)
    p           = _dg_get_preset(cols, rows)
    per_page    = cols * rows
    int_nums    = [i['num'] for i in intersections]
    pages       = [int_nums[i:i+per_page] for i in range(0, len(int_nums), per_page)]
    total_pgs   = len(pages)
    project_nm  = cfg.get('project_name', 'Project')
    scenario    = cfg.get('scenario', 'Existing')

    print(f"    Grid: {cols}×{rows}, {per_page}/page, {total_pgs} page(s), "
          f"scale={p['sf']:.2f}, vol={p['fs_vol']}pt, s={p['s']}")

    for period in ['AM', 'PM']:
        u_map = {n: extracted[n][period]['vehicles']
                 for n in int_nums if n in extracted}
        b_map = (balanced_am if period == 'AM' else balanced_pm) or u_map

        for pg_num, pg_ints in enumerate(pages, 1):
            sname = f"{period}_Diagrams_Pg{pg_num}"
            ws    = wb.create_sheet(sname)
            ws.sheet_view.showGridLines = False

            ws.merge_cells('A1:L1')
            c = ws.cell(row=1, column=1,
                        value=(f"{project_nm}  |  {scenario}  |  {period} Peak  |  "
                               f"Int {pg_ints[0]:02d}–{pg_ints[-1]:02d}  |  "
                               f"Page {pg_num}/{total_pgs}  |  "
                               f"Volumes: Unbalanced (Balanced)"))
            c.fill      = PatternFill('solid', start_color='2F3640', fgColor='2F3640')
            c.font      = Font(name='Arial', bold=True, color='FFFFFF', size=10)
            c.alignment = Alignment(horizontal='center', vertical='center')
            ws.row_dimensions[1].height = 20

            print(f"    Generating {sname}: {len(pg_ints)} intersections...")
            buf = _generate_page_figure(
                pg_ints, geo_map, u_map, b_map,
                period, project_nm, scenario, pg_num, total_pgs, p
            )
            img        = XLImage(buf)
            img.width  = 1200
            img.height = 900
            ws.add_image(img, 'A2')
            ws.row_dimensions[2].height = 680
            for ci in range(1, 13):
                ws.column_dimensions[get_column_letter(ci)].width = 14


def write_output(cfg, intersections, data_map, extracted, peak_choices,
                 balanced_am, balanced_pm, conv_log_am, conv_log_pm,
                 qc_flags, adj_am, adj_pm, _data_map=None):
    # _data_map kept for backward compat; data_map is the same arg
    _data_map = data_map

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _write_registry(wb, intersections, data_map, extracted, peak_choices, balanced_am, balanced_pm, cfg)
    _write_peak_selection(wb, intersections, data_map, peak_choices, cfg['corridor_peak'])

    for inter in intersections:
        n = inter['num']
        _write_int_sheet(wb, inter, data_map[n], extracted[n], peak_choices[n])

    _write_balance_sheet(wb, 'AM_Unbalanced', intersections, extracted, 'AM')
    _write_balance_sheet(wb, 'AM_Balanced',   intersections, extracted, 'AM',
                         balanced=True, balanced_vols=balanced_am)
    _write_balance_sheet(wb, 'PM_Unbalanced', intersections, extracted, 'PM')
    _write_balance_sheet(wb, 'PM_Balanced',   intersections, extracted, 'PM',
                         balanced=True, balanced_vols=balanced_pm)
    _write_conv_log(wb, conv_log_am, conv_log_pm, adj_am, adj_pm)
    _write_qc(wb, qc_flags)

    # Line diagrams — appended to same workbook
    print("\nGenerating line diagram sheets...")
    _write_line_diagrams(wb, intersections, extracted, balanced_am, balanced_pm,
                         cfg.get('lane_configs', {}), cfg)

    fname = f"{cfg['project_name'].replace(' ','_')}_{cfg['scenario'].replace(' ','_')}_Demand.xlsx"
    outpath = os.path.join(cfg['output_folder'], fname)
    wb.save(outpath)
    return outpath

def _write_registry(wb, intersections, data_map, extracted, peak_choices,
                    balanced_am, balanced_pm, cfg):
    ws = wb.create_sheet("Registry")
    ws.sheet_view.showGridLines = False

    _hdr(ws, 1, 1, f"{cfg['project_name']} — {cfg['scenario']} — MASTER VOLUME TABLE",
         span=24, sz=12)

    # Section A
    _hdr(ws, 3, 1, "SECTION A — INTERSECTION INFORMATION", span=10, sz=10)
    info_hdrs = ["Int #","Name","City","Control","Lat","Long",
                 "Count Date","Count File","AM Peak Hour","PM Peak Hour"]
    for ci, h in enumerate(info_hdrs, 1): _subhdr(ws, 4, ci, h)
    ws.column_dimensions['A'].width = 6
    ws.column_dimensions['B'].width = 32
    for col in range(3,25): ws.column_dimensions[get_column_letter(col)].width = 14

    for inter in intersections:
        n   = inter['num']
        r   = 4 + n
        meta = data_map.get(n, {}).get('meta', {})
        vals = [n, inter['name'], inter.get('city',''), inter.get('control',''),
                inter.get('lat',''), inter.get('long',''),
                str(meta.get('date','')) if meta.get('date') else '',
                inter.get('count_file',''),
                peak_choices[n]['AM'], peak_choices[n]['PM']]
        for ci, val in enumerate(vals, 1):
            _data(ws, r, ci, val, align=_left() if ci==2 else _center())

    # Section C master volume table
    mv_start = 4 + len(intersections) + 3
    _hdr(ws, mv_start, 1, "SECTION C — MASTER VOLUME TABLE (Balanced)", span=24, sz=10)

    grps = [(1,1,"Int #"),(2,2,"Period"),(3,5,"NORTHBOUND"),(6,8,"SOUTHBOUND"),
            (9,11,"EASTBOUND"),(12,14,"WESTBOUND"),
            (15,15,"PHF"),(16,16,"HV%"),
            (17,20,"BIKES"),(21,24,"PEDS")]
    for cs,ce,label in grps: _subhdr(ws, mv_start+1, cs, label, span=ce-cs+1)

    mvmt_hdrs = ["Int #","Period"] + MOVEMENTS + ["PHF","HV%",
                 "Bike NB","Bike SB","Bike EB","Bike WB",
                 "Ped N","Ped S","Ped E","Ped W"]
    for ci, h in enumerate(mvmt_hdrs, 1): _subhdr(ws, mv_start+2, ci, h)

    for inter in intersections:
        n = inter['num']
        for pi, period in enumerate(['AM','PM']):
            row = mv_start + 3 + (n-1)*2 + pi
            bal = (balanced_am if period=='AM' else balanced_pm)
            vols = bal[n] if bal and n in bal else extracted[n][period]['vehicles']
            phf  = extracted[n][period]['phf']
            hv   = extracted[n][period]['hv_pct']
            bikes= extracted[n][period]['bikes']
            peds = extracted[n][period]['peds']
            bg   = C_AM if period=='AM' else C_PM
            _data(ws, row, 1, n, bold=True)
            _data(ws, row, 2, period, bg=bg, bold=True)
            for mi, mv in enumerate(MOVEMENTS, 3):
                _data(ws, row, mi, vols.get(mv,0))
            _data(ws, row, 15, phf, fmt='0.000')
            _data(ws, row, 16, f"{hv:.1f}%")
            for ci, k in enumerate(['NB','SB','EB','WB'], 17):
                _data(ws, row, ci, bikes.get(k,0))
            for ci, k in enumerate(['N_leg','S_leg','E_leg','W_leg'], 21):
                _data(ws, row, ci, peds.get(k,0))

def _write_peak_selection(wb, intersections, data_map, peak_choices, corridor_peak):
    ws = wb.create_sheet("PeakHour_Selection")
    ws.sheet_view.showGridLines = False
    _hdr(ws, 1, 1, "PEAK HOUR SELECTION", span=20, sz=12)
    for pi, period in enumerate(['AM','PM']):
        raw_key = f'{period.lower()}_raw'
        base    = 3 + pi*(len(intersections)+5)
        _hdr(ws, base, 1, f"{period} — CANDIDATE PEAK HOUR TOTALS", span=15, sz=10)
        all_w = set()
        cand  = {}
        for inter in intersections:
            n = inter['num']
            c = get_candidate_windows(data_map[n][raw_key])
            cand[n] = {lbl: vol for lbl, vol in c}
            all_w.update(cand[n].keys())
        windows = sorted(all_w)
        hdrs = ["Int #","Name"] + windows + ["Chosen","Own Best","Deviation"]
        for ci, h in enumerate(hdrs, 1): _subhdr(ws, base+1, ci, h)
        for ri, inter in enumerate(intersections):
            n = inter['num']
            row = base + 2 + ri
            _data(ws, row, 1, n, bold=True)
            _data(ws, row, 2, inter['name'], align=_left())
            chosen   = peak_choices[n][period]
            best_win = max(cand[n], key=lambda k: cand[n][k]) if cand[n] else ''
            best_vol = cand[n].get(best_win, 0)
            chosen_vol = cand[n].get(chosen, 0)
            dev = abs(best_vol-chosen_vol)/best_vol if best_vol > 0 else 0
            for wi, w in enumerate(windows, 3):
                bg = C_AM if (period=='AM' and w==chosen) else \
                     C_PM if (period=='PM' and w==chosen) else C_WHITE
                _data(ws, row, wi, cand[n].get(w,0), bg=bg,
                      bold=(w==chosen))
            _data(ws, row, len(windows)+3, chosen, bg=C_AM if period=='AM' else C_PM, bold=True)
            _data(ws, row, len(windows)+4, best_win)
            _data(ws, row, len(windows)+5, f"{dev:.1%}",
                  bg=C_FLAG if dev > 0.10 else C_WHITE)
    ws.column_dimensions['A'].width = 6
    ws.column_dimensions['B'].width = 30
    for col in range(3, 25):
        ws.column_dimensions[get_column_letter(col)].width = 12

def _write_int_sheet(wb, inter, data, extracted, peak_choice):
    n  = inter['num']
    ws = wb.create_sheet(f"Int_{n:02d}")
    ws.sheet_view.showGridLines = False
    _hdr(ws, 1, 1, f"INT {n:02d} — {inter['name'].upper()}", span=20, sz=12)

    meta = data['meta']
    meta_items = [("Int #",n),("Name",inter['name']),("Control",inter.get('control','')),
                  ("Date",str(meta.get('date',''))),("File",inter.get('count_file',''))]
    col = 1
    for lbl, val in meta_items:
        c = ws.cell(row=3, column=col, value=lbl); c.font = _font(bold=True); c.alignment = _left()
        c = ws.cell(row=3, column=col+1, value=val); c.font = _font(); c.border = _border(); c.alignment = _left()
        col += 3

    RAW_HDRS = ["Time"] + MOVEMENTS + ["Total"]
    current_row = 5

    for period in ['AM','PM']:
        raw_key = f'{period.lower()}_raw'
        trk_key = f'{period.lower()}_trucks'
        raw_data = data[raw_key]
        trk_data = data[trk_key]
        peak_lbl = peak_choice[period]

        # Section A: Raw 15-min
        _hdr(ws, current_row, 1, f"SECTION A — RAW 15-MIN DATA  |  {period}", span=len(RAW_HDRS), sz=10)
        dir_grps = [(1,1,"Time"),(2,4,"NORTHBOUND"),(5,7,"SOUTHBOUND"),
                    (8,10,"EASTBOUND"),(11,13,"WESTBOUND"),(14,14,"TOTAL")]
        for cs,ce,lbl in dir_grps: _subhdr(ws, current_row+1, cs, lbl, span=ce-cs+1)
        for ci, h in enumerate(RAW_HDRS, 1): _subhdr(ws, current_row+2, ci, h)

        times = sorted(raw_data.keys())
        for ri, t in enumerate(times):
            row = current_row + 3 + ri
            row_data = raw_data[t]
            c = ws.cell(row=row, column=1, value=t)
            _style(c, bg=C_WHITE, font=_font(bold=True), align=_center())
            row_total = 0
            for mi, mv in enumerate(MOVEMENTS, 2):
                v = row_data.get(mv, 0) or 0
                row_total += v
                c = ws.cell(row=row, column=mi, value=v)
                _style(c, bg=C_WHITE, font=_font(), align=_center())
            c = ws.cell(row=row, column=len(MOVEMENTS)+2, value=row_total)
            _style(c, bg=C_INPUT, font=_font(), align=_center())

        # Section B: Truck data
        trk_start = current_row + 3 + len(times) + 1
        _hdr(ws, trk_start, 1, f"SECTION B — TRUCK VOLUMES  |  {period}", span=len(RAW_HDRS), sz=10)
        for ci, h in enumerate(RAW_HDRS, 1): _subhdr(ws, trk_start+1, ci, h)
        for ri, t in enumerate(times):
            row = trk_start + 2 + ri
            row_data = trk_data.get(t, {})
            c = ws.cell(row=row, column=1, value=t)
            _style(c, bg=C_WHITE, font=_font(bold=True), align=_center())
            trk_total = 0
            for mi, mv in enumerate(MOVEMENTS, 2):
                v = row_data.get(mv, 0) or 0
                trk_total += v
                c = ws.cell(row=row, column=mi, value=v)
                _style(c, bg=C_WHITE, font=_font(), align=_center())
            c = ws.cell(row=row, column=len(MOVEMENTS)+2, value=trk_total)
            _style(c, bg=C_INPUT, font=_font(), align=_center())

        # Section C: Peak hour extraction
        ext_base = trk_start + 2 + len(times) + 2
        _hdr(ws, ext_base, 1,
             f"SECTION C — PEAK HOUR EXTRACTION  |  {period}  |  Peak: {peak_lbl}",
             span=len(RAW_HDRS)+5, sz=10)
        ext_hdrs = ["Metric"] + MOVEMENTS + ["Total","PHF","HV%",
                    "Bike NB","Bike SB","Bike EB","Bike WB",
                    "Ped N","Ped S","Ped E","Ped W"]
        for ci, h in enumerate(ext_hdrs, 1): _subhdr(ws, ext_base+1, ci, h)

        ext   = extracted[period]
        vols  = ext['vehicles']
        trks  = ext['trucks']
        bikes = ext['bikes']
        peds  = ext['peds']

        row = ext_base + 2
        _data(ws, row, 1, "All Vehicles", bold=True, align=_left())
        total = 0
        for mi, mv in enumerate(MOVEMENTS, 2):
            v = vols.get(mv, 0); total += v; _data(ws, row, mi, v)
        _data(ws, row, len(MOVEMENTS)+2, total, bold=True)
        _data(ws, row, len(MOVEMENTS)+3, ext['phf'], fmt='0.000', bold=True)
        _data(ws, row, len(MOVEMENTS)+4, f"{ext['hv_pct']:.1f}%", bold=True)
        for ci, k in enumerate(['NB','SB','EB','WB'], len(MOVEMENTS)+5):
            _data(ws, row, ci, bikes.get(k,0))
        for ci, k in enumerate(['N_leg','S_leg','E_leg','W_leg'], len(MOVEMENTS)+9):
            _data(ws, row, ci, peds.get(k,0))

        row2 = ext_base + 3
        _data(ws, row2, 1, "Trucks", align=_left())
        for mi, mv in enumerate(MOVEMENTS, 2): _data(ws, row2, mi, trks.get(mv,0))
        _data(ws, row2, len(MOVEMENTS)+2, sum(trks.values()))

        current_row = ext_base + 7

    ws.column_dimensions['A'].width = 10
    for col in range(2, 20): ws.column_dimensions[get_column_letter(col)].width = 8
    ws.freeze_panes = "B6"

def _write_balance_sheet(wb, sheet_name, intersections, extracted, period,
                          balanced=False, balanced_vols=None):
    ws = wb.create_sheet(sheet_name)
    ws.sheet_view.showGridLines = False
    state = "BALANCED (rounded to nearest 5)" if balanced else "UNBALANCED"
    _hdr(ws, 1, 1, f"{period} — {state}", span=18, sz=12)
    note = ("Output from Furness engine. U-turns merged to Left. Feeds Registry."
            if balanced else
            "Direct peak hour extraction. U-turns merged to Left. Input to Furness engine.")
    c = ws.cell(row=2, column=1, value=note)
    c.font = _font(italic=True, sz=9); c.alignment = _left()

    dir_grps = [(1,1,"Int #"),(2,2,"Name"),(3,5,"NORTHBOUND"),(6,8,"SOUTHBOUND"),
                (9,11,"EASTBOUND"),(12,14,"WESTBOUND"),(15,15,"PHF"),(16,16,"HV%")]
    for cs,ce,lbl in dir_grps: _subhdr(ws, 3, cs, lbl, span=ce-cs+1)
    hdrs = ["Int #","Name"] + MOVEMENTS + ["PHF","HV%"]
    for ci, h in enumerate(hdrs, 1): _subhdr(ws, 4, ci, h)

    for inter in intersections:
        n   = inter['num']
        r   = 4 + n
        ext = extracted[n][period]
        vols = balanced_vols[n] if (balanced and balanced_vols and n in balanced_vols) \
               else ext['vehicles']
        _data(ws, r, 1, n, bold=True)
        _data(ws, r, 2, inter['name'], align=_left())
        for mi, mv in enumerate(MOVEMENTS, 3): _data(ws, r, mi, vols.get(mv,0))
        _data(ws, r, 15, ext['phf'], fmt='0.000')
        _data(ws, r, 16, f"{ext['hv_pct']:.1f}%")

    ws.column_dimensions['A'].width = 6
    ws.column_dimensions['B'].width = 32
    for col in range(3, 18): ws.column_dimensions[get_column_letter(col)].width = 8

def _write_conv_log(wb, conv_am, conv_pm, adj_am, adj_pm):
    ws = wb.create_sheet("Balancing_Log")
    ws.sheet_view.showGridLines = False
    _hdr(ws, 1, 1, "FURNESS BALANCING — CONVERGENCE LOG  (NCHRP 255, Balance to Average)", span=5, sz=12)
    for pi, (period, conv) in enumerate([('AM',conv_am),('PM',conv_pm)]):
        base = 3 + pi*(len(conv or [])+4)
        _subhdr(ws, base, 1, f"{period} Convergence", span=2)
        for ci, h in enumerate(["Iteration","Max Relative Gap"], 1): _subhdr(ws, base+1, ci, h)
        for ri, entry in enumerate(conv or [], base+2):
            _data(ws, ri, 1, entry['iteration'])
            pct = entry['max_relative_gap']
            _data(ws, ri, 2, f"{pct:.4%}", bg=C_FLAG if pct > CONVERGENCE_THRESHOLD else C_WHITE)
    adj_start = 3 + sum(len(c or [])+4 for c in [conv_am, conv_pm]) + 2
    _subhdr(ws, adj_start, 1, "Adjustment Log", span=5)
    for ci, h in enumerate(["Period","Iteration","Int #","Movement","Delta"], 1):
        _subhdr(ws, adj_start+1, ci, h)
    row = adj_start + 2
    for period, log in [('AM',adj_am or []),('PM',adj_pm or [])]:
        for entry in log:
            _data(ws, row, 1, period); _data(ws, row, 2, entry[0])
            _data(ws, row, 3, entry[1]); _data(ws, row, 4, entry[2])
            _data(ws, row, 5, round(entry[3],2))
            row += 1
    for col in range(1,6): ws.column_dimensions[get_column_letter(col)].width = 14

def _write_qc(wb, flags):
    ws = wb.create_sheet("QC")
    ws.sheet_view.showGridLines = False
    _hdr(ws, 1, 1, "QUALITY CONTROL FLAGS", span=5, sz=12)
    all_checks = [
        ("QC-01","Missing Lat/Long",               "Registry — fill in template"),
        ("QC-02","Atypical count day",              "2_Intersections — verify before use"),
        ("QC-03","Peak deviation >10% from corridor","PeakHour_Selection"),
        ("QC-04","HV% > 15%",                      "Int_XX Section C"),
        ("QC-05","PHF out of range [0.60, 1.00]",  "Int_XX Section C"),
        ("QC-06","Zero volume on active approach",  "Int_XX Section C"),
        ("QC-07","Prohibited movement has volume",  "Int_XX Section C — check count data"),
        ("QC-08","Post-balance residual remains",   "AM/PM_Balanced"),
    ]
    for ci, h in enumerate(["Check","Description","Source","Status","Details"], 1):
        _subhdr(ws, 3, ci, h)
    flag_map = {}
    for f in flags:
        flag_map.setdefault(f['check'], []).append(f['message'])
    for ri, (chk, desc, src) in enumerate(all_checks, 4):
        _data(ws, ri, 1, chk, bold=True)
        _data(ws, ri, 2, desc, align=_left())
        _data(ws, ri, 3, src,  align=_left())
        msgs = flag_map.get(chk, [])
        if msgs:
            _data(ws, ri, 4, "⚠ FLAG", bg=C_FLAG, color=C_RED, bold=True)
            _data(ws, ri, 5, " | ".join(msgs), align=_left())
        else:
            _data(ws, ri, 4, "✓ OK", bg="E8F5E9", color="1B5E20", bold=True)
            _data(ws, ri, 5, "")
    ws.column_dimensions['A'].width = 10
    ws.column_dimensions['B'].width = 38
    ws.column_dimensions['C'].width = 22
    ws.column_dimensions['D'].width = 10
    ws.column_dimensions['E'].width = 65

# ── Main ───────────────────────────────────────────────────────────────────
def main():
    tmpl_path = get_paths()
    cfg, intersections = read_template(tmpl_path)
    validate_files(intersections, cfg['raw_folder'])

    print("\nReading raw count files...")
    data_map = {}
    for inter in intersections:
        n = inter['num']
        print(f"  Int {n:02d}: {inter['name']}")
        d = parse_raw_file(inter['file'])
        # Apply seasonal factor if set
        sf = inter.get('seasonal')
        if sf and isinstance(sf, (int, float)) and sf != 1.0:
            print(f"    Applying seasonal factor: {sf}")
            for period_key in ['am_raw','pm_raw']:
                for t in d[period_key]:
                    for mv in d[period_key][t]:
                        d[period_key][t][mv] = int(d[period_key][t][mv] * sf)
        data_map[n] = d

    peak_choices = select_peak_hours(intersections, data_map, cfg['corridor_peak'])

    print("\nExtracting peak hour volumes...")
    extracted = {}
    for inter in intersections:
        n   = inter['num']
        d   = data_map[n]
        hv_override = inter.get('hv_override')
        extracted[n] = {}
        for period in ['AM','PM']:
            rk = f'{period.lower()}_raw'; tk = f'{period.lower()}_trucks'
            bk = f'{period.lower()}_bikes'; pk = f'{period.lower()}_peds'
            ext = extract_peak_volumes(d[rk], d[tk], peak_choices[n][period], hv_override)
            ext['bikes'] = extract_peak_bikes(d[bk], peak_choices[n][period])
            ext['peds']  = extract_peak_peds(d[pk],  peak_choices[n][period])
            extracted[n][period] = ext
            print(f"  Int {n:02d} {period}: total={ext['total_vol']} "
                  f"PHF={ext['phf']:.3f} HV%={ext['hv_pct']:.1f}%")

    balanced_am = balanced_pm = None
    conv_am = conv_pm = []
    adj_am  = adj_pm  = []

    if cfg['balance']:
        print(f"\nFurness balancing ({cfg['corridor_dir']}, NCHRP 255 Balance to Average)...")
        unbal_am = {n: extracted[n]['AM']['vehicles'] for n in extracted}
        unbal_pm = {n: extracted[n]['PM']['vehicles'] for n in extracted}
        balanced_am, conv_am, adj_am = balance_corridor(
            intersections, unbal_am, cfg['corridor_dir'], 'AM', cfg['balance_config'])
        balanced_pm, conv_pm, adj_pm = balance_corridor(
            intersections, unbal_pm, cfg['corridor_dir'], 'PM', cfg['balance_config'])
    else:
        print("\nBalancing skipped (Balance=No in template).")

    print("\nRunning QC checks...")
    qc_flags = run_qc(intersections, data_map, extracted, peak_choices,
                      balanced_am, balanced_pm, cfg['corridor_peak'], cfg['prohibited'],
                      cfg['corridor_dir'])
    if qc_flags:
        print(f"  {len(qc_flags)} flag(s):")
        for f in qc_flags: print(f"    [{f['check']}] {f['message']}")
    else:
        print("  All checks passed ✓")

    print("\nWriting output Excel...")
    outpath = write_output(cfg, intersections, data_map, extracted, peak_choices,
                           balanced_am, balanced_pm, conv_am, conv_pm,
                           qc_flags, adj_am, adj_pm, data_map)
    print(f"\n✓ Done. Output: {outpath}")
    print("="*60)

if __name__ == "__main__":
    main()
