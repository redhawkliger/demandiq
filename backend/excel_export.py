"""
DemandIQ — Excel workbook export.

Builds an 8-sheet .xlsx from the full project state (same shape as the
frontend's localStorage 'demandiq:project' snapshot).

Sheets:
  1. Project Info       — key/value summary
  2. AM Unbalanced      — Int#, Name, 16 movements (active cells only), PHF, HV%
  3. AM Balanced        — same shape, using intersection.balanced.AM
  4. PM Unbalanced      — same as AM Unbalanced, PM period
  5. PM Balanced        — same as AM Balanced, PM period
  6. Convergence Log    — AM and PM iteration tables side-by-side
  7. QC Flags           — flat list of QC issues
  8. Adjustments        — top 50 balancing deltas across both periods

Inactive cells (movement letter not in the lane config for that approach) are
left blank — never zero — so engineers can distinguish "no lane" from
"lane exists but counted zero".
"""

import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter


# ── Constants ────────────────────────────────────────────────────────────────
ALL_DIRS = ('EB', 'WB', 'NB', 'SB')
ALL_MOVES = ('U', 'L', 'T', 'R')

# Styling (matches the existing /excel endpoint's palette + size)
HDR_FILL  = PatternFill('solid', fgColor='2F3640')
HDR_FONT  = Font(name='Arial', bold=True, color='FFFFFF', size=10)
SUB_FILL  = PatternFill('solid', fgColor='CFD8DC')
SUB_FONT  = Font(name='Arial', bold=True, color='000000', size=10)
DATA_FONT = Font(name='Arial', color='000000', size=10)

CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
LEFT   = Alignment(horizontal='left',   vertical='center')

_THIN = Side(style='thin', color='AAAAAA')
BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _active_movements(approach):
    """Set of active movement chars {U, L, T, R} for an approach dict."""
    if not approach or approach.get('exists') is False:
        return set()
    active = set()
    for lane in approach.get('lanes') or []:
        for ch in lane.get('movement', '') or '':
            if ch in ALL_MOVES:
                active.add(ch)
    return active


def _style_header(cell):
    cell.fill = HDR_FILL
    cell.font = HDR_FONT
    cell.alignment = CENTER
    cell.border = BORDER


def _style_subheader(cell):
    cell.fill = SUB_FILL
    cell.font = SUB_FONT
    cell.alignment = CENTER
    cell.border = BORDER


def _style_data(cell, align=None, fmt=None):
    cell.font = DATA_FONT
    cell.alignment = align or CENTER
    cell.border = BORDER
    if fmt:
        cell.number_format = fmt


# ── Sheet writers ────────────────────────────────────────────────────────────
def _write_project_info(ws, state):
    ws.title = 'Project Info'

    project   = state.get('project')   or {}
    balancing = state.get('balancing') or {}
    analysis  = state.get('analysis')  or {}
    last_run  = analysis.get('lastRun') or {}
    convergence = last_run.get('convergence') or {}
    intersections = state.get('intersections') or []
    qc_flags = last_run.get('qcFlags') or []

    am_win = balancing.get('amWindow') or {}
    pm_win = balancing.get('pmWindow') or {}
    am_conv = convergence.get('AM') or {}
    pm_conv = convergence.get('PM') or {}

    def conv_summary(c):
        if not c:
            return '—'
        n = c.get('iterations_used', 0)
        ok = 'converged' if c.get('converged') else 'did NOT converge'
        return f"{n} iterations, {ok}"

    rows = [
        ('Project Name',       project.get('name', '')),
        ('Project Number',     project.get('projectNumber', '')),
        ('Client / Agency',    project.get('client', '')),
        ('Analyst',            project.get('analyst', '')),
        ('Checker',            project.get('checker', '')),
        ('Date',               project.get('date', '')),
        ('Scenario',           project.get('scenario', '')),
        ('Project Type',       project.get('projectType', '')),
        ('Analysis Periods',   ', '.join(project.get('analysisPeriods') or [])),
        ('', ''),
        ('Intersection Count', len(intersections)),
        ('Corridor Direction', balancing.get('corridorDir') or analysis.get('corridorDir', '')),
        ('Peak Mode',          balancing.get('peakMode', '')),
        ('AM Window',          f"{am_win.get('start', '')} – {am_win.get('end', '')}"),
        ('PM Window',          f"{pm_win.get('start', '')} – {pm_win.get('end', '')}"),
        ('Convergence Threshold', f"{(balancing.get('convergenceThreshold') or 0.01) * 100:.1f}%"),
        ('Max Iterations',     balancing.get('maxIterations', 200)),
        ('', ''),
        ('Last Run',           last_run.get('timestamp', '')),
        ('AM Convergence',     conv_summary(am_conv)),
        ('PM Convergence',     conv_summary(pm_conv)),
        ('QC Flags',           len(qc_flags)),
    ]

    for r, (k, v) in enumerate(rows, start=1):
        if not k:
            continue
        c1 = ws.cell(row=r, column=1, value=k)
        _style_subheader(c1)
        c2 = ws.cell(row=r, column=2, value=v)
        _style_data(c2, align=LEFT)

    ws.column_dimensions['A'].width = 26
    ws.column_dimensions['B'].width = 50


def _write_volume_sheet(ws, title, intersections, period, balanced, overrides=None):
    """Write a volume sheet (16 movement cols + PHF + HV%).

    `balanced=True` reads intersection.balanced[period]; False reads
    .volumes[period] and strips the {value, _source} wrapper.
    Stage 5: when `balanced=True`, applies engineer overrides (if provided)
    on top of the balanced values. Overridden cells get a "*" suffix on
    their displayed value so reviewers can spot interventions at a glance.
    """
    overrides = overrides or {}
    ws.title = title

    # ── Row 1: direction group headers + spacer cells ────────────────
    # Cols 1,2 (Int#, Name) and 19,20 (PHF, HV%) span both header rows.
    for col, label in [(1, 'Int #'), (2, 'Name'), (19, 'PHF'), (20, 'HV%')]:
        c = ws.cell(row=1, column=col, value=label)
        _style_header(c)
        ws.merge_cells(start_row=1, start_column=col, end_row=2, end_column=col)

    # Direction group headers (merged across 4 cols each)
    col = 3
    for d in ALL_DIRS:
        c = ws.cell(row=1, column=col, value=d)
        _style_header(c)
        ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=col + 3)
        # Also style the cells under the merge so borders look clean
        for c2 in range(col, col + 4):
            ws.cell(row=1, column=c2).border = BORDER
        col += 4

    # ── Row 2: U/L/T/R sub-headers (only under each direction group) ─
    col = 3
    for d in ALL_DIRS:
        for m in ALL_MOVES:
            c = ws.cell(row=2, column=col, value=m)
            _style_subheader(c)
            col += 1

    # ── Data rows ────────────────────────────────────────────────────
    for ridx, it in enumerate(intersections, start=3):
        c = ws.cell(row=ridx, column=1, value=it.get('num', ''))
        _style_data(c, fmt='0')

        c = ws.cell(row=ridx, column=2, value=it.get('name', ''))
        _style_data(c, align=LEFT)

        approaches = it.get('approaches') or {}
        if balanced:
            period_data = (it.get('balanced') or {}).get(period) or {}
        else:
            period_data = (it.get('volumes') or {}).get(period) or {}
        # Stage 5: per-intersection override dict for this period
        int_overrides = overrides.get(str(it.get('num', ''))) or {}

        col = 3
        for d in ALL_DIRS:
            active = _active_movements(approaches.get(d))
            for m in ALL_MOVES:
                key = f'{d}{m}'
                cell = ws.cell(row=ridx, column=col)
                if m in active:
                    raw = period_data.get(key)
                    if isinstance(raw, dict):       # unbalanced wrapper
                        val = raw.get('value')
                    else:                            # balanced plain value
                        val = raw
                    # Stage 5: apply engineer override if present (balanced only)
                    is_overridden = False
                    if balanced and key in int_overrides:
                        val = int_overrides[key]
                        is_overridden = True
                    if val is not None:
                        # Marker suffix on overridden cells — written as text so
                        # the "*" is preserved (otherwise openpyxl would coerce
                        # numeric to value-only)
                        if is_overridden:
                            cell.value = f"{val}*"
                            _style_data(cell, align=None)
                            col += 1
                            continue
                        cell.value = val
                # Style cell whether active or not — keeps the grid even.
                _style_data(cell, fmt='0')
                col += 1

        # PHF + HV%
        phf = (it.get('phf') or {}).get(period)
        hv  = (it.get('hvPct') or {}).get(period)
        c_phf = ws.cell(row=ridx, column=19, value=phf)
        _style_data(c_phf, fmt='0.000')
        c_hv  = ws.cell(row=ridx, column=20, value=hv)
        _style_data(c_hv, fmt='0.0')

    # Freeze both header rows + first two columns
    ws.freeze_panes = 'C3'

    # Column widths
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 36
    for c in range(3, 19):
        ws.column_dimensions[get_column_letter(c)].width = 7
    ws.column_dimensions['S'].width = 8
    ws.column_dimensions['T'].width = 8


def _write_convergence(ws, last_run):
    ws.title = 'Convergence Log'
    convergence = last_run.get('convergence') or {}
    am = (convergence.get('AM') or {}).get('log') or []
    pm = (convergence.get('PM') or {}).get('log') or []

    # Section headers row 1
    for start_col, label in [(1, 'AM'), (4, 'PM')]:
        c = ws.cell(row=1, column=start_col, value=label)
        _style_header(c)
        ws.merge_cells(start_row=1, start_column=start_col,
                       end_row=1, end_column=start_col + 1)

    # Column headers row 2
    for col, label in [(1, 'Iteration'), (2, 'Max Gap'), (4, 'Iteration'), (5, 'Max Gap')]:
        c = ws.cell(row=2, column=col, value=label)
        _style_subheader(c)

    # Data
    for ridx, entry in enumerate(am, start=3):
        _style_data(ws.cell(row=ridx, column=1, value=entry.get('iteration')), fmt='0')
        _style_data(ws.cell(row=ridx, column=2, value=entry.get('max_relative_gap')),
                    fmt='0.000000')
    for ridx, entry in enumerate(pm, start=3):
        _style_data(ws.cell(row=ridx, column=4, value=entry.get('iteration')), fmt='0')
        _style_data(ws.cell(row=ridx, column=5, value=entry.get('max_relative_gap')),
                    fmt='0.000000')

    ws.column_dimensions['A'].width = 10
    ws.column_dimensions['B'].width = 12
    ws.column_dimensions['C'].width = 2
    ws.column_dimensions['D'].width = 10
    ws.column_dimensions['E'].width = 12
    ws.freeze_panes = 'A3'


def _write_qc(ws, last_run):
    ws.title = 'QC Flags'
    flags = (last_run or {}).get('qcFlags') or []

    for col, label in enumerate(['Check', 'Int #', 'Period', 'Message'], start=1):
        _style_header(ws.cell(row=1, column=col, value=label))

    if not flags:
        c = ws.cell(row=2, column=1, value='All QC checks passed.')
        _style_data(c, align=LEFT)
        ws.merge_cells('A2:D2')
    else:
        for ridx, f in enumerate(flags, start=2):
            _style_data(ws.cell(row=ridx, column=1, value=f.get('check')))
            _style_data(ws.cell(row=ridx, column=2, value=f.get('int')))
            _style_data(ws.cell(row=ridx, column=3, value=f.get('period')))
            _style_data(ws.cell(row=ridx, column=4, value=f.get('message')), align=LEFT)

    ws.column_dimensions['A'].width = 10
    ws.column_dimensions['B'].width = 8
    ws.column_dimensions['C'].width = 8
    ws.column_dimensions['D'].width = 80
    ws.freeze_panes = 'A2'


def _write_adjustments(ws, last_run):
    ws.title = 'Adjustments'
    adj = (last_run or {}).get('adjustments') or {}
    am = adj.get('AM') or []
    pm = adj.get('PM') or []

    combined = [
        {**a, '_period': 'AM'} for a in am
    ] + [
        {**a, '_period': 'PM'} for a in pm
    ]
    combined.sort(key=lambda a: abs(a.get('delta') or 0), reverse=True)
    top = combined[:50]

    for col, label in enumerate(['Period', 'Int #', 'Movement', 'Delta'], start=1):
        _style_header(ws.cell(row=1, column=col, value=label))

    if not top:
        c = ws.cell(row=2, column=1, value='No adjustments (already balanced).')
        _style_data(c, align=LEFT)
        ws.merge_cells('A2:D2')
    else:
        for ridx, a in enumerate(top, start=2):
            _style_data(ws.cell(row=ridx, column=1, value=a.get('_period')))
            _style_data(ws.cell(row=ridx, column=2, value=a.get('intersection_num')), fmt='0')
            _style_data(ws.cell(row=ridx, column=3, value=a.get('movement')))
            _style_data(ws.cell(row=ridx, column=4, value=a.get('delta')),
                        fmt='+0.0;-0.0;0.0')

    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 8
    ws.column_dimensions['C'].width = 10
    ws.column_dimensions['D'].width = 10
    ws.freeze_panes = 'A2'


# ── Public API ───────────────────────────────────────────────────────────────
def _write_overrides(wb, intersections, overrides):
    """Stage 5: Engineer Overrides sheet. One row per overridden cell.
    Omitted entirely (no sheet added) if there are no overrides."""
    am = overrides.get('AM') or {}
    pm = overrides.get('PM') or {}
    total = sum(len(m) for m in am.values()) + sum(len(m) for m in pm.values())
    if total == 0:
        return

    ws = wb.create_sheet('Engineer Overrides')

    # Header
    for col, label in enumerate(['Int #', 'Name', 'Period', 'Movement', 'Raw', 'Balanced', 'Override'], start=1):
        c = ws.cell(row=1, column=col, value=label)
        _style_header(c)

    # int_num → intersection dict for quick lookups
    by_num = {str(it.get('num')): it for it in intersections}

    rows = []
    for period, period_map in (('AM', am), ('PM', pm)):
        for int_str, mvts in period_map.items():
            it = by_num.get(int_str)
            if not it:
                continue
            raw_period = (it.get('volumes') or {}).get(period) or {}
            bal_period = (it.get('balanced') or {}).get(period) or {}
            for mv, override_val in mvts.items():
                raw_cell = raw_period.get(mv)
                raw_val = raw_cell.get('value') if isinstance(raw_cell, dict) else raw_cell
                bal_val = bal_period.get(mv)
                rows.append({
                    'num': int(int_str),
                    'name': it.get('name', ''),
                    'period': period,
                    'movement': mv,
                    'raw': raw_val or 0,
                    'balanced': bal_val or 0,
                    'override': override_val,
                })

    rows.sort(key=lambda r: (r['num'], r['period'], r['movement']))
    for ridx, r in enumerate(rows, start=2):
        _style_data(ws.cell(row=ridx, column=1, value=r['num']), fmt='0')
        _style_data(ws.cell(row=ridx, column=2, value=r['name']), align=LEFT)
        _style_data(ws.cell(row=ridx, column=3, value=r['period']), align=LEFT)
        _style_data(ws.cell(row=ridx, column=4, value=r['movement']), align=LEFT)
        _style_data(ws.cell(row=ridx, column=5, value=r['raw']), fmt='0')
        _style_data(ws.cell(row=ridx, column=6, value=r['balanced']), fmt='0')
        _style_data(ws.cell(row=ridx, column=7, value=r['override']), fmt='0')

    ws.freeze_panes = 'A2'
    for col, width in ((1, 8), (2, 32), (3, 8), (4, 10), (5, 10), (6, 10), (7, 10)):
        ws.column_dimensions[get_column_letter(col)].width = width


def build_workbook(project_state):
    """Build the full 8-sheet workbook from the project snapshot.

    Returns: bytes (.xlsx data).
    """
    intersections = project_state.get('intersections') or []
    last_run = (project_state.get('analysis') or {}).get('lastRun') or {}
    # Stage 5: per-cell engineer overrides applied on top of balanced values
    overrides = ((project_state.get('balancing') or {}).get('overrides')) or {'AM': {}, 'PM': {}}

    wb = Workbook()

    _write_project_info(wb.active, project_state)
    _write_volume_sheet(wb.create_sheet(), 'AM Unbalanced', intersections, 'AM', balanced=False)
    _write_volume_sheet(wb.create_sheet(), 'AM Balanced',   intersections, 'AM', balanced=True,
                        overrides=overrides.get('AM') or {})
    _write_volume_sheet(wb.create_sheet(), 'PM Unbalanced', intersections, 'PM', balanced=False)
    _write_volume_sheet(wb.create_sheet(), 'PM Balanced',   intersections, 'PM', balanced=True,
                        overrides=overrides.get('PM') or {})
    _write_convergence(wb.create_sheet(),  last_run)
    _write_qc(wb.create_sheet(),           last_run)
    _write_adjustments(wb.create_sheet(),  last_run)
    # Stage 5: Engineer Overrides sheet (omitted entirely if no overrides)
    _write_overrides(wb, intersections, overrides)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
