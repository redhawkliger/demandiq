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
    }


# ── Arrow primitives (locked from v26) ─────────────────────────────────────────
def _dg_arrow(ax, x0, y0, x1, y1, curve=0.0, lw=2.5, hw=0.019, hl=0.019):
    """Draw a (optionally bezier-curved) arrow in DG_GREY."""
    if curve == 0:
        dx = x1 - x0; dy = y1 - y0; ln = np.sqrt(dx**2 + dy**2)
        if ln < 1e-6: return
        sx = x1 - (hl * dx / ln); sy = y1 - (hl * dy / ln)
        ax.plot([x0, sx], [y0, sy], color=DG_GREY, lw=lw,
                solid_capstyle='round', zorder=8)
        a = np.arctan2(dy, dx); tip = np.array([x1, y1])
        L = tip + hw * np.array([-np.sin(a), np.cos(a)]) - hl * np.array([np.cos(a), np.sin(a)])
        R = tip - hw * np.array([-np.sin(a), np.cos(a)]) - hl * np.array([np.cos(a), np.sin(a)])
        ax.add_patch(MplPolygon([tip, L, R], closed=True,
                     facecolor=DG_GREY, edgecolor=DG_GREY, lw=0.5, zorder=9))
    else:
        mx = (x0 + x1) / 2; my = (y0 + y1) / 2; dx = x1 - x0; dy = y1 - y0
        px = -dy; py = dx; n = np.sqrt(px**2 + py**2)
        if n > 0: px /= n; py /= n
        cx2 = mx + curve * px; cy2 = my + curve * py
        t = np.linspace(0, 0.85, 40)
        xs = (1 - t)**2 * x0 + 2 * (1 - t) * t * cx2 + t**2 * x1
        ys = (1 - t)**2 * y0 + 2 * (1 - t) * t * cy2 + t**2 * y1
        ax.plot(xs, ys, color=DG_GREY, lw=lw, solid_capstyle='round', zorder=8)
        te = 0.92
        tx = 2 * (1 - te) * (cx2 - x0) + 2 * te * (x1 - cx2)
        ty = 2 * (1 - te) * (cy2 - y0) + 2 * te * (y1 - cy2)
        a = np.arctan2(ty, tx); tip = np.array([x1, y1])
        L = tip + hw * np.array([-np.sin(a), np.cos(a)]) - hl * np.array([np.cos(a), np.sin(a)])
        R = tip - hw * np.array([-np.sin(a), np.cos(a)]) - hl * np.array([np.cos(a), np.sin(a)])
        ax.add_patch(MplPolygon([tip, L, R], closed=True,
                     facecolor=DG_GREY, edgecolor=DG_GREY, lw=0.5, zorder=9))


def _dg_get_arrow(ap, mv, cx, cy, s):
    """Arrow start/end/curve geometry — approved from v26. s = arrow shaft scale."""
    c = DG_C
    if ap == 'NB':
        if mv == 'L': return cx,        cy - s * 0.35, cx - s * 0.9, cy + s * 0.4, -c
        if mv == 'T': return cx,        cy - s * 0.5,  cx,           cy + s * 0.5,  0
        if mv == 'R': return cx,        cy - s * 0.35, cx + s * 0.9, cy + s * 0.4, +c
    elif ap == 'SB':
        if mv == 'L': return cx,        cy + s * 0.35, cx + s * 0.9, cy - s * 0.4, -c
        if mv == 'T': return cx,        cy + s * 0.5,  cx,           cy - s * 0.5,  0
        if mv == 'R': return cx,        cy + s * 0.35, cx - s * 0.9, cy - s * 0.4, +c
    elif ap == 'EB':
        if mv == 'L': return cx - s * 0.35, cy,        cx + s * 0.4, cy + s * 0.9, -c
        if mv == 'T': return cx - s * 0.5,  cy,        cx + s * 0.5, cy,            0
        if mv == 'R': return cx - s * 0.35, cy,        cx + s * 0.4, cy - s * 0.9, +c
    elif ap == 'WB':
        if mv == 'L': return cx + s * 0.35, cy,        cx - s * 0.4, cy - s * 0.9, -c
        if mv == 'T': return cx + s * 0.5,  cy,        cx - s * 0.5, cy,            0
        if mv == 'R': return cx + s * 0.35, cy,        cx - s * 0.4, cy + s * 0.9, +c
    return None


def _dg_lane_positions(ap, qcx, qcy, sp):
    """Lane positions median→curb for each approach."""
    if   ap == 'NB': return [('L', qcx - sp, qcy), ('T', qcx, qcy), ('R', qcx + sp, qcy)]
    elif ap == 'SB': return [('L', qcx + sp, qcy), ('T', qcx, qcy), ('R', qcx - sp, qcy)]
    elif ap == 'EB': return [('L', qcx, qcy + sp), ('T', qcx, qcy), ('R', qcx, qcy - sp)]
    elif ap == 'WB': return [('L', qcx, qcy - sp), ('T', qcx, qcy), ('R', qcx, qcy + sp)]
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
def _dg_draw_approach(ax, ap, cx, cy, u_vols, b_vols, p, label_fn):
    """Draw 3 arrows + volume labels for one approach using preset p.

    label_fn: callable(u_int, b_int) → (text_str, color_hex). Determines what
    each volume label says and what colour it's drawn in.
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

    for mv, ax_, ay_ in lanes:
        geom = _dg_get_arrow(ap, mv, ax_, ay_, s)
        if geom is None:
            continue
        x0, y0, x1, y1, cv = geom
        _dg_arrow(ax, x0, y0, x1, y1, curve=cv, lw=lw, hw=hw, hl=hl)
        key = f"{ap}{mv}"
        u = int(u_vols.get(key, 0) or 0)
        b = int(b_vols.get(key, 0) or 0)
        lbl, color = label_fn(u, b)
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


def _dg_draw_cell(ax, geo, u_vols, b_vols, p, label_fn):
    """Draw one full intersection cell into `ax` using preset p."""
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
    else:
        ax.plot(cx, cy, 'k.', markersize=4, zorder=6)
        for ap in geo.get('stopped_approaches', []):
            _dg_stop_sign(ax, ap, cx, cy)

    ns = streets.get('NS', '')
    ew = streets.get('EW', '')
    nk = dict(fontsize=p['fs_street'], color=DG_BLACK, fontweight='bold',
              ha='center', va='center', zorder=7)
    if ns:
        if 'NB' in active: ax.text(cx - 0.052, cy - arm * 0.70, ns, rotation=90, **nk)
        if 'SB' in active: ax.text(cx + 0.052, cy + arm * 0.70, ns, rotation=90, **nk)
    if ew:
        if 'EB' in active: ax.text(cx - arm * 0.70, cy + 0.044, ew, **nk)
        if 'WB' in active: ax.text(cx + arm * 0.70, cy - 0.044, ew, **nk)

    for ap in active:
        _dg_draw_approach(ax, ap, cx, cy, u_vols, b_vols, p, label_fn)

    # Number badge top-left + name banner top-center
    ax.add_patch(MplCircle((0.082, 0.922), 0.048, facecolor=DG_WHITE,
                 edgecolor=DG_BLACK, lw=1.0, zorder=10))
    ax.text(0.082, 0.922, str(n), fontsize=p['fs_num'], color=DG_BLACK,
            fontweight='bold', ha='center', va='center', zorder=11)
    ax.text(0.5, 0.955, name.replace(' & ', ' @ '), fontsize=p['fs_name'],
            color=DG_BLACK, fontweight='bold', ha='center', va='center')


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


def render_single_diagram(intersection_geo, u_vols, b_vols, view_mode='combined'):
    """Render one intersection as a PNG.

    Returns: bytes (PNG data).
    Raises:  ValueError on unknown view_mode.
    """
    label_fn = _make_label_fn(view_mode)
    p = _single_cell_preset(FIG_INCHES)

    fig = plt.figure(figsize=(FIG_INCHES, FIG_INCHES), facecolor=DG_WHITE)
    ax = fig.add_subplot(1, 1, 1)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    _dg_draw_cell(ax, intersection_geo, u_vols or {}, b_vols or {}, p, label_fn)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=DPI, facecolor=DG_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
