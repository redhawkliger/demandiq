"""Unit tests for the new NCHRP 255/765 turning-movement balancer.
Run: python3.12 -m pytest backend/test_balancer_nchrp.py -v
or directly: python3.12 backend/test_balancer_nchrp.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from balancer import (
    resolve_link_volumes,
    intersection_targets,
    furness_intersection,
    balance_nchrp,
    _build_links_by_int,
    _build_matrix,
    _extract_matrix,
    DIRECTION_SPEC,
    CELL_MOVEMENT,
)

FULL = {'EBL':0,'EBT':0,'EBR':0,'WBL':0,'WBT':0,'WBR':0,'NBL':0,'NBT':0,
        'NBR':0,'SBL':0,'SBT':0,'SBR':0,'WBU':0,'EBU':0,'NBU':0,'SBU':0}
def mk(d): m=dict(FULL); m.update(d); return m


# ─── Test 1 — 4x4 Furness on a known matrix ────────────────────────────────
def test_furness_4x4_known_answer():
    """Start matrix: cells all 10. Row targets [100,100,100,100], col targets
    same. Result must be 25 in every cell (every row and col sums to 100,
    proportions preserved)."""
    M = [[10.0]*4 for _ in range(4)]
    row_t = [100, 100, 100, 100]
    col_t = [100, 100, 100, 100]
    present = [True, True, True, True]
    M_out, conv, iters = furness_intersection(M, row_t, col_t, present, tol=0.01, max_iter=50)
    assert conv, f"didn't converge in {iters} iters"
    for r in range(4):
        for c in range(4):
            assert abs(M_out[r][c] - 25.0) < 0.05, f"cell ({r},{c}) = {M_out[r][c]}, expected 25"
    print(f"  test_furness_4x4_known_answer: PASS (converged in {iters} iter)")


# ─── Test 2 — link resolution: 'larger' vs 'average' ────────────────────────
def test_link_resolution_larger_vs_average():
    """Two intersections, one EB/WB link between them. Int 1's EB outflow
    sums to 278; Int 2's EB approach sums to 164. Resolution should be:
        larger  → max(278, 164) = 278
        average → (278 + 164) / 2 = 221
    """
    vols = {
        1: mk({'EBT': 250, 'SBL': 14, 'NBR': 14}),   # EB outflow = 250+14+14 = 278
        2: mk({'EBL': 30, 'EBT': 120, 'EBR': 14}),   # EB approach = 30+120+14 = 164
    }
    links = [{'fromNum': 1, 'toNum': 2, 'direction': 'EB/WB'}]
    coords = {1: {'lat': 0, 'lng': 0}, 2: {'lat': 0, 'lng': 1}}

    res_larger = resolve_link_volumes(vols, links, method='larger', coords=coords)
    res_avg    = resolve_link_volumes(vols, links, method='average', coords=coords)

    assert res_larger[(1, 2, 'EB')] == 278.0, f"larger EB: {res_larger[(1,2,'EB')]}"
    assert res_avg[(1, 2, 'EB')]    == 221.0, f"average EB: {res_avg[(1,2,'EB')]}"
    print(f"  test_link_resolution_larger_vs_average: PASS")
    print(f"    larger:  EB 1→2 = {res_larger[(1,2,'EB')]:.0f}  (max of 278, 164)")
    print(f"    average: EB 1→2 = {res_avg[(1,2,'EB')]:.0f}  (mean of 278, 164)")


# ─── Test 3 — 3-leg T intersection (missing leg → 3x3 effective) ────────────
def test_3leg_t_intersection():
    """T intersection: no west leg at all. The W-leg row (EB approach) and
    col (WB exit) must be masked. Furness should still converge using only
    the 3 present legs."""
    # T intersection with NO west leg. That means:
    #   - No EB approach (EBL/EBT/EBR must be 0)
    #   - No WB through (WBT goes west — impossible)
    #   - No NBL (left turn from north-bound exits west — impossible)
    #   - No SBR (right turn from south-bound exits west — impossible)
    vols = mk({
        # N leg present: SB approach
        'SBL': 20,                  # turns east (E leg) — OK
        'SBR': 0,                   # would turn west — IMPOSSIBLE
        'SBT': 50,                  # through south — OK
        # E leg present: WB approach
        'WBL': 25,                  # turns south — OK
        'WBT': 0,                   # through west — IMPOSSIBLE
        'WBR': 15,                  # turns north — OK
        # S leg present: NB approach
        'NBL': 0,                   # would turn west — IMPOSSIBLE
        'NBT': 80,                  # through north — OK
        'NBR': 15,                  # turns east — OK
        # W leg absent: no EB approach
        'EBL': 0, 'EBT': 0, 'EBR': 0,
    })
    # No links — all stub legs
    row_targets, col_targets, present = intersection_targets(
        99, {99: vols}, links_by_int={}, resolved_links={}
    )
    # Index 2 = W leg = EB approach. With no movements and no link, present=False
    assert present[0] is True, "S leg should be present"
    assert present[1] is True, "N leg should be present"
    assert present[2] is False, "W leg should be ABSENT (no link, no movements)"
    assert present[3] is True, "E leg should be present"

    M = _build_matrix(vols)
    M_out, conv, iters = furness_intersection(M, row_targets, col_targets, present,
                                              tol=0.01, max_iter=50)
    assert conv, "3-leg T should converge"
    # The W-leg row stays all zeros
    for c in range(4):
        assert M_out[2][c] == 0.0, f"W-leg row cell ({c}) = {M_out[2][c]}, expected 0"
    # And the W-leg col stays all zeros (nothing exits west)
    for r in range(4):
        assert M_out[r][2] == 0.0, f"W-leg col cell ({r}) = {M_out[r][2]}, expected 0"
    print(f"  test_3leg_t_intersection: PASS (W leg masked, converged in {iters} iter)")


# ─── Test 4 — floor activation (balanced < raw → clamped) ───────────────────
def test_floor_activation():
    """Construct a case where Furness would naturally produce a value below
    raw, then confirm the floor clamps it AND a QC flag is raised.
    Force this by giving Int 1 a HIGH EBT raw but a LOW resolved EB outflow
    target — Furness would scale EBT down, but floor must hold it at raw."""
    vols = {
        1: mk({'EBL': 10, 'EBT': 500, 'EBR': 10, 'WBL': 10, 'WBT': 10, 'WBR': 10,
               'NBL': 10, 'NBT': 10, 'NBR': 10, 'SBL': 10, 'SBT': 10, 'SBR': 10}),
        2: mk({'EBL': 10, 'EBT': 200, 'EBR': 10}),  # EB approach=220 << Int1 EB outflow 520
    }
    links = [{'fromNum': 1, 'toNum': 2, 'direction': 'EB/WB'}]
    coords = {1: {'lat': 0, 'lng': 0}, 2: {'lat': 0, 'lng': 1}}

    # With 'average', Int 1 EB outflow target = (520 + 220) / 2 = 370. Furness
    # will scale EBT down from 500 → ~355 (since EBT is 96% of EB outflow).
    # 355 < 500 raw → floor clamps EBT to 500, QC flag fires.
    result = balance_nchrp(vols, links, method='average', coords=coords,
                           apply_floor=True, round_to_5=False)

    int1 = result['balanced'][1]
    assert int1['EBT'] >= 500, f"EBT should be ≥ raw 500 after floor; got {int1['EBT']}"
    floor_flags = [f for f in result['qc_flags']
                   if f['check'] == 'NCHRP-FLOOR' and f['int'] == 1]
    assert len(floor_flags) >= 1, f"expected NCHRP-FLOOR flag for Int 1; got {result['qc_flags']}"
    print(f"  test_floor_activation: PASS")
    print(f"    Int 1 EBT raw=500, balanced (post-floor)={int1['EBT']:.1f}")
    print(f"    NCHRP-FLOOR flag fired ({len(floor_flags)} movement(s))")


# ─── Test 5 — end-to-end 3-intersection EB corridor with disagreement ───────
def test_end_to_end_3int_corridor():
    """Three intersections, EB/WB links 1↔2 and 2↔3. The middle intersection's
    counts disagree with both neighbors. New balancer should:
      - Resolve each link's EB and WB volumes consistently
      - Per-intersection Fratar match resolved targets
      - Floor at raw everywhere
      - Round up to next 5
      - NEVER cascade-inflate WB the way the old algo did
    """
    vols = {
        1: mk({'EBL': 80, 'EBT': 1000, 'EBR': 50, 'WBL': 50, 'WBT': 900, 'WBR': 40,
               'SBL': 25, 'NBR': 25}),
        2: mk({'EBL': 60, 'EBT': 1050, 'EBR': 40, 'WBL': 40, 'WBT': 920, 'WBR': 50,
               'SBL': 30, 'NBR': 20}),
        3: mk({'EBL': 100, 'EBT': 600, 'EBR': 70, 'WBL': 70, 'WBT': 880, 'WBR': 60,
               'SBL': 40, 'NBR': 35}),
    }
    links = [
        {'fromNum': 1, 'toNum': 2, 'direction': 'EB/WB'},
        {'fromNum': 2, 'toNum': 3, 'direction': 'EB/WB'},
    ]
    coords = {1: {'lat': 0, 'lng': 0}, 2: {'lat': 0, 'lng': 1}, 3: {'lat': 0, 'lng': 2}}

    result = balance_nchrp(vols, links, method='larger', coords=coords)
    bal = result['balanced']

    # Every nonzero movement must be ≥ raw (floor)
    for int_num in (1, 2, 3):
        for mv, raw_val in vols[int_num].items():
            if raw_val > 0:
                assert bal[int_num][mv] >= raw_val, \
                    f"Int {int_num} {mv}: balanced {bal[int_num][mv]} < raw {raw_val} (FLOOR VIOLATED)"

    # Every nonzero movement must be a multiple of 5 (rounded up)
    for int_num in (1, 2, 3):
        for mv, val in bal[int_num].items():
            if val > 0:
                assert val % 5 == 0, f"Int {int_num} {mv}={val} is not a multiple of 5"

    # No cascade — Int 3 WBT should NOT have exploded. Old buggy algo pushed it
    # to ~1600 on similar input. NCHRP keeps it close to raw 880.
    assert bal[3]['WBT'] < 1100, \
        f"Int 3 WBT = {bal[3]['WBT']} — looks like cascade inflation (should be ~880-1000)"

    # Resolved EB link volume between 1 and 2:
    # Int 1 EB outflow = 1000 + 25 + 25 = 1050
    # Int 2 EB approach = 60 + 1050 + 40 = 1150
    # method='larger' → 1150
    assert result['resolved_links'][(1, 2, 'EB')] == 1150.0
    print(f"  test_end_to_end_3int_corridor: PASS")
    print(f"    Int 1 EBT: raw 1000 → balanced {bal[1]['EBT']}")
    print(f"    Int 3 WBT: raw  880 → balanced {bal[3]['WBT']} (was ~1600 under old algo)")
    print(f"    resolved EB link 1→2: {result['resolved_links'][(1,2,'EB')]:.0f}  (max of 1050, 1150)")


if __name__ == '__main__':
    tests = [
        test_furness_4x4_known_answer,
        test_link_resolution_larger_vs_average,
        test_3leg_t_intersection,
        test_floor_activation,
        test_end_to_end_3int_corridor,
    ]
    passed = 0
    failed = 0
    for t in tests:
        print(f"Running {t.__name__}...")
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
