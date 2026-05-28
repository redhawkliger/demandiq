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
    fractional_volume_flags,
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
    proportions preserved). Balanced targets → IPF converges in 1 step.
    NB: furness_intersection now returns 4-tuple (matrix, conv, iters, residual)."""
    M = [[10.0]*4 for _ in range(4)]
    row_t = [100, 100, 100, 100]
    col_t = [100, 100, 100, 100]
    present = [True, True, True, True]
    M_out, conv, iters, residual = furness_intersection(M, row_t, col_t, present, tol=0.01, max_iter=50)
    assert conv, f"didn't converge in {iters} iters"
    for r in range(4):
        for c in range(4):
            assert abs(M_out[r][c] - 25.0) < 0.05, f"cell ({r},{c}) = {M_out[r][c]}, expected 25"
    assert residual < 0.05, f"residual should be ~0 on balanced targets; got {residual}"
    print(f"  test_furness_4x4_known_answer: PASS (converged in {iters} iter, residual={residual:.4f})")


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
    M_out, conv, iters, residual = furness_intersection(M, row_targets, col_targets, present,
                                                        tol=0.01, max_iter=50)
    assert conv, "3-leg T should converge"
    # The W-leg row stays all zeros
    for c in range(4):
        assert M_out[2][c] == 0.0, f"W-leg row cell ({c}) = {M_out[2][c]}, expected 0"
    # And the W-leg col stays all zeros (nothing exits west)
    for r in range(4):
        assert M_out[r][2] == 0.0, f"W-leg col cell ({r}) = {M_out[r][2]}, expected 0"
    print(f"  test_3leg_t_intersection: PASS (W leg masked, converged in {iters} iter)")


# ─── Test 4a — under 'larger', every balanced movement stays >= raw ─────────
def test_larger_conserves_links_movements_may_drop():
    """Under 'larger', the guarantee that actually holds is LINK CONSERVATION,
    not a per-movement floor.

    The original spec claim ("larger ⇒ no movement below raw") is FALSE — it
    confuses aggregate monotonicity with per-cell monotonicity. Resolved link
    targets = max(count_up, count_down) only bound the directional TOTALS, and
    even those can drop: per-intersection biproportional fitting (IPF) is a 2-D
    proportional fit, and at boundary/end nodes the row-sum vs col-sum target
    margins are INCONSISTENT. Concretely, at Int 1 (west end):

        ROW targets (approaches): EB 1130, WB 990, NB 25, SB 25  → 2170
        COL targets (exits):      EB 1150, WB 900, NB 120, SB 100 → 2270

    The EB-exit column is raised to the resolved link (1→2,EB)=1150, but the
    EB-approach row has no upstream link so it stays at raw 1130 — a +100
    inconsistency the fit can't satisfy. It compromises, inflating EBT and
    squeezing EBL/EBR/WBT below raw. This is correct NCHRP behavior; the drops
    are surfaced to the engineer in the S7 review-drops UI for override. We do
    NOT clamp them with a floor — NCHRP-FLOOR was removed in Stage 4b because a
    floor reintroduces conservation violations.

    Asserted (production path, round_to_5=True):
      - no NCHRP-FLOOR flags (floor stays gone)
      - every Full-mode link delta == 0 (post-round reconciliation, Stage 4c.3)
    Surfaced, NOT asserted: count + sample of movements that ended below raw.

    (NOTE: with round_to_5=False the reconciliation pass doesn't run, so
    conservation is NOT enforced — that's why this asserts the real
    production path rather than the raw pre-round IPF output.)"""
    coords = {n: {'lat': 0.0, 'lng': float(n)} for n in range(1, 10)}
    coords[6] = {'lat': 0.005, 'lng': 5.0}    # 6 is north of 5
    coords[5] = {'lat': 0.0, 'lng': 5.0}      # 5 stays at lng=5

    raw = {
        1: mk({'EBL':80,'EBT':1000,'EBR':50,'WBL':50,'WBT':900,'WBR':40,'NBR':25,'SBL':25}),
        2: mk({'EBL':60,'EBT':1050,'EBR':40,'WBL':40,'WBT':920,'WBR':50,'NBR':20,'SBL':30}),
        3: mk({'EBL':100,'EBT':1020,'EBR':70,'WBL':70,'WBT':880,'WBR':60,'NBR':35,'SBL':40}),
        4: mk({'EBL':80,'EBT':980,'EBR':60,'WBL':60,'WBT':850,'WBR':50,'NBR':30,'SBL':35}),
        5: mk({'EBL':90,'EBT':950,'EBR':80,'WBL':80,'WBT':820,'WBR':70,
               'NBL':30,'NBT':200,'NBR':35,'SBL':40,'SBT':180,'SBR':25}),
        6: mk({'NBL':25,'NBT':220,'NBR':30,'SBL':35,'SBT':200,'SBR':28}),
        7: mk({'EBL':70,'EBT':900,'EBR':50,'WBL':50,'WBT':800,'WBR':60,'NBR':25,'SBL':30}),
        8: mk({'EBL':60,'EBT':880,'EBR':50,'WBL':50,'WBT':770,'WBR':50,'NBR':25,'SBL':25}),
        9: mk({'EBL':50,'EBT':850,'EBR':40,'WBL':40,'WBT':750,'WBR':40,'NBR':20,'SBL':20}),
    }
    links = ([{'fromNum': a, 'toNum': b, 'direction': 'EB/WB'}
              for a, b in [(1,2),(2,3),(3,4),(4,5),(5,7),(7,8),(8,9)]]
             + [{'fromNum': 5, 'toNum': 6, 'direction': 'NB/SB'}])

    # Production path — round_to_5=True runs the Stage 4c.3 reconciliation.
    result = balance_nchrp(raw, links, method='larger', coords=coords)
    bal = result['balanced']

    # Floor must stay gone.
    floor_flags = [f for f in result['qc_flags'] if f['check'] == 'NCHRP-FLOOR']
    assert len(floor_flags) == 0, \
        f"NCHRP-FLOOR flags should no longer exist; found {len(floor_flags)}"

    # THE invariant: every Full-mode link conserves exactly (delta == 0).
    full = [e for e in result['link_conservation'] if e.get('mode') == 'Full']
    assert len(full) > 0, "expected Full-mode links to check"
    nonzero = [e for e in full if abs(e['delta']) > 1e-9]
    assert not nonzero, (
        "Larger must conserve every Full link (delta == 0); nonzero: "
        + ", ".join(f"{e['fromNum']}→{e['toNum']} {e['direction']} Δ={e['delta']:.2f}"
                    for e in nonzero)
    )

    # Informational only: surface per-movement drops (engineer reviews these).
    drops = []
    for int_num, raw_vols in raw.items():
        for mv, raw_val in raw_vols.items():
            if raw_val > 0 and bal[int_num].get(mv, 0) < raw_val - 1e-6:
                drops.append((int_num, mv, raw_val, bal[int_num].get(mv, 0)))

    print(f"  test_larger_conserves_links_movements_may_drop: PASS "
          f"({len(full)} Full links conserve exactly; "
          f"{len(drops)} movements below raw — expected, surfaced in S7 review-drops)")
    for int_num, mv, rv, bv in drops[:3]:
        print(f"    Int {int_num} {mv}: raw {rv} → balanced {bv:.0f}")
    if len(drops) > 3:
        print(f"    ... + {len(drops) - 3} more (engineer reviews / overrides these)")


# ─── Test 4b — under 'average', some movements CAN drop below raw ───────────
def test_average_can_go_below_raw():
    """Under 'average' resolution, link targets are the mean of upstream and
    downstream counts. If one side genuinely undercounted, Furness will scale
    that side down — and that's the correct NCHRP behavior. Assert at least
    one movement drops below raw on the same Bodger-like network."""
    coords = {n: {'lat': 0.0, 'lng': float(n)} for n in range(1, 10)}
    coords[6] = {'lat': 0.005, 'lng': 5.0}
    coords[5] = {'lat': 0.0, 'lng': 5.0}

    raw = {
        1: mk({'EBL':80,'EBT':1000,'EBR':50,'WBL':50,'WBT':900,'WBR':40,'NBR':25,'SBL':25}),
        2: mk({'EBL':60,'EBT':1050,'EBR':40,'WBL':40,'WBT':920,'WBR':50,'NBR':20,'SBL':30}),
        3: mk({'EBL':100,'EBT':1020,'EBR':70,'WBL':70,'WBT':880,'WBR':60,'NBR':35,'SBL':40}),
        4: mk({'EBL':80,'EBT':980,'EBR':60,'WBL':60,'WBT':850,'WBR':50,'NBR':30,'SBL':35}),
        5: mk({'EBL':90,'EBT':950,'EBR':80,'WBL':80,'WBT':820,'WBR':70,
               'NBL':30,'NBT':200,'NBR':35,'SBL':40,'SBT':180,'SBR':25}),
        6: mk({'NBL':25,'NBT':220,'NBR':30,'SBL':35,'SBT':200,'SBR':28}),
        7: mk({'EBL':70,'EBT':900,'EBR':50,'WBL':50,'WBT':800,'WBR':60,'NBR':25,'SBL':30}),
        8: mk({'EBL':60,'EBT':880,'EBR':50,'WBL':50,'WBT':770,'WBR':50,'NBR':25,'SBL':25}),
        9: mk({'EBL':50,'EBT':850,'EBR':40,'WBL':40,'WBT':750,'WBR':40,'NBR':20,'SBL':20}),
    }
    links = ([{'fromNum': a, 'toNum': b, 'direction': 'EB/WB'}
              for a, b in [(1,2),(2,3),(3,4),(4,5),(5,7),(7,8),(8,9)]]
             + [{'fromNum': 5, 'toNum': 6, 'direction': 'NB/SB'}])

    result = balance_nchrp(raw, links, method='average', coords=coords,
                           round_to_5=False)
    bal = result['balanced']

    drops = []
    for int_num, raw_vols in raw.items():
        for mv, raw_val in raw_vols.items():
            if raw_val > 0:
                bv = bal[int_num].get(mv, 0)
                if bv < raw_val - 0.5:    # only count meaningful drops
                    drops.append((int_num, mv, raw_val, bv))

    assert len(drops) > 0, \
        "Average mode should produce at least some below-raw movements on this corridor"
    # And no NCHRP-FLOOR flags (the floor is gone)
    floor_flags = [f for f in result['qc_flags'] if f['check'] == 'NCHRP-FLOOR']
    assert len(floor_flags) == 0
    print(f"  test_average_can_go_below_raw: PASS ({len(drops)} movement(s) below raw — expected NCHRP behavior)")
    for int_num, mv, raw_val, bv in drops[:5]:
        print(f"    Int {int_num} {mv}: raw {raw_val} → balanced {bv:.2f}")
    if len(drops) > 5:
        print(f"    ... + {len(drops) - 5} more")


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

    # Floor is gone — we no longer assert balanced >= raw on every movement.
    # Conservation normalization can pull some stub-leg movements slightly
    # below raw; that's now visible to the engineer rather than masked.
    # What we DO still assert: no cascade explosion.

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


# ─── Test 7 — imbalanced 4×4 IPF (the Stage 4c change) ──────────────────────
def test_imbalanced_4x4_ipf():
    """IPF must handle row_total != col_total without pre-normalization.

    Row targets sum to 1000; col targets sum to 1500. Pre-Stage-4c code
    would have averaged them to 1250 then pretended targets matched — that
    silently shifted both target sets and propagated bias.

    True IPF (Stage 4c) iterates row-scale + col-scale until cells stop
    moving (matrix stability), accepts that residuals to targets persist,
    and reports the residual honestly.
    """
    # Start: all cells = 50. Initial row sums = 200, col sums = 200.
    M = [[50.0] * 4 for _ in range(4)]
    row_t = [200, 200, 300, 300]   # total = 1000
    col_t = [400, 400, 350, 350]   # total = 1500
    present = [True, True, True, True]

    M_out, conv, iters, residual = furness_intersection(
        M, row_t, col_t, present, tol=0.01, max_iter=500
    )

    # Should converge by MATRIX-STABILITY criterion despite imbalanced targets
    assert conv, f"IPF should reach a stable matrix even with imbalanced targets; got iters={iters}"

    # The residual to targets should be > 0 — that's the irreducible imbalance
    assert residual > 0.5, \
        f"final_residual should expose imbalance (got {residual:.2f}); IPF can't satisfy both target sets simultaneously"

    # No cell should be NaN / negative — matrix stays positive
    for r in range(4):
        for c in range(4):
            assert M_out[r][c] >= 0, f"cell ({r},{c}) went negative: {M_out[r][c]}"

    # Row sums should land near (row_total / col_total * row_target) → because
    # col scaling is the last operation, col sums match col targets exactly,
    # and row sums end at scaled-down versions of row targets.
    # We don't assert exact numbers here, just that the matrix is well-formed.
    row_sums_out = [sum(M_out[r]) for r in range(4)]
    col_sums_out = [sum(M_out[r][c] for r in range(4)) for c in range(4)]

    print(f"  test_imbalanced_4x4_ipf: PASS")
    print(f"    converged in {iters} iter, final_residual = {residual:.2f} veh")
    print(f"    target row totals: 1000  → output row sum: {sum(row_sums_out):.0f}")
    print(f"    target col totals: 1500  → output col sum: {sum(col_sums_out):.0f}")
    print(f"    (last-pass col scaling sets col sums to col targets; row sums absorb the imbalance)")


# ─── Test 8 — link conservation holds after balance (Stage 4c.1) ───────────
def test_link_conservation_holds():
    """The engineer-facing correctness criterion: on every link, upstream
    outflow == downstream inflow (within rounding tolerance). This must hold
    on the BALANCED matrix after IPF + Larger/Average resolution + round-up-5.
    If this test fails, the algorithm has a real conservation bug."""
    coords = {n: {'lat': 0.0, 'lng': float(n)} for n in range(1, 10)}
    coords[6] = {'lat': 0.005, 'lng': 5.0}
    coords[5] = {'lat': 0.0, 'lng': 5.0}

    raw = {
        1: mk({'EBL':80,'EBT':1000,'EBR':50,'WBL':50,'WBT':900,'WBR':40,'NBR':25,'SBL':25}),
        2: mk({'EBL':60,'EBT':1050,'EBR':40,'WBL':40,'WBT':920,'WBR':50,'NBR':20,'SBL':30}),
        3: mk({'EBL':100,'EBT':1020,'EBR':70,'WBL':70,'WBT':880,'WBR':60,'NBR':35,'SBL':40}),
        4: mk({'EBL':80,'EBT':980,'EBR':60,'WBL':60,'WBT':850,'WBR':50,'NBR':30,'SBL':35}),
        5: mk({'EBL':90,'EBT':950,'EBR':80,'WBL':80,'WBT':820,'WBR':70,
               'NBL':30,'NBT':200,'NBR':35,'SBL':40,'SBT':180,'SBR':25}),
        6: mk({'NBL':25,'NBT':220,'NBR':30,'SBL':35,'SBT':200,'SBR':28}),
        7: mk({'EBL':70,'EBT':900,'EBR':50,'WBL':50,'WBT':800,'WBR':60,'NBR':25,'SBL':30}),
        8: mk({'EBL':60,'EBT':880,'EBR':50,'WBL':50,'WBT':770,'WBR':50,'NBR':25,'SBL':25}),
        9: mk({'EBL':50,'EBT':850,'EBR':40,'WBL':40,'WBT':750,'WBR':40,'NBR':20,'SBL':20}),
    }
    links = ([{'fromNum': a, 'toNum': b, 'direction': 'EB/WB'}
              for a, b in [(1,2),(2,3),(3,4),(4,5),(5,7),(7,8),(8,9)]]
             + [{'fromNum': 5, 'toNum': 6, 'direction': 'NB/SB'}])

    # Stage 4c.3: post-round link reconciliation enforces |delta| == 0 on Full
    # links exactly (the canonical = round5(avg pre-round) is set as both
    # leg sums via _adjust_leg_to_target). Land Use and None links are
    # excluded from the assertion — Land Use intentionally allows a
    # documented landuse_delta, None passes through without reconciliation.
    for method in ('larger', 'average'):
        result = balance_nchrp(raw, links, method=method, coords=coords)
        lc = result['link_conservation']
        assert isinstance(lc, list)
        assert len(lc) > 0
        full_links = [e for e in lc if e.get('mode') == 'Full']
        landuse_links = [e for e in lc if e.get('mode') == 'Land Use']
        none_links = [e for e in lc if e.get('mode') == 'None']
        violations = [e for e in full_links if abs(e['delta']) > 0.5]
        if violations:
            for v in violations[:5]:
                print(f"    VIOLATION {method}: {v['fromNum']}→{v['toNum']} {v['direction']}: "
                      f"out={v['upstream_outflow']:.1f} in={v['downstream_inflow']:.1f} "
                      f"delta={v['delta']:+.1f}")
        assert len(violations) == 0, \
            f"{method}: {len(violations)} Full link(s) failed exact conservation"
        print(f"    {method}: {len(full_links)} Full links — all delta==0 ✓ | "
              f"{len(landuse_links)} Land Use | {len(none_links)} None")
    print(f"  test_link_conservation_holds: PASS (post-round reconciliation enforces conservation)")


# ─── Test 9 — Stage 5 (amendment v2): movements_review schema, ordering, ──
#               all-movements coverage (no drop-only filter)
def test_movements_review_present():
    """balance_nchrp returns movements_review with ONE entry per
    (int_num, movement) where raw>0 — INCLUDING entries where balanced>=raw.
    Sorted by int_num asc then standard L/T/R movement order."""
    coords = {n: {'lat': 0.0, 'lng': float(n)} for n in range(1, 10)}
    coords[6] = {'lat': 0.005, 'lng': 5.0}; coords[5] = {'lat': 0.0, 'lng': 5.0}
    raw = {
        1: mk({'EBL':80,'EBT':1000,'EBR':50,'WBL':50,'WBT':900,'WBR':40,'NBR':25,'SBL':25}),
        2: mk({'EBL':60,'EBT':1050,'EBR':40,'WBL':40,'WBT':920,'WBR':50,'NBR':20,'SBL':30}),
        3: mk({'EBL':100,'EBT':1020,'EBR':70,'WBL':70,'WBT':880,'WBR':60,'NBR':35,'SBL':40}),
        4: mk({'EBL':80,'EBT':980,'EBR':60,'WBL':60,'WBT':850,'WBR':50,'NBR':30,'SBL':35}),
        5: mk({'EBL':90,'EBT':950,'EBR':80,'WBL':80,'WBT':820,'WBR':70,
               'NBL':30,'NBT':200,'NBR':35,'SBL':40,'SBT':180,'SBR':25}),
        6: mk({'NBL':25,'NBT':220,'NBR':30,'SBL':35,'SBT':200,'SBR':28}),
        7: mk({'EBL':70,'EBT':900,'EBR':50,'WBL':50,'WBT':800,'WBR':60,'NBR':25,'SBL':30}),
        8: mk({'EBL':60,'EBT':880,'EBR':50,'WBL':50,'WBT':770,'WBR':50,'NBR':25,'SBL':25}),
        9: mk({'EBL':50,'EBT':850,'EBR':40,'WBL':40,'WBT':750,'WBR':40,'NBR':20,'SBL':20}),
    }
    links = ([{'fromNum': a, 'toNum': b, 'direction': 'EB/WB'} for a, b in [(1,2),(2,3),(3,4),(4,5),(5,7),(7,8),(8,9)]]
             + [{'fromNum': 5, 'toNum': 6, 'direction': 'NB/SB'}])

    result = balance_nchrp(raw, links, method='larger', coords=coords)
    review = result['movements_review']
    assert isinstance(review, list), f"movements_review should be list; got {type(review)}"
    assert len(review) > 0, "Bodger has many movements; review should be non-empty"

    # Schema unchanged
    for e in review:
        assert set(e.keys()) == {'int_num', 'movement', 'raw', 'balanced', 'delta'}, \
            f"bad schema: {e.keys()}"
        assert e['delta'] == e['balanced'] - e['raw']
        assert e['raw'] > 0, "raw==0 entries should be excluded"

    # Now expect ONE entry per (int_num, movement) with raw>0 — drops AND non-drops.
    standard = ('EBL','EBT','EBR','WBL','WBT','WBR','NBL','NBT','NBR','SBL','SBT','SBR')
    expected_count = 0
    for n, raw_v in raw.items():
        for mv in standard:
            if raw_v.get(mv, 0) > 0:
                expected_count += 1
    assert len(review) == expected_count, \
        f"review has {len(review)} entries; expected {expected_count} (every raw>0 movement)"

    # At least one non-drop must be present now (proves filter was removed)
    non_drops = [e for e in review if e['delta'] >= 0]
    assert len(non_drops) > 0, "review must include movements where balanced>=raw"

    # Sort: int_num asc, then standard movement order
    mv_rank = {mv: i for i, mv in enumerate(standard)}
    expected_order = sorted(review, key=lambda x: (x['int_num'], mv_rank[x['movement']]))
    assert review == expected_order, \
        "list should be sorted by int_num asc, then standard movement order"

    print(f"  test_movements_review_present: PASS ({len(review)} movements; "
          f"{sum(1 for e in review if e['delta'] < 0)} drops)")


# ─── Test 10 — Stage 5 v2: all_movements coverage explicit ─────────────────
def test_all_movements_present():
    """Every (int × movement-with-raw>0) appears in movements_review — no
    threshold gating. Specifically: every NON-drop (delta>=0) is also present."""
    coords = {1: {'lat': 0.0, 'lng': 0.0}, 2: {'lat': 0.0, 'lng': 1.0}}
    raw = {
        1: mk({'EBT': 1000, 'WBT': 800, 'EBL': 50, 'WBR': 30}),
        2: mk({'EBT': 1000, 'WBT': 800, 'EBR': 40, 'WBL': 60}),
    }
    links = [{'fromNum': 1, 'toNum': 2, 'direction': 'EB/WB'}]
    result = balance_nchrp(raw, links, method='larger', coords=coords)
    review = result['movements_review']

    # Build the set of (int, mv) entries actually present in review
    present = {(e['int_num'], e['movement']) for e in review}

    # Every raw-positive movement should be there
    for n, raw_v in raw.items():
        for mv, val in raw_v.items():
            if val > 0 and mv in ('EBL','EBT','EBR','WBL','WBT','WBR','NBL','NBT','NBR','SBL','SBT','SBR'):
                assert (n, mv) in present, \
                    f"({n},{mv}) raw={val} missing from review (drop-only filter still active?)"

    print(f"  test_all_movements_present: PASS ({len(review)} entries cover every raw>0 movement)")


# ─── Test 11 — Stage 10.1: fractional-volume source-data QC flag ───────────
def test_fractional_volume_flag():
    """A raw value with a fractional part fires FRACTIONAL-VOLUME for exactly
    that movement; an all-integer raw set fires zero fractional flags; tiny
    float noise within epsilon is NOT flagged."""
    raw = {
        1: {'EBT': 1000, 'EBL': 80, 'WBT': 102.5},   # WBT fractional
        2: {'EBT': 950, 'NBL': 30},                  # all integer
    }
    flags = fractional_volume_flags(raw, period='AM')
    assert len(flags) == 1, f"expected exactly 1 flag, got {len(flags)}: {flags}"
    f = flags[0]
    assert f['check'] == 'FRACTIONAL-VOLUME'
    assert f['int'] == 1 and f['period'] == 'AM'
    assert 'WBT' in f['message'] and '102.5' in f['message'], f['message']

    # All-integer raw → zero fractional flags
    clean = {1: {'EBT': 1000, 'EBL': 80}, 2: {'WBT': 950.0}}  # 950.0 is whole
    assert fractional_volume_flags(clean) == [], fractional_volume_flags(clean)

    # Float-representation noise within epsilon → not flagged
    noisy = {1: {'EBT': 100.0000001}}
    assert fractional_volume_flags(noisy) == [], "epsilon should absorb float noise"

    # Genuine fraction just above epsilon → flagged
    assert len(fractional_volume_flags({1: {'EBT': 100.01}})) == 1

    print(f"  test_fractional_volume_flag: PASS (1 flag on WBT 102.5, 0 on clean)")


if __name__ == '__main__':
    tests = [
        test_furness_4x4_known_answer,
        test_link_resolution_larger_vs_average,
        test_3leg_t_intersection,
        test_larger_conserves_links_movements_may_drop,
        test_average_can_go_below_raw,
        test_end_to_end_3int_corridor,
        test_imbalanced_4x4_ipf,
        test_link_conservation_holds,
        test_movements_review_present,
        test_all_movements_present,
        test_fractional_volume_flag,
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
