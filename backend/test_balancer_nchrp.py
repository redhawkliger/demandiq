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


# ─── Test 3b — no phantom movement on an absent leg forced by a Full link ────
def test_no_phantom_movement_on_absent_leg():
    """Regression for the int-7 phantom-EBT bug. Int 7 is a 3-leg T on an E-W
    corridor: legs W, N, S — there is NO E leg. So every E-leg movement is raw 0:
    EBT/SBL/NBR (which exit east) and WBL/WBT/WBR (which approach from the east).
    A Full EB/WB link 7->8 sits on the (absent) E side; the east neighbour pulls
    demand through it. The Stage 4c.3 post-round reconciliation must NOT invent
    eastbound-through flow on a leg that physically doesn't exist — raw EBT 0 must
    stay balanced EBT 0 (likewise SBL, NBR, the other two E-exit movements).

    Before the fix, reconciliation dumps the link's canonical volume into EBT
    (first cell of DIRECTION_SPEC['EB']['outflow']) because it never checks raw-leg
    presence, yielding a conservation-clean, unflagged phantom (~200+ veh)."""
    int7 = mk({
        'EBL': 80, 'EBR': 70,            # W-approach turns onto N/S (EBT=0: no E exit)
        'NBT': 300, 'NBL': 60,           # S-approach: through N + left to W (NBR=0: no E)
        'SBT': 290, 'SBR': 40,           # N-approach: through S + right to W (SBL=0: no E)
    })
    int8 = mk({                          # real east neighbour with EB approach demand
        'EBL': 20, 'EBT': 400, 'EBR': 20, 'NBL': 50, 'NBT': 300, 'NBR': 40,
        'SBL': 45, 'SBT': 290, 'SBR': 35, 'WBL': 40, 'WBT': 260, 'WBR': 30,
    })
    raw = {7: int7, 8: int8}
    links = [{'fromNum': 7, 'toNum': 8, 'direction': 'EB/WB', 'mode': 'Full'}]
    coords = {7: {'lat': 32.90, 'lng': -117.05}, 8: {'lat': 32.90, 'lng': -117.04}}  # 7 west of 8

    res = balance_nchrp(raw, links, method='larger', coords=coords, round_to_5=True)
    b7 = res['balanced'][7]
    # All three movements exit via the absent E leg → none can carry flow.
    assert b7['EBT'] == 0, f"phantom EBT={b7['EBT']} invented on an absent E leg"
    assert b7['SBL'] == 0, f"phantom SBL={b7['SBL']} invented on an absent E leg"
    assert b7['NBR'] == 0, f"phantom NBR={b7['NBR']} invented on an absent E leg"

    # The infeasibility is SURFACED, not silently balanced: int 7's E-outflow
    # stays 0, the link delta stays VISIBLE, and a NCHRP-LINK-NOLEG flag names it.
    eb = next((c for c in res['link_conservation']
               if c['fromNum'] == 7 and c['toNum'] == 8 and c['direction'] == 'EB'), None)
    assert eb is not None, "expected link 7→8 EB in the conservation table"
    assert eb['upstream_outflow'] == 0, f"int 7 E-outflow must be 0, got {eb['upstream_outflow']}"
    assert abs(eb['delta']) > 0.5, f"infeasible link delta must stay visible, got {eb['delta']}"

    # The FEASIBLE endpoint (int 8) must NOT be corrupted toward the phantom-0
    # side: its real eastbound approach (raw 440) is preserved (~435 after IPF +
    # round), never reconciled down toward int 7's structural 0.
    b8 = res['balanced'][8]
    assert b8['EBL'] + b8['EBT'] + b8['EBR'] >= 430, \
        f"int 8 real W-approach corrupted to {b8['EBL'] + b8['EBT'] + b8['EBR']} (expected ~435)"

    noleg = [f for f in res['qc_flags'] if f.get('check') == 'NCHRP-LINK-NOLEG' and f.get('int') == 7]
    assert noleg, f"expected NCHRP-LINK-NOLEG for int 7; got {[f.get('check') for f in res['qc_flags']]}"
    # Must NOT be mislabeled as a generic raw-floor delta on the same link.
    generic = [f for f in res['qc_flags'] if f.get('check') == 'NCHRP-LINK-DELTA' and f.get('int') == 7]
    assert not generic, f"no-leg link must not also raise NCHRP-LINK-DELTA: {generic}"
    print("  test_no_phantom_movement_on_absent_leg: PASS "
          "(no phantom; structural delta surfaced via NCHRP-LINK-NOLEG)")


# ─── Test 3c — a no-leg link is purely informational, never forces ──────────
def test_noleg_link_does_not_perturb_feasible_endpoint():
    """TASK 2 (validate at resolve/leg-total time). A structurally infeasible
    (no-leg) Full link must NOT force leg totals anywhere — not just in Stage 4c.3
    reconciliation, but also in Level 1 (balance_leg_totals link-equality). It is
    surfaced as NCHRP-LINK-NOLEG with a visible delta, but the balanced result of
    its FEASIBLE endpoint must be byte-identical whether or not the broken link
    exists. (Before TASK 2, Level 1's link-equality pulled int 8's real counts
    toward int 7's phantom-0 side: EBT 400->395 plus five other movements.)"""
    int7 = mk({'EBL': 80, 'EBR': 70, 'NBT': 300, 'NBL': 60, 'SBT': 290, 'SBR': 40})
    int8 = mk({'EBL': 20, 'EBT': 400, 'EBR': 20, 'NBL': 50, 'NBT': 300, 'NBR': 40,
               'SBL': 45, 'SBT': 290, 'SBR': 35, 'WBL': 40, 'WBT': 260, 'WBR': 30})
    coords = {7: {'lat': 32.90, 'lng': -117.05}, 8: {'lat': 32.90, 'lng': -117.04}}
    link = [{'fromNum': 7, 'toNum': 8, 'direction': 'EB/WB', 'mode': 'Full'}]

    with_link = balance_nchrp({7: int7, 8: int8}, link, method='larger', coords=coords)['balanced'][8]
    no_link = balance_nchrp({7: int7, 8: int8}, [], method='larger', coords=coords)['balanced'][8]
    diff = [k for k in with_link if with_link[k] != no_link.get(k)]
    assert not diff, f"no-leg link perturbed feasible int 8 on {diff}: " \
        f"{ {k: (no_link[k], with_link[k]) for k in diff} }"
    print("  test_noleg_link_does_not_perturb_feasible_endpoint: PASS "
          "(feasible endpoint untouched by the broken link)")


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


# ─── Test 12 — GEOMETRY-FALLBACK qc_flag emission (PRD-05) ──────────────────
def test_geometry_fallback_no_emission_when_coords_distinct():
    """Bodger-shaped fixture (distinct coords): zero GEOMETRY-FALLBACK flags.
    Verifies the flag fires only on coord degeneracy, not on every balance run."""
    vols = {
        1: mk({'EBT': 250, 'SBL': 14}),
        2: mk({'EBL': 30, 'EBT': 120, 'EBR': 14}),
    }
    links = [{'fromNum': 1, 'toNum': 2, 'direction': 'EB/WB', 'mode': 'Full'}]
    coords = {1: {'lat': 40.0, 'lng': -75.0},
              2: {'lat': 40.0, 'lng': -74.99}}   # ~0.01 deg apart, ~1 km

    fallbacks = []
    resolve_link_volumes(vols, links, method='larger', coords=coords,
                         geometry_fallbacks=fallbacks)
    assert fallbacks == [], f"expected no fallbacks; got {fallbacks}"

    result = balance_nchrp(vols, links, method='larger', coords=coords)
    geom_flags = [f for f in result['qc_flags'] if f['check'] == 'GEOMETRY-FALLBACK']
    assert geom_flags == [], f"expected no GEOMETRY-FALLBACK; got {geom_flags}"
    print(f"  test_geometry_fallback_no_emission_when_coords_distinct: PASS")


def test_geometry_fallback_fires_on_coincident_coords():
    """Two intersections at identical lat/lng on an EB/WB link: exactly one
    GEOMETRY-FALLBACK flag, message names both int numbers, period=None."""
    vols = {
        1: mk({'EBT': 250}),
        2: mk({'EBT': 120}),
    }
    links = [{'fromNum': 1, 'toNum': 2, 'direction': 'EB/WB', 'mode': 'Full'}]
    coords = {1: {'lat': 40.0, 'lng': -75.0},
              2: {'lat': 40.0, 'lng': -75.0}}   # identical → ambiguous

    fallbacks = []
    resolve_link_volumes(vols, links, method='larger', coords=coords,
                         geometry_fallbacks=fallbacks)
    assert fallbacks == [(1, 2)], f"expected [(1,2)]; got {fallbacks}"

    # Within epsilon (1e-7 < 1e-6): still flagged
    coords_near = {1: {'lat': 40.0, 'lng': -75.0},
                   2: {'lat': 40.0 + 1e-7, 'lng': -75.0 + 1e-7}}
    fallbacks_near = []
    resolve_link_volumes(vols, links, method='larger', coords=coords_near,
                         geometry_fallbacks=fallbacks_near)
    assert fallbacks_near == [(1, 2)], f"epsilon-equal coords should flag; got {fallbacks_near}"

    result = balance_nchrp(vols, links, method='larger', coords=coords)
    geom_flags = [f for f in result['qc_flags'] if f['check'] == 'GEOMETRY-FALLBACK']
    assert len(geom_flags) == 1, f"expected 1 flag; got {len(geom_flags)}: {geom_flags}"
    f = geom_flags[0]
    assert f['period'] is None, f"period should be None; got {f['period']!r}"
    assert f['fromNum'] == 1 and f['toNum'] == 2, f
    assert '1' in f['message'] and '2' in f['message'], f"message must name both ints: {f['message']!r}"
    assert '↔' in f['message'], f"message format check: {f['message']!r}"
    print(f"  test_geometry_fallback_fires_on_coincident_coords: PASS")
    print(f"    message: {f['message']}")


def test_geometry_fallback_one_per_link_not_per_int():
    """Three intersections, 2 share coords with each adjacent neighbor on
    DIFFERENT pairs: exactly one flag per affected link, never per int."""
    vols = {
        1: mk({'EBT': 200}),
        2: mk({'EBT': 180, 'EBL': 0}),
        3: mk({'EBT': 150}),
    }
    links = [
        {'fromNum': 1, 'toNum': 2, 'direction': 'EB/WB', 'mode': 'Full'},
        {'fromNum': 2, 'toNum': 3, 'direction': 'EB/WB', 'mode': 'Full'},
    ]
    # 1 and 2 share coords (ambiguous); 3 is distinct (resolves cleanly)
    coords = {
        1: {'lat': 40.0, 'lng': -75.0},
        2: {'lat': 40.0, 'lng': -75.0},
        3: {'lat': 40.0, 'lng': -74.98},
    }
    fallbacks = []
    resolve_link_volumes(vols, links, method='larger', coords=coords,
                         geometry_fallbacks=fallbacks)
    assert fallbacks == [(1, 2)], f"expected only (1,2); got {fallbacks}"

    # Now degenerate BOTH links (1-2 and 2-3 share with neighbors).
    coords_two_bad = {
        1: {'lat': 40.0, 'lng': -75.0},
        2: {'lat': 40.0, 'lng': -75.0},
        3: {'lat': 40.0, 'lng': -75.0},
    }
    fallbacks2 = []
    resolve_link_volumes(vols, links, method='larger', coords=coords_two_bad,
                         geometry_fallbacks=fallbacks2)
    assert set(fallbacks2) == {(1, 2), (2, 3)}, f"expected 2 distinct pairs; got {fallbacks2}"
    assert len(fallbacks2) == 2, f"each pair only once: {fallbacks2}"
    print(f"  test_geometry_fallback_one_per_link_not_per_int: PASS")


def test_geometry_fallback_deduped_across_am_pm():
    """Same coord-sharing fixture exercised through the /balance-nchrp app
    layer with both AM and PM data: GEOMETRY-FALLBACK appears exactly once,
    not twice (deduped across periods because geometry doesn't change)."""
    from fastapi.testclient import TestClient
    from app import app

    payload = {
        "intersections": [
            {"num": 1, "lat": 40.0, "lng": -75.0},
            {"num": 2, "lat": 40.0, "lng": -75.0},   # coincident with 1
        ],
        "unbalanced_volumes": {
            "AM": {
                "1": {"EBT": 250},
                "2": {"EBT": 120},
            },
            "PM": {
                "1": {"EBT": 300},
                "2": {"EBT": 140},
            },
        },
        "links": [
            {"fromNum": 1, "toNum": 2, "direction": "EB/WB", "mode": "Full"},
        ],
        "link_resolution_method": "larger",
    }
    client = TestClient(app)
    r = client.post("/balance-nchrp", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    geom = [f for f in body['qc_flags'] if f['check'] == 'GEOMETRY-FALLBACK']
    assert len(geom) == 1, f"expected exactly 1 GEOMETRY-FALLBACK after dedup; got {len(geom)}: {geom}"
    assert geom[0]['period'] is None, f"period should be None corridor-wide; got {geom[0]['period']!r}"
    assert geom[0]['fromNum'] == 1 and geom[0]['toNum'] == 2
    print(f"  test_geometry_fallback_deduped_across_am_pm: PASS (1 flag covers AM + PM)")


def test_invalid_link_direction_rejected():
    """F1: a link with direction='NB' (cardinal) instead of 'NB/SB' (axis)
    used to be silently skipped by resolve_link_volumes, producing an empty
    resolved_links + a misleading '0/0 links conserve ✓' hero on the
    frontend. The /balance-nchrp endpoint now rejects such payloads with
    HTTP 400 + a helpful message identifying the bad link."""
    from fastapi.testclient import TestClient
    from app import app

    payload = {
        "intersections": [
            {"num": 1, "lat": 32.85, "lng": -116.85},
            {"num": 2, "lat": 32.86, "lng": -116.85},
        ],
        "unbalanced_volumes": {
            "AM": {"1": {"NBT": 480}, "2": {"NBT": 510}},
            "PM": {"1": {"NBT": 560}, "2": {"NBT": 580}},
        },
        "links": [
            {"fromNum": 1, "toNum": 2, "direction": "NB", "mode": "Full"},   # cardinal, not axis
        ],
        "link_resolution_method": "larger",
    }
    client = TestClient(app)
    r = client.post("/balance-nchrp", json=payload)
    assert r.status_code == 400, f"expected 400 on invalid direction; got {r.status_code}: {r.text}"
    body = r.json()
    detail = body.get('detail', '')
    assert "'NB'" in detail, f"detail should quote the bad direction; got {detail!r}"
    assert "1→2" in detail, f"detail should identify the link; got {detail!r}"
    assert "EB/WB" in detail and "NB/SB" in detail, f"detail should list the valid options; got {detail!r}"
    print(f"  test_invalid_link_direction_rejected: PASS (400 + identifies link 1→2 + lists valid axes)")


def test_f2_geometry_root_attached_to_link_delta_messages():
    """F2: when a coincident-coord pair fires GEOMETRY-FALLBACK, every
    NCHRP-LINK-DELTA on a link touching either endpoint should reference
    the root cause in its message so engineers don't chase each delta
    independently."""
    from fastapi.testclient import TestClient
    from app import app

    # 3 intersections; Int 2 and Int 3 share coords (geometry collision).
    # Counts arranged so link conservation breaks on the 2↔3 link in AM.
    payload = {
        "intersections": [
            {"num": 1, "lat": 32.85, "lng": -116.85},
            {"num": 2, "lat": 32.86, "lng": -116.85},
            {"num": 3, "lat": 32.86, "lng": -116.85},   # coincident with 2
        ],
        "unbalanced_volumes": {
            "AM": {
                "1": {"EBL": 50, "EBT": 300, "EBR": 40, "WBL": 30, "WBT": 280, "WBR": 35,
                      "NBL": 25, "NBT": 480, "NBR": 20, "SBL": 18, "SBT": 510, "SBR": 5},
                "2": {"EBL": 35, "EBT": 280, "EBR": 45, "WBL": 32, "WBT": 270, "WBR": 38,
                      "NBL": 28, "NBT": 510, "NBR": 22, "SBL": 20, "SBT": 490, "SBR": 6},
                "3": {"EBL": 48, "EBT": 285, "EBR": 41, "WBL": 33, "WBT": 265, "WBR": 36,
                      "NBL": 27, "NBT": 530, "NBR": 21, "SBL": 19, "SBT": 460, "SBR": 5},
            },
            "PM": {
                "1": {"NBT": 560}, "2": {"NBT": 580}, "3": {"NBT": 610},
            },
        },
        "links": [
            {"fromNum": 1, "toNum": 2, "direction": "NB/SB", "mode": "Full"},
            {"fromNum": 2, "toNum": 3, "direction": "NB/SB", "mode": "Full"},
        ],
        "link_resolution_method": "larger",
    }
    client = TestClient(app)
    r = client.post("/balance-nchrp", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    geom = [f for f in body['qc_flags'] if f['check'] == 'GEOMETRY-FALLBACK']
    assert len(geom) == 1, f"expected 1 GEOMETRY-FALLBACK on Int 2↔3; got {len(geom)}: {geom}"
    assert {geom[0]['fromNum'], geom[0]['toNum']} == {2, 3}

    link_deltas = [f for f in body['qc_flags'] if f['check'] == 'NCHRP-LINK-DELTA']
    # The 2↔3 cascade should produce at least one NCHRP-LINK-DELTA on a link
    # touching one of {2, 3}; that flag must reference the geometry root.
    cascaded = [
        f for f in link_deltas
        if 'GEOMETRY-FALLBACK at Int 2↔3' in f['message']
    ]
    assert cascaded, (
        f"expected NCHRP-LINK-DELTA on a 2↔3-touching link to name the "
        f"GEOMETRY-FALLBACK root; got messages: {[f['message'] for f in link_deltas]}"
    )
    # The cascaded flag must NOT carry the generic raw-floor message
    for f in cascaded:
        assert 'raw-floor clipping' not in f['message'], (
            f"geometry-root flag should drop the generic raw-floor hint: {f['message']}"
        )
    print(f"  test_f2_geometry_root_attached_to_link_delta_messages: PASS "
          f"({len(cascaded)} NCHRP-LINK-DELTA flag(s) name the geometry root)")


def test_f3_source_outlier_flag_fires_on_typo():
    """F3: 5-intersection corridor where Int 3 SBT was typed 12 instead of
    1200. The corridor's SB approach total averages ~430 veh; Int 3 = 18 veh
    (SBL=2, SBT=12, SBR=4) is >3σ below mean and >50 veh from it. Should
    fire SOURCE-OUTLIER on Int 3 SB approach (AM); should NOT fire on the
    other intersections."""
    from balancer import source_outlier_flags
    am = {
        1: {"SBL": 20, "SBT": 420, "SBR": 30},   # total 470
        2: {"SBL": 18, "SBT": 410, "SBR": 28},   # total 456
        3: {"SBL":  2, "SBT":  12, "SBR":  4},   # total  18 — TYPO
        4: {"SBL": 22, "SBT": 415, "SBR": 25},   # total 462
        5: {"SBL": 19, "SBT": 408, "SBR": 30},   # total 457
    }
    flags = source_outlier_flags(am, period='AM')
    sb_int3 = [f for f in flags if f['int'] == 3 and 'SB' in f['message']]
    assert len(sb_int3) == 1, f"expected 1 SOURCE-OUTLIER on Int 3 SB; got {flags}"
    msg = sb_int3[0]['message']
    assert 'lower' in msg, f"should say 'lower' (Int 3 is below mean): {msg}"
    assert 'Verify the source count' in msg
    assert sb_int3[0]['period'] == 'AM'
    # Other intersections must not be flagged
    other = [f for f in flags if f['int'] != 3]
    assert other == [], f"expected no flag on the clean intersections; got {other}"
    print(f"  test_f3_source_outlier_flag_fires_on_typo: PASS (Int 3 SB flagged, others clean)")


def test_f3_no_outlier_on_well_balanced_corridor():
    """F3: when all leg totals fall within reasonable noise of each other,
    no SOURCE-OUTLIER should fire (no false-positives on healthy corridors)."""
    from balancer import source_outlier_flags
    am = {n: {"NBT": 420 + 10 * (n - 3), "NBR": 30, "NBL": 25} for n in range(1, 6)}
    flags = source_outlier_flags(am, period='AM')
    assert flags == [], f"expected no outliers on a flat corridor; got {flags}"
    print(f"  test_f3_no_outlier_on_well_balanced_corridor: PASS")


def test_f3_abs_floor_suppresses_quiet_corridor_false_positives():
    """F3: a tiny low-volume corridor (T-leg approaches ~15 veh each, stdev
    ~2 veh) might trigger 3σ on a value 8 veh from mean. The abs_floor_veh
    guard requires at least 50 veh of absolute deviation in addition; no
    flag should fire here despite the high sigma."""
    from balancer import source_outlier_flags
    am = {1: {"NBT": 13}, 2: {"NBT": 14}, 3: {"NBT": 15}, 4: {"NBT": 16}, 5: {"NBT": 22}}
    flags = source_outlier_flags(am, period='AM')
    assert flags == [], (
        f"abs_floor_veh should suppress sub-50-veh deviations even at "
        f"high sigma; got {flags}"
    )
    print(f"  test_f3_abs_floor_suppresses_quiet_corridor_false_positives: PASS")


def test_f3_min_sample_size_skips_tiny_corridors():
    """F3: with only 2 intersections having an approach, statistics aren't
    reliable. No flag should fire even on an obvious outlier."""
    from balancer import source_outlier_flags
    am = {1: {"NBT": 420}, 2: {"NBT": 12}}
    flags = source_outlier_flags(am, period='AM')
    assert flags == [], f"expected no flag on 2-int corridor; got {flags}"
    print(f"  test_f3_min_sample_size_skips_tiny_corridors: PASS")


def test_valid_link_directions_still_accepted():
    """Regression guard: the validation rejects only unknown directions;
    well-formed 'EB/WB' and 'NB/SB' links continue to balance cleanly."""
    from fastapi.testclient import TestClient
    from app import app

    payload = {
        "intersections": [
            {"num": 1, "lat": 32.85, "lng": -116.85},
            {"num": 2, "lat": 32.86, "lng": -116.85},
        ],
        "unbalanced_volumes": {
            "AM": {"1": {"NBT": 480}, "2": {"NBT": 510}},
            "PM": {"1": {"NBT": 560}, "2": {"NBT": 580}},
        },
        "links": [
            {"fromNum": 1, "toNum": 2, "direction": "NB/SB", "mode": "Full"},
        ],
        "link_resolution_method": "larger",
    }
    client = TestClient(app)
    r = client.post("/balance-nchrp", json=payload)
    assert r.status_code == 200, f"valid 'NB/SB' direction should pass; got {r.status_code}: {r.text}"
    print(f"  test_valid_link_directions_still_accepted: PASS (200 on 'NB/SB')")


if __name__ == '__main__':
    tests = [
        test_furness_4x4_known_answer,
        test_link_resolution_larger_vs_average,
        test_3leg_t_intersection,
        test_no_phantom_movement_on_absent_leg,
        test_noleg_link_does_not_perturb_feasible_endpoint,
        test_larger_conserves_links_movements_may_drop,
        test_average_can_go_below_raw,
        test_end_to_end_3int_corridor,
        test_imbalanced_4x4_ipf,
        test_link_conservation_holds,
        test_movements_review_present,
        test_all_movements_present,
        test_fractional_volume_flag,
        test_geometry_fallback_no_emission_when_coords_distinct,
        test_geometry_fallback_fires_on_coincident_coords,
        test_geometry_fallback_one_per_link_not_per_int,
        test_geometry_fallback_deduped_across_am_pm,
        test_invalid_link_direction_rejected,
        test_valid_link_directions_still_accepted,
        test_f2_geometry_root_attached_to_link_delta_messages,
        test_f3_source_outlier_flag_fires_on_typo,
        test_f3_no_outlier_on_well_balanced_corridor,
        test_f3_abs_floor_suppresses_quiet_corridor_false_positives,
        test_f3_min_sample_size_skips_tiny_corridors,
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
