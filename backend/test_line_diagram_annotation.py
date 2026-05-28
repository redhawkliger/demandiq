"""Stage 10.4 — per-intersection diagram annotation rendering.

Verifies:
  1. _wrap_caption wraps + truncates to DG_CAP_MAX_LINES with an ellipsis.
  2. render_single_diagram with an annotation reserves a bottom band (taller
     PNG, same width) while leaving the no-annotation render square/unchanged.

Run: python3.12 backend/test_line_diagram_annotation.py
"""
import sys, os, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image
from line_diagram import (
    render_single_diagram, render_diagram_grid, _wrap_caption,
    DG_CAP_MAX_LINES, FIG_INCHES, DPI,
)

GEO = {
    'num': 1, 'name': 'Main St & 1st Ave',
    'active_legs': ['NB', 'SB', 'EB', 'WB'],
    'control': 'Signalized',
    'streets': {'NS': '1st Ave', 'EW': 'Main St'},
    'stopped_approaches': [],
}
U = {'EBT': 1000, 'EBL': 80, 'WBT': 900, 'NBT': 200, 'SBT': 180}
B = {'EBT': 1050, 'EBL': 60, 'WBT': 950, 'NBT': 210, 'SBT': 190}


def _size(png):
    return Image.open(io.BytesIO(png)).size


def test_wrap_caption():
    assert _wrap_caption('') == ('', 0)
    assert _wrap_caption(None) == ('', 0)
    w, n = _wrap_caption('short note')
    assert n == 1 and w == 'short note', (w, n)
    # whitespace collapsed
    w, n = _wrap_caption('  multiple   spaces\n\there ')
    assert w == 'multiple spaces here', repr(w)
    # long text truncates to max lines with an ellipsis
    w, n = _wrap_caption('word ' * 200)
    assert n == DG_CAP_MAX_LINES, n
    assert w.endswith('…'), repr(w[-10:])
    print(f"  test_wrap_caption: PASS (truncates to {DG_CAP_MAX_LINES} lines + ellipsis)")


def test_render_reserves_band_for_annotation():
    base = render_single_diagram(GEO, U, B, 'combined')
    bw, bh = _size(base)
    assert bw == bh == int(FIG_INCHES * DPI), f"no-annotation should be square {bw}x{bh}"

    annotated = render_single_diagram(
        GEO, U, B, 'combined',
        annotation='RTOR prohibited NB; field count 2024-03-15')
    aw, ah = _size(annotated)
    assert aw == bw, f"width must be unchanged ({aw} != {bw})"
    assert ah > bh, f"annotated must be taller ({ah} not > {bh})"
    print(f"  test_render_reserves_band_for_annotation: PASS "
          f"(plain {bw}x{bh} → annotated {aw}x{ah})")


def test_empty_annotation_is_noop():
    base = render_single_diagram(GEO, U, B, 'combined')
    for empty in ('', '   ', None):
        same = render_single_diagram(GEO, U, B, 'combined', annotation=empty)
        assert _size(same) == _size(base), f"empty annotation {empty!r} changed size"
    print("  test_empty_annotation_is_noop: PASS")


# ─── Stage 10.5: composite diagram grid ────────────────────────────────────
def _grid_cell(num, period_label=None):
    return {
        'geo': {'num': num, 'name': f'Int {num} & Cross',
                'active_legs': ['NB', 'SB', 'EB', 'WB'], 'control': 'Signalized',
                'streets': {'NS': 'Cross', 'EW': 'Main'}, 'stopped_approaches': []},
        'u_vols': {'EBT': 1000, 'WBT': 900}, 'b_vols': {'EBT': 1050, 'WBT': 950},
        'overrides': {}, 'period_label': period_label,
    }


def test_grid_dimensions():
    cell_px = int(FIG_INCHES * DPI)
    # 5 cells, 3 cols → 2 rows
    png = render_diagram_grid([_grid_cell(i) for i in range(1, 6)], 'combined', cols=3)
    w, h = _size(png)
    assert w == 3 * cell_px, w
    assert h == 2 * cell_px, h
    # 10 cells (Both periods ×5), 3 cols → 4 rows
    both = []
    for i in range(1, 6):
        both += [_grid_cell(i, 'AM'), _grid_cell(i, 'PM')]
    w2, h2 = _size(render_diagram_grid(both, 'combined', cols=3))
    assert (w2, h2) == (3 * cell_px, 4 * cell_px), (w2, h2)
    print(f"  test_grid_dimensions: PASS (5→{w}x{h}, 10→{w2}x{h2})")


def test_grid_title_adds_band():
    base = _size(render_diagram_grid([_grid_cell(1)], 'combined', cols=3))
    titled = _size(render_diagram_grid([_grid_cell(1)], 'combined', cols=3, title='Corridor'))
    assert titled[0] == base[0], 'title must not change width'
    assert titled[1] > base[1], 'title adds a top band (taller)'
    print(f"  test_grid_title_adds_band: PASS ({base} → {titled})")


def test_grid_empty_raises():
    try:
        render_diagram_grid([], 'combined')
        assert False, 'empty cells should raise'
    except ValueError:
        pass
    print("  test_grid_empty_raises: PASS")


if __name__ == '__main__':
    tests = [
        test_wrap_caption,
        test_render_reserves_band_for_annotation,
        test_empty_annotation_is_noop,
        test_grid_dimensions,
        test_grid_title_adds_band,
        test_grid_empty_raises,
    ]
    passed = failed = 0
    for t in tests:
        print(f"Running {t.__name__}...")
        try:
            t(); passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}"); failed += 1
        except Exception:
            import traceback; traceback.print_exc(); failed += 1
    print(f"\n{'='*50}\n  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
