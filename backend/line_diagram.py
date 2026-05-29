"""
DemandIQ — single-intersection line diagram renderer.

Extracted from 3_demand_analysis.py (the v26-approved line diagram engine).
Geometry, colours, cluster positions, font sizes, and arrow shapes are all
locked from the original — DO NOT redesign. Only changes vs the original:

  - Module is self-contained: matplotlib.use('Agg') configured here, not
    inherited from the script's top-level.
  - _dg_draw_approach and _dg_draw_cell take a `label_fn(u, b) -> (text, color)`
    callable so the four view modes (combined / balanced / unbalanced / delta)
    can swap labels without parallel renderers.
  - New constants DG_DELTA_UP and DG_DELTA_DOWN for delta-view colouring.
  - _single_cell_preset() replaces _dg_get_preset() for our use case — the
    original assumed a 20×15 inch multi-grid figure, which gives the wrong
    scale factor for a 4×4 inch single-cell render.
  - Multi-grid functions (_dg_get_preset, _dg_get_grid, _dg_legend_bar,
    _generate_page_figure) are NOT extracted — those belong with S8's report
    generator.
"""

import io
import math

import matplotlib
matplotlib.use('Agg')                       # headless before pyplot import
import matplotlib.pyplot as plt              # noqa: E402
import numpy as np                           # noqa: E402
from matplotlib.patches import Polygon as MplPolygon, Circle as MplCircle  # noqa: E402


# ── Colour constants (locked from v26) ─────────────────────────────────────────
DG_BLACK = '#000000'
DG_WHITE = '#FFFFFF'
DG_GREY  = '#969696'         # RGB 150,150,150 — road arms + arrows
DG_DELTA_UP   = '#2D8050'    # delta-view: positive (more after balancing)
DG_DELTA_DOWN = '#B0413E'    # delta-view: negative

# ── Geometry constants (locked from v26) ───────────────────────────────────────
DG_ARM   = 0.38              # road arm length (normalized cell coord, fixed)
DG_C     = 0.10              # arrow curve radius
DG_SP_F  = 1.5               # arrow cluster spacing factor (× s)
DG_VOL_NS = 0.9              # volume label offset NB/SB (× s)
DG_VOL_EW = 0.7              # volume label offset EB/WB (× s)

# Cluster centers — locked positions (SB cy+0.15 to clear title)
DG_CLUSTERS = {
    'NB': (+0.22, -0.20),    # SE quadrant of cell
    'SB': (-0.22, +0.15),    # NW quadrant
    'EB': (-0.20, -0.20),    # SW quadrant
    'WB': (+0.20, +0.20),    # NE quadrant
}

# Reference cell size + base parameters at sf=1.0
DG_REF_CELL_W = 16 / 3       # ≈ 5.33 inches
DG_REF_CELL_H = 12 / 2       # = 6.00 inches
DG_BASE = {
    's':         0.062,      # arrow shaft (normalized cell coords)
    'lw':        2.5,        # line width (points)
    'hw':        0.019,      # arrowhead width
    'hl':        0.019,      # arrowhead length
    'fs_vol':    12,         # volume label font (points)
    'fs_street': 10,         # street name font
    'fs_name':   12,         # intersection name font
    'fs_num':    12,         # intersection number font
}


# ── Preset for a single-cell rendering ─────────────────────────────────────────
def _single_cell_preset(fig_inches=4.0):
    """Return preset (s, lw, hw, hl, font sizes) scaled for a square figure of
    fig_inches × fig_inches inches. Clamp scale factor to [0.4, 1.2] so the
    arrows never blow up or vanish."""
    sf = min(fig_inches / DG_REF_CELL_W, fig_inches / DG_REF_CELL_H)
    sf = max(0.4, min(sf, 1.2))
    b = DG_BASE
    return {
        's':         round(b['s']         * sf, 4),
        'lw':        max(1.2, b['lw']     * sf),
        'hw':        round(b['hw']        * sf, 4),
        'hl':        round(b['hl']        * sf, 4),
        'fs_vol':    max(6,  round(b['fs_vol']    * sf, 1)),
        'fs_street': max(5,  round(b['fs_street'] * sf, 1)),
        'fs_name':   max(6,  round(b['fs_name']   * sf, 1)),
        'fs_num':    max(6,  round(b['fs_num']    * sf, 1)),
        'sf':        sf,
        'fig_inches': fig_inches,
    }


# ── Arrow primitives ───────────────────────────────────────────────────────────
def _dg_arrow(ax, points, lw=2.5, hw=0.019, hl=0.019):
    """Draw a MUTCD-style polyline arrow in DG_GREY.

    `points`: list of (x, y) tuples — at least 2 points. Arrowhead placed at
    the final point, oriented along the final segment.
    """
    if not points or len(points) < 2:
        return
    x_last, y_last = points[-1]
    x_prev, y_prev = points[-2]
    dx = x_last - x_prev
    dy = y_last - y_prev
    ln = np.sqrt(dx * dx + dy * dy)
    if ln < 1e-6:
        return

    # Trim the last segment so the line doesn't run into the arrowhead.
    sx = x_last - (hl * dx / ln)
    sy = y_last - (hl * dy / ln)
    xs = [p[0] for p in points[:-1]] + [sx]
    ys = [p[1] for p in points[:-1]] + [sy]
    ax.plot(xs, ys, color=DG_GREY, lw=lw,
            solid_capstyle='round', solid_joinstyle='miter', zorder=8)

    # Arrowhead triangle at the final tip
    a = np.arctan2(dy, dx)
    tip = np.array([x_last, y_last])
    L = tip + hw * np.array([-np.sin(a),  np.cos(a)]) - hl * np.array([np.cos(a), np.sin(a)])
    R = tip - hw * np.array([-np.sin(a),  np.cos(a)]) - hl * np.array([np.cos(a), np.sin(a)])
    ax.add_patch(MplPolygon([tip, L, R], closed=True,
                 facecolor=DG_GREY, edgecolor=DG_GREY, lw=0.5, zorder=9))


def _dg_get_arrow(ap, mv, cx, cy, s):
    """Return polyline points [(x, y), ...] for one movement arrow.

    MUTCD-style right-angle polylines for L/R, a single segment for T, and a
    ∩-shaped 4-point loop for U-turns with the arrowhead pointing back the
    way the vehicle came from. (cx, cy) is the lane position; everything is
    relative to that.
    """
    if ap == 'NB':                                # vehicle flow: south → north
        if mv == 'T':
            return [(cx, cy - s * 0.5), (cx, cy + s * 0.5)]
        if mv == 'L':                              # bend west
            return [(cx, cy - s * 0.5), (cx, cy + s * 0.15), (cx - s * 0.9, cy + s * 0.15)]
        if mv == 'R':                              # bend east
            return [(cx, cy - s * 0.5), (cx, cy + s * 0.15), (cx + s * 0.9, cy + s * 0.15)]
        if mv == 'U':                              # loop WEST (driver's left), return south
            return [
                (cx,            cy - s * 0.5),
                (cx,            cy + s * 0.35),
                (cx - s * 0.40, cy + s * 0.35),
                (cx - s * 0.40, cy - s * 0.5),
            ]
    elif ap == 'SB':                              # vehicle flow: north → south
        if mv == 'T':
            return [(cx, cy + s * 0.5), (cx, cy - s * 0.5)]
        if mv == 'L':                              # bend east (driver's left on SB)
            return [(cx, cy + s * 0.5), (cx, cy - s * 0.15), (cx + s * 0.9, cy - s * 0.15)]
        if mv == 'R':                              # bend west
            return [(cx, cy + s * 0.5), (cx, cy - s * 0.15), (cx - s * 0.9, cy - s * 0.15)]
        if mv == 'U':                              # loop EAST (driver's left), return north
            return [
                (cx,            cy + s * 0.5),
                (cx,            cy - s * 0.35),
                (cx + s * 0.40, cy - s * 0.35),
                (cx + s * 0.40, cy + s * 0.5),
            ]
    elif ap == 'EB':                              # vehicle flow: west → east
        if mv == 'T':
            return [(cx - s * 0.5, cy), (cx + s * 0.5, cy)]
        if mv == 'L':                              # bend north
            return [(cx - s * 0.5, cy), (cx + s * 0.15, cy), (cx + s * 0.15, cy + s * 0.9)]
        if mv == 'R':                              # bend south
            return [(cx - s * 0.5, cy), (cx + s * 0.15, cy), (cx + s * 0.15, cy - s * 0.9)]
        if mv == 'U':                              # loop NORTH (driver's left), return west
            return [
                (cx - s * 0.5,  cy),
                (cx + s * 0.35, cy),
                (cx + s * 0.35, cy + s * 0.40),
                (cx - s * 0.5,  cy + s * 0.40),
            ]
    elif ap == 'WB':                              # vehicle flow: east → west
        if mv == 'T':
            return [(cx + s * 0.5, cy), (cx - s * 0.5, cy)]
        if mv == 'L':                              # bend south
            return [(cx + s * 0.5, cy), (cx - s * 0.15, cy), (cx - s * 0.15, cy - s * 0.9)]
        if mv == 'R':                              # bend north
            return [(cx + s * 0.5, cy), (cx - s * 0.15, cy), (cx - s * 0.15, cy + s * 0.9)]
        if mv == 'U':                              # loop SOUTH (driver's left), return east
            return [
                (cx + s * 0.5,  cy),
                (cx - s * 0.35, cy),
                (cx - s * 0.35, cy - s * 0.40),
                (cx + s * 0.5,  cy - s * 0.40),
            ]
    return None


def _dg_lane_positions(ap, qcx, qcy, sp):
    """Lane positions median→curb for each approach. U-turn sits 2.5 slots
    beyond cluster centre on the median side, giving the U's return shaft
    clearance from the L turn's horizontal bend."""
    if ap == 'NB':
        return [('L', qcx - sp,       qcy), ('T', qcx, qcy), ('R', qcx + sp, qcy),
                ('U', qcx - 2.5 * sp, qcy)]
    elif ap == 'SB':
        return [('L', qcx + sp,       qcy), ('T', qcx, qcy), ('R', qcx - sp, qcy),
                ('U', qcx + 2.5 * sp, qcy)]
    elif ap == 'EB':
        return [('L', qcx, qcy + sp),       ('T', qcx, qcy), ('R', qcx, qcy - sp),
                ('U', qcx, qcy + 2.5 * sp)]
    elif ap == 'WB':
        return [('L', qcx, qcy - sp),       ('T', qcx, qcy), ('R', qcx, qcy + sp),
                ('U', qcx, qcy - 2.5 * sp)]
    return []


def _dg_stop_sign(ax, ap, cx, cy):
    """Stop sign with bar facing approaching traffic. Position 0.06 from center."""
    r = 0.016; sl = 0.030; sk = 0.020; off = 0.038; pos = 0.06; lw_s = 1.3
    if ap == 'NB':
        ox, oy = cx + off, cy - pos
        ax.plot([ox, ox], [oy + r, oy + r + sk], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox, oy), r, facecolor=DG_WHITE, edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox - sl, ox + sl], [oy - r, oy - r], color=DG_BLACK, lw=lw_s * 1.4, zorder=9)
    elif ap == 'SB':
        ox, oy = cx - off, cy + pos
        ax.plot([ox, ox], [oy - r - sk, oy - r], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox, oy), r, facecolor=DG_WHITE, edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox - sl, ox + sl], [oy + r, oy + r], color=DG_BLACK, lw=lw_s * 1.4, zorder=9)
    elif ap == 'EB':
        ox, oy = cx - pos, cy - off
        ax.plot([ox + r, ox + r + sk], [oy, oy], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox, oy), r, facecolor=DG_WHITE, edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox - r, ox - r], [oy - sl, oy + sl], color=DG_BLACK, lw=lw_s * 1.4, zorder=9)
    elif ap == 'WB':
        ox, oy = cx + pos, cy + off
        ax.plot([ox - r - sk, ox - r], [oy, oy], color=DG_BLACK, lw=lw_s, zorder=7)
        ax.add_patch(MplCircle((ox, oy), r, facecolor=DG_WHITE, edgecolor=DG_BLACK, lw=lw_s, zorder=8))
        ax.plot([ox + r, ox + r], [oy - sl, oy + sl], color=DG_BLACK, lw=lw_s * 1.4, zorder=9)


# ── Cell + approach drawing ────────────────────────────────────────────────────
def _dg_draw_approach(ax, ap, cx, cy, u_vols, b_vols, p, label_fn, overrides=None):
    """Draw 3 arrows + volume labels for one approach using preset p.

    label_fn: callable(u_int, b_int) → (text_str, color_hex). Determines what
    each volume label says and what colour it's drawn in.

    Stage 5: `overrides` is an optional {movement_key: value} dict for this
    intersection's period. When a key is overridden, `b` is replaced with
    the override value AND the label gets a "*" suffix so engineer
    interventions are spottable at a glance.
    """
    s   = p['s']
    sp  = s * DG_SP_F
    lw  = p['lw']; hw = p['hw']; hl = p['hl']
    dx, dy = DG_CLUSTERS[ap]
    qcx, qcy = cx + dx, cy + dy
    lanes = _dg_lane_positions(ap, qcx, qcy, sp)
    vns = s * DG_VOL_NS
    vew = s * DG_VOL_EW
    fs  = p['fs_vol']
    overrides = overrides or {}

    for mv, ax_, ay_ in lanes:
        points = _dg_get_arrow(ap, mv, ax_, ay_, s)
        if not points:
            continue
        _dg_arrow(ax, points, lw=lw, hw=hw, hl=hl)
        key = f"{ap}{mv}"
        u = int(u_vols.get(key, 0) or 0)
        b = int(b_vols.get(key, 0) or 0)
        is_overridden = key in overrides
        if is_overridden:
            b = int(overrides[key] or 0)
        lbl, color = label_fn(u, b)
        if is_overridden:
            lbl = f"{lbl}*"
        if ap == 'NB':
            ax.text(ax_, ay_ - vns, lbl, fontsize=fs, color=color,
                    rotation=90, ha='center', va='top', zorder=10)
        elif ap == 'SB':
            ax.text(ax_, ay_ + vns, lbl, fontsize=fs, color=color,
                    rotation=90, ha='center', va='bottom', zorder=10)
        elif ap == 'EB':
            ax.text(ax_ - vew, ay_, lbl, fontsize=fs, color=color,
                    ha='right', va='center', zorder=10)
        elif ap == 'WB':
            ax.text(ax_ + vew, ay_, lbl, fontsize=fs, color=color,
                    ha='left', va='center', zorder=10)


def _fit_street_label(text, base_fs, fig_inches, max_text_extent, min_fs=6.0):
    """Wrap a street-name label so it fits along an arm without colliding with
    the title / badge / cell edge.

    Strategy:
      1. Split on ' / ' (combined route names like "South H St / Cabarillo Hwy"
         become two lines).
      2. Any line still longer than soft_limit chars gets split once more at the
         space nearest its midpoint.
      3. Font size shrinks proportionally so the longest line fits within
         max_text_extent (axis-fraction units), floored at min_fs pt.

    Returns (rendered_text, fs). The text may contain '\\n'; matplotlib renders
    it as multi-line natively. fs is unchanged when the label already fits.
    """
    if not text:
        return text, base_fs

    # Step 1 — wrap on ' / '
    if ' / ' in text:
        lines = [s.strip() for s in text.split(' / ') if s.strip()]
    else:
        lines = [text]

    # Step 2 — secondary wrap on midpoint space for any still-long line
    soft_limit = 18
    wrapped = []
    for line in lines:
        if len(line) <= soft_limit or ' ' not in line:
            wrapped.append(line)
            continue
        mid = len(line) // 2
        left = line.rfind(' ', 0, mid)
        right = line.find(' ', mid)
        if left < 0 and right < 0:
            wrapped.append(line)
            continue
        if left < 0:
            sp = right
        elif right < 0:
            sp = left
        else:
            sp = left if (mid - left) <= (right - mid) else right
        wrapped.append(line[:sp].strip())
        wrapped.append(line[sp + 1:].strip())

    longest = max((len(L) for L in wrapped), default=0)
    if longest == 0:
        return '\n'.join(wrapped), base_fs

    # Step 3 — proportional shrink. Empirical char-width coefficient for the
    # bold sans-serif fallback matplotlib uses: ≈ 0.55 × glyph height.
    # Glyph height in axis-fraction units = fs / (72 * fig_inches).
    char_w_per_pt = 0.55 / (72.0 * fig_inches)
    fs = base_fs
    if longest * fs * char_w_per_pt > max_text_extent:
        fs = max_text_extent / (longest * char_w_per_pt)
    fs = max(min_fs, min(fs, base_fs))
    return '\n'.join(wrapped), round(fs, 1)


def _dg_draw_cell(ax, geo, u_vols, b_vols, p, label_fn, overrides=None, period_label=None):
    """Draw one full intersection cell into `ax` using preset p.

    period_label: optional 'AM'/'PM' tag drawn top-right (used by the batch
    grid so each cell shows its period; single-cell renders pass None)."""
    active  = geo.get('active_legs', ['NB', 'SB', 'EB', 'WB'])
    control = geo.get('control', 'Signalized')
    streets = geo.get('streets', {})
    n, name = geo['num'], geo['name']
    arm     = DG_ARM

    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_aspect('equal')
    ax.set_facecolor(DG_WHITE)
    for side in ['top', 'bottom', 'left', 'right']:
        ax.spines[side].set_visible(True)
        ax.spines[side].set_linewidth(0.8)
        ax.spines[side].set_color(DG_BLACK)
    ax.set_xticks([]); ax.set_yticks([])

    cx, cy = 0.5, 0.5
    rk = dict(color=DG_GREY, lw=2.8, solid_capstyle='butt', zorder=5)
    if 'NB' in active: ax.plot([cx, cx],         [cy, cy - arm], **rk)
    if 'SB' in active: ax.plot([cx, cx],         [cy, cy + arm], **rk)
    if 'EB' in active: ax.plot([cx, cx - arm],   [cy, cy],       **rk)
    if 'WB' in active: ax.plot([cx, cx + arm],   [cy, cy],       **rk)

    if 'Signal' in control:
        ax.add_patch(MplCircle((cx, cy), 0.022, facecolor=DG_WHITE,
                     edgecolor=DG_BLACK, lw=1.5, zorder=6))
    elif 'Roundabout' in control:
        # Outer ring (same size as signal circle, white fill).
        ax.add_patch(MplCircle((cx, cy), 0.022, facecolor=DG_WHITE,
                     edgecolor=DG_BLACK, lw=1.5, zorder=6))
        # Inner filled circle — central island, ~half radius.
        ax.add_patch(MplCircle((cx, cy), 0.010, facecolor=DG_BLACK,
                     edgecolor=DG_BLACK, lw=0.5, zorder=7))
    else:
        ax.plot(cx, cy, 'k.', markersize=4, zorder=6)
        for ap in geo.get('stopped_approaches', []):
            _dg_stop_sign(ax, ap, cx, cy)

    # Street labels — wrap on ' / ' and auto-shrink long names so they stay
    # clear of the title (y≈0.955), the number badge (top-left), and the cell
    # border. NS labels are rotated 90°, so their "length" extends along the
    # vertical arm — same overflow risk toward the title as EW does laterally.
    fig_inches = p.get('fig_inches', 4.0)
    ns_raw = streets.get('NS', '')
    ew_raw = streets.get('EW', '')
    # NS radial space: from label center (cy ± arm*0.70 = 0.766 / 0.234) to title
    # (y=0.955) is 0.189 axis units half-extent; doubled = 0.378. Use 0.34 to
    # leave a small safety margin from the title.
    ns_text, ns_fs = _fit_street_label(ns_raw, p['fs_street'], fig_inches, 0.34)
    # EW lateral space: from label center (cx ± arm*0.70) to the nearer cell edge
    # is 0.234 axis units half-extent; doubled = 0.468. Use 0.44 for margin.
    ew_text, ew_fs = _fit_street_label(ew_raw, p['fs_street'], fig_inches, 0.44)
    nk_common = dict(color=DG_BLACK, fontweight='bold',
                     ha='center', va='center', zorder=7)
    if ns_text:
        if 'NB' in active: ax.text(cx - 0.052, cy - arm * 0.70, ns_text, rotation=90, fontsize=ns_fs, **nk_common)
        if 'SB' in active: ax.text(cx + 0.052, cy + arm * 0.70, ns_text, rotation=90, fontsize=ns_fs, **nk_common)
    if ew_text:
        if 'EB' in active: ax.text(cx - arm * 0.70, cy + 0.044, ew_text, fontsize=ew_fs, **nk_common)
        if 'WB' in active: ax.text(cx + arm * 0.70, cy - 0.044, ew_text, fontsize=ew_fs, **nk_common)

    for ap in active:
        _dg_draw_approach(ax, ap, cx, cy, u_vols, b_vols, p, label_fn, overrides)

    # Number badge top-left + name banner top-center
    ax.add_patch(MplCircle((0.082, 0.922), 0.048, facecolor=DG_WHITE,
                 edgecolor=DG_BLACK, lw=1.0, zorder=10))
    ax.text(0.082, 0.922, str(n), fontsize=p['fs_num'], color=DG_BLACK,
            fontweight='bold', ha='center', va='center', zorder=11)
    ax.text(0.5, 0.955, name.replace(' & ', ' @ '), fontsize=p['fs_name'],
            color=DG_BLACK, fontweight='bold', ha='center', va='center')
    if period_label:
        ax.text(0.92, 0.922, period_label, fontsize=p['fs_num'], color=DG_BLACK,
                fontweight='bold', ha='right', va='center', zorder=11)


# ── View-mode label functions ──────────────────────────────────────────────────
def _make_label_fn(view_mode):
    """Return a label_fn(u, b) → (text, color_hex) for the given view mode."""
    if view_mode == 'combined':
        return lambda u, b: (f"{u} ({b})", DG_BLACK)
    if view_mode == 'balanced':
        return lambda u, b: (f"{b}", DG_BLACK)
    if view_mode == 'unbalanced':
        return lambda u, b: (f"{u}", DG_BLACK)
    if view_mode == 'delta':
        def fn(u, b):
            d = b - u
            if d > 0: return (f"+{d}", DG_DELTA_UP)
            if d < 0: return (f"{d}",  DG_DELTA_DOWN)
            return ("0", DG_BLACK)
        return fn
    raise ValueError(f"unknown view_mode: {view_mode!r}")


VIEW_MODES = ('combined', 'balanced', 'unbalanced', 'delta')


# ── Public API ─────────────────────────────────────────────────────────────────
FIG_INCHES = 4.0
DPI = 150


# Stage 10.4: caption (annotation) layout.
DG_CAP_WIDTH    = 46     # wrap width in chars (~fits a 4in-wide figure at fs 9)
DG_CAP_MAX_LINES = 3     # truncate longer notes with an ellipsis
DG_CAP_FS       = 9      # caption font size (points)


def _wrap_caption(text):
    """Wrap an annotation to the caption band; truncate to DG_CAP_MAX_LINES
    with an ellipsis. Returns (wrapped_text, line_count) or ('', 0) if empty."""
    import textwrap
    text = ' '.join((text or '').split())   # collapse whitespace/newlines
    if not text:
        return '', 0
    lines = textwrap.wrap(text, width=DG_CAP_WIDTH) or ['']
    if len(lines) > DG_CAP_MAX_LINES:
        lines = lines[:DG_CAP_MAX_LINES]
        lines[-1] = lines[-1].rstrip() + '…'
    return '\n'.join(lines), len(lines)


def render_single_diagram(intersection_geo, u_vols, b_vols, view_mode='combined',
                          overrides=None, annotation=None):
    """Render one intersection as a PNG.

    Args:
      intersection_geo, u_vols, b_vols, view_mode: as before.
      overrides: optional dict {movement_key: value} of engineer overrides for
                 this intersection in the period being rendered. When provided,
                 each overridden movement's balanced value is replaced and the
                 label gets a "*" suffix so reviewers can spot interventions.
      annotation: optional free-text note (Stage 10.4). When present it renders
                 as a wrapped caption strip in a reserved band below the cell.
                 The square cell is pinned to the top so its geometry is
                 pixel-identical whether or not a caption is present.

    Returns: bytes (PNG data).
    Raises:  ValueError on unknown view_mode.
    """
    label_fn = _make_label_fn(view_mode)
    p = _single_cell_preset(FIG_INCHES)

    caption, n_lines = _wrap_caption(annotation)
    if caption:
        # Reserve a bottom band sized to the line count; the cell stays a
        # square FIG_INCHES×FIG_INCHES box pinned to the top of a taller figure.
        cap_h = 0.26 + 0.17 * n_lines        # inches
        fig_h = FIG_INCHES + cap_h
        bottom_frac = cap_h / fig_h
        fig = plt.figure(figsize=(FIG_INCHES, fig_h), facecolor=DG_WHITE)
        ax = fig.add_subplot(1, 1, 1)
        ax.set_position([0, bottom_frac, 1, FIG_INCHES / fig_h])
    else:
        fig_h = FIG_INCHES
        fig = plt.figure(figsize=(FIG_INCHES, fig_h), facecolor=DG_WHITE)
        ax = fig.add_subplot(1, 1, 1)
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    _dg_draw_cell(ax, intersection_geo, u_vols or {}, b_vols or {}, p, label_fn, overrides or {})

    if caption:
        fig.text(0.5, bottom_frac / 2, f"Note: {caption}", ha='center', va='center',
                 fontsize=DG_CAP_FS, color=DG_BLACK, linespacing=1.3)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=DPI, facecolor=DG_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


GRID_DEFAULT_COLS = 3


def render_diagram_grid(cells, view_mode='combined', cols=GRID_DEFAULT_COLS, title=None):
    """Stage 10.5: compose multiple intersection cells into ONE print-sized
    composite PNG grid. Reuses _dg_draw_cell — each cell is a square
    FIG_INCHES×FIG_INCHES subplot, so a 3-wide grid is ~12in across.

    Args:
      cells: list of {geo, u_vols, b_vols, overrides, period_label}.
             Per-cell engineer annotations are NOT drawn here (they'd break
             the uniform grid) — they live on the individual per-card PNGs.
      view_mode: label mode applied to every cell.
      cols: columns in the grid (rows derived).
      title: optional banner drawn across the top.

    Returns: bytes (PNG). Raises ValueError if `cells` is empty.
    """
    n = len(cells)
    if n == 0:
        raise ValueError("render_diagram_grid: no cells to render")

    label_fn = _make_label_fn(view_mode)
    cols = max(1, min(int(cols), n))
    rows = math.ceil(n / cols)
    cell_in = FIG_INCHES
    p = _single_cell_preset(cell_in)

    title_h = 0.6 if title else 0.0
    fig_w = cols * cell_in
    fig_h = rows * cell_in + title_h
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=DG_WHITE)

    cell_frac_w = 1.0 / cols
    grid_frac_h = (rows * cell_in) / fig_h          # fraction below the title band
    cell_frac_h = grid_frac_h / rows

    for i, c in enumerate(cells):
        r = i // cols
        col = i % cols
        left = col * cell_frac_w
        # row 0 at the top, working down (title band occupies the very top)
        bottom = (rows - 1 - r) * cell_frac_h
        ax = fig.add_axes([left, bottom, cell_frac_w, cell_frac_h])
        _dg_draw_cell(
            ax, c['geo'], c.get('u_vols') or {}, c.get('b_vols') or {},
            p, label_fn, c.get('overrides') or {}, period_label=c.get('period_label'),
        )

    if title:
        fig.text(0.5, 1 - (title_h / fig_h) / 2, title, ha='center', va='center',
                 fontsize=14, fontweight='bold', color=DG_BLACK)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=DPI, facecolor=DG_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── PRD-03: corridor diagram with link-volume labels ─────────────────────────
def _primary_direction_pair(corridor_dir):
    """Split a corridor dir like 'EB/WB' or 'NB/SB' into the forward + reverse
    single-direction codes. Returns (forward, reverse). Forward is the first
    token (the corridor's stated primary direction)."""
    if not corridor_dir or '/' not in corridor_dir:
        return (None, None)
    a, b = corridor_dir.split('/', 1)
    return (a.strip(), b.strip())


def _segment_label_for_pair(from_num, to_num, resolved_links, corridor_dir):
    """Find the resolved-links entry for the segment between two adjacent
    intersections in the corridor's primary direction.

    Tries the corridor's forward direction first (e.g. EB), then the reverse
    (WB) so a label is rendered regardless of which way `from_num` → `to_num`
    points. Returns (text, volume) or (None, None) if no match.
    """
    if not resolved_links:
        return (None, None)
    fwd, rev = _primary_direction_pair(corridor_dir)

    def _find(f, t, direction):
        for r in resolved_links:
            if (int(r.get('fromNum')) == f
                    and int(r.get('toNum')) == t
                    and r.get('direction') == direction):
                return r
        return None

    chosen = None
    if fwd:
        chosen = _find(from_num, to_num, fwd)
    if chosen is None and rev:
        chosen = _find(from_num, to_num, rev)
    # Try the swapped pair too — corridor cell ordering doesn't always match
    # the resolved-link key ordering when the link goes the "other" way.
    if chosen is None and fwd:
        chosen = _find(to_num, from_num, fwd)
    if chosen is None and rev:
        chosen = _find(to_num, from_num, rev)

    if chosen is None:
        return (None, None)
    vol = chosen.get('volume')
    if vol is None:
        return (None, None)
    text = f"{int(chosen['fromNum'])}→{int(chosen['toNum'])}: {int(round(float(vol)))} veh"
    return (text, float(vol))


def render_corridor_diagram(cells, resolved_links, corridor_dir, period_label,
                            view_mode='combined', cols=GRID_DEFAULT_COLS,
                            title=None):
    """PRD-03: render the corridor as a grid of intersection cells with
    link-volume labels drawn on the corridor segments BETWEEN adjacent cells.

    Per-cell rendering is byte-identical to render_diagram_grid (same preset,
    same _dg_draw_cell call, same layout math). The only addition is a thin
    label drawn at each adjacent-pair boundary in figure coords.

    Args:
      cells: list of {geo, u_vols, b_vols, overrides, period_label}, in
             corridor order. Adjacent entries that share a row will get a
             segment label between them.
      resolved_links: list[{fromNum, toNum, direction, volume}] for THIS period
                      (i.e. lastRun.resolvedLinks[period]). May be empty —
                      the diagram still renders cleanly with no labels.
      corridor_dir: 'EB/WB' or 'NB/SB' — used to pick which resolved-link
                    direction is the corridor's primary flow.
      period_label: 'AM' or 'PM' — drawn as the per-cell tag AND used in the
                    title if title is None.
      view_mode: label mode applied to every cell.
      cols: columns in the grid (rows derived).
      title: optional banner drawn across the top. If None, no banner.

    Returns: bytes (PNG). Raises ValueError if `cells` is empty.
    """
    n = len(cells)
    if n == 0:
        raise ValueError("render_corridor_diagram: no cells to render")

    label_fn = _make_label_fn(view_mode)
    cols = max(1, min(int(cols), n))
    rows = math.ceil(n / cols)
    cell_in = FIG_INCHES
    p = _single_cell_preset(cell_in)

    title_h = 0.6 if title else 0.0
    fig_w = cols * cell_in
    fig_h = rows * cell_in + title_h
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=DG_WHITE)

    cell_frac_w = 1.0 / cols
    grid_frac_h = (rows * cell_in) / fig_h
    cell_frac_h = grid_frac_h / rows

    # Apply per-cell period_label override so AM/PM tag shows on every cell.
    for i, c in enumerate(cells):
        r = i // cols
        col = i % cols
        left = col * cell_frac_w
        bottom = (rows - 1 - r) * cell_frac_h
        ax = fig.add_axes([left, bottom, cell_frac_w, cell_frac_h])
        _dg_draw_cell(
            ax, c['geo'], c.get('u_vols') or {}, c.get('b_vols') or {},
            p, label_fn, c.get('overrides') or {},
            period_label=c.get('period_label') or period_label,
        )

    # Segment labels: walk adjacent pairs that share a row. The label sits at
    # the cell boundary in figure-fraction coords, centered vertically on the
    # cell's road axis (y = cell midpoint). Font matches the per-cell volume
    # label font so it reads as part of the diagram, not chrome.
    fs_seg = p['fs_vol']
    for i in range(n - 1):
        r = i // cols
        r_next = (i + 1) // cols
        if r != r_next:
            continue                    # row wrap — no in-figure adjacency
        a_geo = cells[i]['geo']
        b_geo = cells[i + 1]['geo']
        text, _vol = _segment_label_for_pair(
            int(a_geo['num']), int(b_geo['num']), resolved_links, corridor_dir,
        )
        if text is None:
            continue
        col_a = i % cols
        # Boundary x sits between cell i and cell i+1 in figure coords.
        x = (col_a + 1) * cell_frac_w
        # y centered on the cell's interior — cells span [bottom, bottom+cell_frac_h]
        # and the road axis runs through cy=0.5 in axis coords.
        bottom = (rows - 1 - r) * cell_frac_h
        y = bottom + cell_frac_h * 0.5
        # White bbox keeps the label readable when it lands over the road arm
        # or arrow geometry. No new color encoding — pure black text.
        fig.text(
            x, y, text, ha='center', va='center',
            fontsize=fs_seg, color=DG_BLACK, fontweight='bold', zorder=20,
            bbox=dict(facecolor=DG_WHITE, edgecolor=DG_BLACK, lw=0.6,
                      boxstyle='round,pad=0.25'),
        )

    if title:
        fig.text(0.5, 1 - (title_h / fig_h) / 2, title, ha='center', va='center',
                 fontsize=14, fontweight='bold', color=DG_BLACK)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=DPI, facecolor=DG_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
