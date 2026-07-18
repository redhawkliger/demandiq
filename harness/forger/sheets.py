"""The Forger — deterministic seeded vendor-style count-sheet generator.

Per (seed, style): generate one intersection's known-answer TMC data (12
movements, volumes 5-1500, derivable approach totals + grand total) and
render it to a PDF:

  Style T (tabular)  — NDS / Quality Counts-like: movement columns, 15-min
                       interval rows summing exactly to the peak-hour
                       values, totals row.
  Style D (diagram)  — Counts Unlimited-like: plan-view intersection
                       graphic, volumes at movement arrow positions,
                       approach-total boxes, compass indicator. The style
                       that triggers the known S1 mis-mapping bug.

  NOTE on Style D provenance: the repo holds NO Counts Unlimited layout
  notes and no sample PDFs (searched exhaustively 2026-07-14, incl. git
  history — the prior analysis was never committed). The layout here is
  built from industry-standard peak-hour TMC diagram conventions plus the
  bug's recorded symptoms (N/S flips, L/T/R slot shifts, totals read as
  movements). Acceptance gate #1 — the real extractor must exhibit mapping
  errors on Style D — is the fidelity arbiter; iterate this layout if the
  bug doesn't express.

Determinism contract: everything is driven by random.Random(f'forger:...')
(string-seeded, process-stable) and reportlab's invariant mode — PDF bytes
are identical per (seed, style), forever. No LLM anywhere in this module.

Corpus firewall: every PDF's metadata carries `forger-synthetic=true`
(Subject + Keywords). Forger sheets must NEVER enter an extraction
fine-tuning/example corpus — a model must not be trained on its own exam.
"""

import io
import random

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

STYLES = ('T', 'D')

MOVEMENTS_12 = (
    'EBL', 'EBT', 'EBR', 'WBL', 'WBT', 'WBR',
    'NBL', 'NBT', 'NBR', 'SBL', 'SBT', 'SBR',
)
APPROACHES = ('NB', 'SB', 'EB', 'WB')

# Values must stay pairwise >MIN_GAP apart (movements + approach totals +
# grand total) so the Grader's exact-value matching is unambiguous: a
# MAP-ERR (exact value in the wrong slot) can never be mistaken for a
# DIGIT-ERR (±small delta at the right slot).
MIN_GAP = 10

_NS_STREETS = ['1st Ave', 'Grand Ave', 'Cedar Ave', 'Euclid Ave', 'Palm Ave',
               'Magnolia Ave', 'Mission Blvd', 'College Blvd']
_EW_STREETS = ['Main St', 'Broadway', 'Foothill Blvd', 'Chapman Ave',
               'Katella Ave', 'Lincoln Ave', 'Imperial Hwy', 'Adams St']
_CITIES = ['Escondido', 'Vista', 'Poway', 'Carlsbad', 'Fullerton', 'Orange']
_FONTS = ['Helvetica', 'Times-Roman', 'Courier']

_AM_BINS = ('7:15', '7:30', '7:45', '8:00')
_PM_BINS = ('16:45', '17:00', '17:15', '17:30')


def _draw_period_volumes(rng):
    """One period's 12 movement values, rejection-sampled until all 17
    derived numbers (12 movements + 4 approach totals + grand total) are
    pairwise >MIN_GAP apart. Deterministic per rng state."""
    for _ in range(1000):
        vols = {mv: rng.randrange(5, 1501) for mv in MOVEMENTS_12}
        at = {ap: sum(vols[f'{ap}{t}'] for t in 'LTR') for ap in APPROACHES}
        grand = sum(vols.values())
        nums = sorted(list(vols.values()) + list(at.values()) + [grand])
        if all(b - a > MIN_GAP for a, b in zip(nums, nums[1:])):
            return vols, at, grand
    raise RuntimeError('rejection sampling failed (should be unreachable)')


def _split_bins(rng, total):
    """Split a peak-hour value into 4 non-negative 15-min bins summing
    exactly to it (Style T interval rows)."""
    base = total // 4
    bins = [base] * 4
    for i in range(total - base * 4):
        bins[i % 4] += 1
    for _ in range(3):                       # seeded jitter, sum-preserving
        i, j = rng.randrange(4), rng.randrange(4)
        shift = rng.randrange(0, max(1, bins[i] // 3))
        bins[i] -= shift
        bins[j] += shift
    return bins


def generate_sheet(seed, style):
    """Deterministic sheet data (the ANSWER KEY) for one (seed, style)."""
    if style not in STYLES:
        raise ValueError(f'unknown style {style!r} — one of {STYLES}')
    rng = random.Random(f'forger:{style}:{seed}')
    ns_street = rng.choice(_NS_STREETS)
    ew_street = rng.choice(_EW_STREETS)
    sheet = {
        'seed': seed,
        'style': style,
        'intersection_name': f'{ns_street} & {ew_street}',
        'ns_street': ns_street,
        'ew_street': ew_street,
        'city': rng.choice(_CITIES),
        'date': f'{rng.randrange(1, 13):02d}/{rng.randrange(1, 29):02d}/2026',
        'job_no': f'CU-{rng.randrange(10000, 99999)}',
        'orientation': rng.choice(('N-up', 'E-up')),
        'font': rng.choice(_FONTS),
        'font_size': rng.choice((7, 8, 9)),
        'periods': {},
        'approach_totals': {},
        'grand_total': {},
        'bins': {},
        'peak_windows': {'AM': '7:15 AM - 8:15 AM', 'PM': '4:45 PM - 5:45 PM'},
    }
    for period in ('AM', 'PM'):
        vols, at, grand = _draw_period_volumes(rng)
        sheet['periods'][period] = vols
        sheet['approach_totals'][period] = at
        sheet['grand_total'][period] = grand
        sheet['bins'][period] = {mv: _split_bins(rng, v)
                                 for mv, v in vols.items()}
    return sheet


# ── PDF rendering ────────────────────────────────────────────────────────────

def _new_canvas(buf, sheet):
    c = rl_canvas.Canvas(buf, pagesize=letter, invariant=1)
    c.setTitle(f"Turning Movement Count — {sheet['intersection_name']}")
    c.setAuthor('DemandIQ Forger (synthetic)')
    c.setSubject('forger-synthetic=true')
    c.setKeywords('forger-synthetic=true; never use as training data')
    return c


def render_pdf(sheet):
    """Render a sheet to deterministic PDF bytes (invariant mode: fixed
    dates, deterministic ID — byte-identical per (seed, style))."""
    buf = io.BytesIO()
    c = _new_canvas(buf, sheet)
    if sheet['style'] == 'T':
        _render_tabular(c, sheet)
    else:
        _render_diagram(c, sheet)
    c.showPage()
    c.save()
    return buf.getvalue()


# ── Style T: NDS/Quality Counts-like tabular sheet ──────────────────────────

# Column order mirrors the NDS convention (approach-major, L/T/R/U per
# approach, per-interval TOTAL last) seen in training_data.jsonl example 1.
_T_COLS = ['NL', 'NT', 'NR', 'NU', 'SL', 'ST', 'SR', 'SU',
           'EL', 'ET', 'ER', 'EU', 'WL', 'WT', 'WR', 'WU']
_T_COL_TO_MV = {'N': 'NB', 'S': 'SB', 'E': 'EB', 'W': 'WB'}


def _t_value(sheet, period, col, bin_idx=None):
    mv = _T_COL_TO_MV[col[0]] + col[1]
    if col[1] == 'U':
        return 0
    if bin_idx is None:
        return sheet['periods'][period][mv]
    return sheet['bins'][period][mv][bin_idx]


def _render_tabular(c, sheet):
    font, fs = sheet['font'], sheet['font_size']
    w, h = letter
    y = h - 40
    c.setFont(font + ('-Bold' if font == 'Helvetica' else ''), 11)
    c.drawString(40, y, 'NATIONAL DATA SERVICES — INTERSECTION TURNING MOVEMENT COUNT')
    c.setFont(font, fs + 1)
    y -= 16
    c.drawString(40, y, f"Location: {sheet['intersection_name']}"
                        f"    City: {sheet['city']}")
    y -= 12
    c.drawString(40, y, f"Date: {sheet['date']}    Project ID: {sheet['job_no']}"
                        f"    Control: Signalized")
    y -= 12
    c.drawString(40, y, f"NS/EW Streets: {sheet['ns_street']} / {sheet['ew_street']}")

    x0, colw = 88, 28
    for period, bins in (('AM', _AM_BINS), ('PM', _PM_BINS)):
        y -= 22
        c.setFont(font, fs + 1)
        c.drawString(40, y, f'{period} PEAK PERIOD'
                            f"  ({sheet['peak_windows'][period]})")
        y -= 12
        c.setFont(font, fs)
        c.drawString(x0 + 4 * colw * 0, y, 'NORTHBOUND')
        c.drawString(x0 + 4 * colw * 1, y, 'SOUTHBOUND')
        c.drawString(x0 + 4 * colw * 2, y, 'EASTBOUND')
        c.drawString(x0 + 4 * colw * 3, y, 'WESTBOUND')
        y -= 11
        c.drawString(40, y, 'Time')
        for i, col in enumerate(_T_COLS):
            c.drawRightString(x0 + i * colw + colw - 6, y, col)
        c.drawRightString(x0 + 16 * colw + colw - 2, y, 'TOTAL')
        for b, t in enumerate(bins):
            y -= 11
            c.drawString(40, y, t)
            row_total = 0
            for i, col in enumerate(_T_COLS):
                v = _t_value(sheet, period, col, b)
                row_total += v
                c.drawRightString(x0 + i * colw + colw - 6, y, str(v))
            c.drawRightString(x0 + 16 * colw + colw - 2, y, str(row_total))
        y -= 12
        c.drawString(40, y, 'Peak Hr')
        for i, col in enumerate(_T_COLS):
            c.drawRightString(x0 + i * colw + colw - 6, y,
                              str(_t_value(sheet, period, col)))
        c.drawRightString(x0 + 16 * colw + colw - 2, y,
                          str(sheet['grand_total'][period]))


# ── Style D: Counts Unlimited-like diagram sheet ────────────────────────────
#
# One page, two panels (AM top / PM bottom). Each panel: a plan-view
# crossing with, on each edge, the approach's three movement volumes laid
# along that edge in [left-turn, through, right-turn] order as seen by the
# driver, small turn glyphs (arrows) beside each number, a boxed approach
# total on each edge, a grand-total box, and a compass arrow. Orientation
# 'N-up' puts the north leg at the top; 'E-up' rotates the drawing 90°
# (east leg at top) with the compass showing it — the layout feature that
# plausibly induces N/S mis-mapping.

# edge -> which approach's traffic ARRIVES from that edge
_EDGE_APPROACH = {
    'N-up': {'top': 'SB', 'bottom': 'NB', 'left': 'EB', 'right': 'WB'},
    'E-up': {'top': 'WB', 'bottom': 'EB', 'left': 'SB', 'right': 'NB'},
}
# page-coordinate travel vector of traffic ENTERING from each edge (y up)
_TRAVEL = {'top': (0, -1), 'bottom': (0, 1), 'left': (1, 0), 'right': (-1, 0)}


def _arrow(c, x, y, edge, turn):
    """Small drawn turn arrow (base-14 fonts have no arrow glyphs): an 8pt
    shaft in the travel direction, bending 6pt toward the driver's left or
    right for L/R, with a 3pt arrowhead at the tip."""
    tx, ty = _TRAVEL[edge]
    lx, ly = -ty, tx                      # driver's left in page coords
    if turn == 'L':
        bx, by = lx, ly
    elif turn == 'R':
        bx, by = -lx, -ly
    else:
        bx, by = tx, ty
    mx, my = x + tx * 8, y + ty * 8
    ex, ey = (mx + bx * 6, my + by * 6) if turn in 'LR' else (mx, my)
    c.setLineWidth(0.8)
    c.line(x, y, mx, my)
    if turn in 'LR':
        c.line(mx, my, ex, ey)
    hx, hy = (bx, by)
    c.line(ex, ey, ex - hx * 3 - hy * 2, ey - hy * 3 + hx * 2)
    c.line(ex, ey, ex - hx * 3 + hy * 2, ey - hy * 3 - hx * 2)


def _render_diagram_panel(c, sheet, period, cx, cy):
    """One period's diagram panel centred at (cx, cy). All numbers sit clear
    of the pavement; per approach the trio is laid out in [L, T, R] order
    along its edge with drawn turn arrows, plus a boxed approach total at
    the outer end of the leg."""
    font, fs = sheet['font'], sheet['font_size']
    edges = _EDGE_APPROACH[sheet['orientation']]
    HALF, ROAD = 100, 16

    c.setFont(font, fs + 2)
    c.drawCentredString(cx, cy + HALF + 44,
                        f"{period} PEAK HOUR  {sheet['peak_windows'][period]}")

    # crossing streets with dashed centerlines (inside pavement only)
    c.setLineWidth(1.2)
    c.rect(cx - HALF, cy - ROAD, 2 * HALF, 2 * ROAD)
    c.rect(cx - ROAD, cy - HALF, 2 * ROAD, 2 * HALF)
    c.setDash(3, 3)
    c.line(cx - HALF, cy, cx + HALF, cy)
    c.line(cx, cy - HALF, cx, cy + HALF)
    c.setDash()

    vols = sheet['periods'][period]
    at = sheet['approach_totals'][period]
    c.setFont(font, fs)

    def trio(approach):
        return [(vols[f'{approach}{t}'], t) for t in 'LTR']

    # top edge — numbers in a row above the pavement, arrows beneath them
    ap = edges['top']
    for i, (v, t) in enumerate(trio(ap)):
        x = cx + (i - 1) * 36
        c.drawCentredString(x, cy + HALF + 8, str(v))
        _arrow(c, x, cy + HALF + 4, 'top', t)
    c.rect(cx - 26, cy + HALF + 22, 52, 13)
    c.drawCentredString(cx, cy + HALF + 25, str(at[ap]))

    # bottom edge — mirrored (trio still reads [L, T, R] for its driver)
    ap = edges['bottom']
    for i, (v, t) in enumerate(trio(ap)):
        x = cx + (1 - i) * 36
        c.drawCentredString(x, cy - HALF - 14, str(v))
        _arrow(c, x, cy - HALF - 4, 'bottom', t)
    c.rect(cx - 26, cy - HALF - 32, 52, 13)
    c.drawCentredString(cx, cy - HALF - 29, str(at[ap]))

    # left edge — vertical stack outside the pavement
    ap = edges['left']
    for i, (v, t) in enumerate(trio(ap)):
        y = cy + (1 - i) * 24
        c.drawRightString(cx - HALF - 16, y - 3, str(v))
        _arrow(c, cx - HALF - 10, y, 'left', t)
    c.rect(cx - HALF - 70, cy - 42, 52, 13)
    c.drawCentredString(cx - HALF - 44, cy - 39, str(at[ap]))

    # right edge
    ap = edges['right']
    for i, (v, t) in enumerate(trio(ap)):
        y = cy + (i - 1) * 24
        c.drawString(cx + HALF + 16, y - 3, str(v))
        _arrow(c, cx + HALF + 10, y, 'right', t)
    c.rect(cx + HALF + 18, cy + 30, 52, 13)
    c.drawCentredString(cx + HALF + 44, cy + 33, str(at[ap]))

    # street labels, grand total, compass
    c.setFont(font, fs + 1)
    h_street = sheet['ew_street'] if sheet['orientation'] == 'N-up' else sheet['ns_street']
    v_street = sheet['ns_street'] if sheet['orientation'] == 'N-up' else sheet['ew_street']
    c.drawString(cx - HALF - 70, cy + 14, h_street)
    c.drawString(cx + ROAD + 6, cy + HALF - 26, v_street)
    c.rect(cx - HALF - 70, cy - HALF - 32, 142, 13)
    c.drawString(cx - HALF - 66, cy - HALF - 29,
                 f"TOTAL ENTERING: {sheet['grand_total'][period]}")
    nx, ny = cx + HALF + 44, cy + HALF + 18
    c.setFont(font, fs + 2)
    if sheet['orientation'] == 'N-up':
        c.line(nx, ny, nx, ny + 14)
        c.line(nx, ny + 14, nx - 3, ny + 10)
        c.line(nx, ny + 14, nx + 3, ny + 10)
        c.drawString(nx + 5, ny + 4, 'N')
    else:                                  # E-up: north points page-left
        c.line(nx + 14, ny + 7, nx, ny + 7)
        c.line(nx, ny + 7, nx + 4, ny + 10)
        c.line(nx, ny + 7, nx + 4, ny + 4)
        c.drawString(nx + 16, ny + 4, 'N')


def _render_diagram(c, sheet):
    font, fs = sheet['font'], sheet['font_size']
    w, h = letter
    c.setFont(font + ('-Bold' if font == 'Helvetica' else ''), 12)
    c.drawCentredString(w / 2, h - 36, 'COUNTS UNLIMITED, INC.')
    c.setFont(font, fs + 2)
    c.drawCentredString(w / 2, h - 50, 'INTERSECTION TURNING MOVEMENT COUNT')
    c.setFont(font, fs + 1)
    c.drawString(48, h - 68, f"Location: {sheet['intersection_name']}"
                             f"   City: {sheet['city']}")
    c.drawString(48, h - 80, f"Date: {sheet['date']}   Job No: {sheet['job_no']}")
    _render_diagram_panel(c, sheet, 'AM', w / 2, h - 250)
    _render_diagram_panel(c, sheet, 'PM', w / 2, h - 590)
