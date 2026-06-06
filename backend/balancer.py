"""
DemandIQ — balancing engine.

Extracted from the original WSP demand-analysis tool (since removed) and
cleaned for use as a web-API module.

Cleanups vs original:
- print() statements removed; functions return data, callers decide what to log.
- adjustments and qc flags returned as plain dicts (originally tuples).
- Defensive against intersection nums missing from the vols dict.
"""

# 12 standard movements — no U-turns. Order matches the original script.
MOVEMENTS = [
    'NBL', 'NBT', 'NBR',
    'SBL', 'SBT', 'SBR',
    'EBL', 'EBT', 'EBR',
    'WBL', 'WBT', 'WBR',
]


# ── Rounding ─────────────────────────────────────────────────────────────────
def round_to_5(v, original=None):
    """Round v to nearest 5; minimum 5 for any non-zero movement.

    Args:
        v:        Scaled/balanced float volume to round.
        original: Original unbalanced integer volume before Furness scaling.
                  If original > 0, result is floored at 5 — a counted movement
                  can never be rounded to zero. If original is None, v itself
                  determines zero vs non-zero (v < 0.5 → 0).
    """
    truly_empty = (original == 0) if original is not None else (v < 0.5)
    if truly_empty:
        return 0
    return max(5, int(round(v / 5.0)) * 5)



# Movement sets per balancing direction (spec §2).
#   OUTFLOW feeders = movements that LEAVE in that direction (through + 2 turns).
#   outflow_u       = U-turn that physically heads in that direction.
#                     Counted in the OUTFLOW total, NEVER receives delta.
#   APPROACH moves  = movements that ARRIVE from that direction.
DIRECTION_SPEC = {
    'EB': {'outflow': ['EBT', 'SBL', 'NBR'], 'outflow_u': 'WBU', 'approach': ['EBL', 'EBT', 'EBR']},
    'WB': {'outflow': ['WBT', 'NBL', 'SBR'], 'outflow_u': 'EBU', 'approach': ['WBL', 'WBT', 'WBR']},
    'NB': {'outflow': ['NBT', 'EBL', 'WBR'], 'outflow_u': 'SBU', 'approach': ['NBL', 'NBT', 'NBR']},
    'SB': {'outflow': ['SBT', 'WBL', 'EBR'], 'outflow_u': 'NBU', 'approach': ['SBL', 'SBT', 'SBR']},
}


# ══════════════════════════════════════════════════════════════════════════════
# Stage 4 / NCHRP rewrite: real per-intersection Fratar factoring.
#
# Replaces the previous link-by-link Gauss-Seidel scheme (removed in
# Stage 7) which had a cascade bug. This is NCHRP 255/765 turning-movement
# refinement: each intersection's 4×4 O-D matrix is
# Fratar-factored to match link-resolved and raw-derived row/column targets.
#
# Four steps:
#   A) Resolve adjacent-intersection link disagreements into ONE volume per
#      directed edge (larger or average of the two counts).
#   B) For every intersection, build a 4×4 matrix and iterate Furness
#      (row scale → col scale → repeat) until row sums and col sums match
#      their targets within tol.
#   C) Floor: clamp every movement to its raw value (balanced ≥ raw).
#   D) Round up to next multiple of 5; raw==0 stays 0.
# ══════════════════════════════════════════════════════════════════════════════

# Matrix layout: rows = approach leg (where cars came FROM); cols = exit leg
# (where cars are heading TO). Indexing follows physical leg orientation:
#   row 0 = S leg (cars came from south, going NB)
#   row 1 = N leg (cars came from north, going SB)
#   row 2 = W leg (cars came from west, going EB)
#   row 3 = E leg (cars came from east, going WB)
#   col 0 = S leg exit (cars going SB)
#   col 1 = N leg exit (cars going NB)
#   col 2 = W leg exit (cars going WB)
#   col 3 = E leg exit (cars going EB)
# Diagonal cells are U-turns (skipped — pass through unchanged per spec).
CELL_MOVEMENT = {
    (0, 0): None,  (0, 1): 'NBT', (0, 2): 'NBL', (0, 3): 'NBR',
    (1, 0): 'SBT', (1, 1): None,  (1, 2): 'SBR', (1, 3): 'SBL',
    (2, 0): 'EBR', (2, 1): 'EBL', (2, 2): None,  (2, 3): 'EBT',
    (3, 0): 'WBL', (3, 1): 'WBR', (3, 2): 'WBT', (3, 3): None,
}
# Inverse: movement code → (row, col). Useful for shared-cell detection in
# Stage 4c.3 reconciliation.
MOVEMENT_CELL = {mv: (r, c) for (r, c), mv in CELL_MOVEMENT.items() if mv is not None}
LEG_INDEX  = {'S': 0, 'N': 1, 'W': 2, 'E': 3}    # leg name → row/col index
LEG_IN_DIR  = {0: 'NB', 1: 'SB', 2: 'EB', 3: 'WB'}   # cars entering via leg
LEG_OUT_DIR = {0: 'SB', 1: 'NB', 2: 'WB', 3: 'EB'}   # cars exiting via leg

# Coordinate-equality epsilon for detecting overlapping intersection lat/lng.
# 1e-6 degrees ≈ 11 cm — far below survey precision, so anything within this
# distance is effectively "same point" and can't disambiguate leg orientation.
# Used by resolve_link_volumes to emit GEOMETRY-FALLBACK qc_flags when the
# lat/lng-based directional resolution falls through to int-number ordering.
COORD_DEGENERACY_EPS = 1e-6


def resolve_link_volumes(volumes, links, method='larger', coords=None,
                          geometry_fallbacks=None, raw_pairs_out=None):
    """STEP A — collapse two adjacent intersection counts on the same link
    into ONE resolved volume per directed edge.

    Args:
        volumes: { int_num: { movement: value } }
        links:   [{ 'fromNum': int, 'toNum': int, 'direction': 'EB/WB'|'NB/SB' }]
        method:  'larger' (default) or 'average'
        coords:  { int_num: {'lat': float, 'lng': float} } — optional but
                 strongly recommended. Without coords, num-order is used as a
                 fallback geographic ordering (assumes lower num is west/south).
        geometry_fallbacks: optional list to receive (lo_num, hi_num) tuples for
                 every link whose orientation couldn't be disambiguated from
                 coords (missing coords OR overlapping within COORD_DEGENERACY_EPS).
                 Caller turns these into GEOMETRY-FALLBACK qc_flags. Deduped
                 internally by sorted int pair so AM + PM share the same accumulator.

    Returns:
        { (upstream_num, downstream_num, dir_code): resolved_volume }
        where dir_code is one of 'EB' | 'WB' | 'NB' | 'SB'.
        EB direction has west→east upstream/downstream; SB has north→south.

    Stores BOTH directions of each link (an EB/WB link produces two entries:
    one EB, one WB).
    """
    coords = coords or {}
    out = {}

    def _note_fallback(a, b):
        if geometry_fallbacks is None:
            return
        pair = (min(a, b), max(a, b))
        if pair not in geometry_fallbacks:
            geometry_fallbacks.append(pair)

    for L in links:
        a, b = int(L['fromNum']), int(L['toNum'])
        axis = L.get('direction')
        if axis == 'EB/WB':
            # Determine which is west by longitude (or fallback: smaller num is west)
            a_lng = coords.get(a, {}).get('lng')
            b_lng = coords.get(b, {}).get('lng')
            if (a_lng is not None and b_lng is not None
                    and abs(a_lng - b_lng) > COORD_DEGENERACY_EPS):
                west, east = (a, b) if a_lng < b_lng else (b, a)
            else:
                # Either coord missing or coords are coincident within epsilon —
                # int-number ordering is the only signal we have. Record so the
                # engineer sees a named warning instead of mystery LINK-DELTA.
                west, east = (a, b) if a < b else (b, a)
                _note_fallback(a, b)
            for dir_code, up, dn in (('EB', west, east), ('WB', east, west)):
                up_vols = volumes.get(up, {})
                dn_vols = volumes.get(dn, {})
                count_up = sum(up_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['outflow'])
                count_dn = sum(dn_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['approach'])
                resolved = max(count_up, count_dn) if method == 'larger' else (count_up + count_dn) / 2.0
                out[(up, dn, dir_code)] = float(resolved)
                if raw_pairs_out is not None:
                    raw_pairs_out[(up, dn, dir_code)] = {
                        'raw_upstream': float(count_up),
                        'raw_downstream': float(count_dn),
                    }
        elif axis == 'NB/SB':
            a_lat = coords.get(a, {}).get('lat')
            b_lat = coords.get(b, {}).get('lat')
            if (a_lat is not None and b_lat is not None
                    and abs(a_lat - b_lat) > COORD_DEGENERACY_EPS):
                south, north = (a, b) if a_lat < b_lat else (b, a)
            else:
                south, north = (a, b) if a < b else (b, a)
                _note_fallback(a, b)
            for dir_code, up, dn in (('NB', south, north), ('SB', north, south)):
                up_vols = volumes.get(up, {})
                dn_vols = volumes.get(dn, {})
                count_up = sum(up_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['outflow'])
                count_dn = sum(dn_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['approach'])
                resolved = max(count_up, count_dn) if method == 'larger' else (count_up + count_dn) / 2.0
                out[(up, dn, dir_code)] = float(resolved)
                if raw_pairs_out is not None:
                    raw_pairs_out[(up, dn, dir_code)] = {
                        'raw_upstream': float(count_up),
                        'raw_downstream': float(count_dn),
                    }
    return out


def _build_links_by_int(links, coords=None):
    """Return { int_num: [(neighbor_num, leg, axis), ...] }.

    leg is 'N' | 'S' | 'E' | 'W' — which physical leg of THIS intersection the
    link sits on. Determined from coords; falls back to num ordering."""
    from collections import defaultdict
    coords = coords or {}
    out = defaultdict(list)
    for L in links:
        a, b = int(L['fromNum']), int(L['toNum'])
        axis = L.get('direction')
        if axis == 'EB/WB':
            a_lng = coords.get(a, {}).get('lng')
            b_lng = coords.get(b, {}).get('lng')
            if a_lng is not None and b_lng is not None:
                a_west = a_lng < b_lng
            else:
                a_west = a < b
            if a_west:
                out[a].append((b, 'E', axis))
                out[b].append((a, 'W', axis))
            else:
                out[a].append((b, 'W', axis))
                out[b].append((a, 'E', axis))
        elif axis == 'NB/SB':
            a_lat = coords.get(a, {}).get('lat')
            b_lat = coords.get(b, {}).get('lat')
            if a_lat is not None and b_lat is not None:
                a_south = a_lat < b_lat
            else:
                a_south = a < b
            if a_south:
                out[a].append((b, 'N', axis))
                out[b].append((a, 'S', axis))
            else:
                out[a].append((b, 'S', axis))
                out[b].append((a, 'N', axis))
    return out


def _leg_present(int_vols, leg):
    """Is this physical leg present at the intersection? A leg is missing
    when no link sits on it AND no raw movements involving it are nonzero."""
    idx = LEG_INDEX[leg]
    in_dir = LEG_IN_DIR[idx]
    out_dir = LEG_OUT_DIR[idx]
    approach_sum = sum(int_vols.get(k, 0) for k in DIRECTION_SPEC[in_dir]['approach'])
    outflow_sum  = sum(int_vols.get(k, 0) for k in DIRECTION_SPEC[out_dir]['outflow'])
    return approach_sum > 0 or outflow_sum > 0


def intersection_targets(int_num, raw_volumes, links_by_int, resolved_links):
    """STEP B prep — compute row and column targets for one intersection's 4×4
    matrix, plus which legs are present (for 3-leg T intersections, the missing
    leg's row and col are masked).

    Returns:
        row_targets[0..3]:  float or None (None = leg absent / 3-leg T)
        col_targets[0..3]:  float or None
        present[0..3]:      bool — True if that leg exists at this int
    """
    int_vols = raw_volumes.get(int_num, {})
    row_targets = [None] * 4
    col_targets = [None] * 4
    present    = [False] * 4

    # Which legs have links?
    leg_to_link = {}
    for (neighbor, leg, axis) in links_by_int.get(int_num, []):
        leg_to_link[leg] = (neighbor, axis)

    for leg, idx in LEG_INDEX.items():
        in_dir = LEG_IN_DIR[idx]
        out_dir = LEG_OUT_DIR[idx]
        if leg in leg_to_link:
            # Linked leg — targets come from resolved link volumes
            neighbor, _axis = leg_to_link[leg]
            row_targets[idx] = resolved_links.get((neighbor, int_num, in_dir), 0.0)
            col_targets[idx] = resolved_links.get((int_num, neighbor, out_dir), 0.0)
            present[idx] = True
        elif _leg_present(int_vols, leg):
            # Stub leg with raw movements — use raw sums
            row_targets[idx] = float(sum(int_vols.get(k, 0) for k in DIRECTION_SPEC[in_dir]['approach']))
            col_targets[idx] = float(sum(int_vols.get(k, 0) for k in DIRECTION_SPEC[out_dir]['outflow']))
            present[idx] = True
        # else: leg absent (3-leg T) — targets stay None, present stays False

    return row_targets, col_targets, present


def balance_leg_totals(
    raw_volumes,
    links,
    method='larger',
    coords=None,
    max_outer=500,
    tol=1e-7,
):
    """STEP B Level 1 — Network-level leg-total balancing (NCHRP 255 §C.2,
    NCHRP 765 ch. 6). Alternates two projections until the targets are
    network-consistent:

      (1) LINK EQUALITY — for every directed link (u → d) in direction `dir`,
          set col_t[u][u_leg] = row_t[d][d_leg] = larger_or_avg(both sides).
          After this step, adjacent intersections agree on each link.

      (2) INTERSECTION CONSERVATION — at each intersection X, scale row + col
          targets to their geometric mean (target = sqrt(row_sum × col_sum)).
          Symmetric / minimum-perturbation. Ensures row_total == col_total at
          each intersection so Level 2 per-intersection IPF can hit both
          target sets exactly.

    After convergence, level-2 per-intersection IPF with these targets
    converges to exact match → link conservation holds across the network
    automatically (delta < tol pre-rounding).

    Returns:
        (row_t, col_t, present_t, outer_iters, converged, qc_flags)
        row_t / col_t: { int_num: [s, n, w, e] target lists }  (leg-indexed)
        present_t:     { int_num: [bool, bool, bool, bool] }   (leg-present mask)
        qc_flags:      NCHRP-LINK-INFEASIBLE entries (when Larger was forced
                       to fall back to Average on a specific link)
    """
    import math
    coords = coords or {}
    qc_flags = []

    # Initialize row + col targets from raw leg sums
    row_t = {}
    col_t = {}
    present_t = {}
    for int_num, int_vols in raw_volumes.items():
        rt = [0.0] * 4
        ct = [0.0] * 4
        pres = [False] * 4
        for leg, idx in LEG_INDEX.items():
            in_dir  = LEG_IN_DIR[idx]
            out_dir = LEG_OUT_DIR[idx]
            rt[idx] = float(sum(int_vols.get(k, 0) for k in DIRECTION_SPEC[in_dir]['approach']))
            ct[idx] = float(sum(int_vols.get(k, 0) for k in DIRECTION_SPEC[out_dir]['outflow']))
            pres[idx] = (rt[idx] > 0) or (ct[idx] > 0)
        row_t[int_num] = rt
        col_t[int_num] = ct
        present_t[int_num] = pres

    # Build link endpoint list with geographic ordering. Each EB/WB link
    # produces TWO directed entries (one EB, one WB); each NB/SB produces
    # one NB and one SB. Per-link method override possible via feasibility
    # check below.
    link_directed = []           # list of (u, u_leg_idx, d, d_leg_idx, direction_code, method_override)
    link_methods = {}            # (link_id) → 'larger' | 'average' after feasibility check

    for L_idx, L in enumerate(links):
        # Skip None-mode links from leg-total balancing entirely. They appear
        # in the conservation table as informational but don't participate in
        # Level 1 link-equality enforcement.
        if L.get('mode', 'Full') == 'None':
            continue
        a, b = int(L['fromNum']), int(L['toNum'])
        axis = L.get('direction')
        if axis == 'EB/WB':
            a_lng = coords.get(a, {}).get('lng')
            b_lng = coords.get(b, {}).get('lng')
            if a_lng is not None and b_lng is not None:
                west, east = (a, b) if a_lng < b_lng else (b, a)
            else:
                west, east = (a, b) if a < b else (b, a)
            link_directed.append((west, LEG_INDEX['E'], east, LEG_INDEX['W'], 'EB', L_idx))
            link_directed.append((east, LEG_INDEX['W'], west, LEG_INDEX['E'], 'WB', L_idx))
        elif axis == 'NB/SB':
            a_lat = coords.get(a, {}).get('lat')
            b_lat = coords.get(b, {}).get('lat')
            if a_lat is not None and b_lat is not None:
                south, north = (a, b) if a_lat < b_lat else (b, a)
            else:
                south, north = (a, b) if a < b else (b, a)
            link_directed.append((south, LEG_INDEX['N'], north, LEG_INDEX['S'], 'NB', L_idx))
            link_directed.append((north, LEG_INDEX['S'], south, LEG_INDEX['N'], 'SB', L_idx))
        # Mark linked legs as present even if raw was 0
        for u, u_leg, d, d_leg, _dir, _idx in link_directed[-2:]:
            present_t[u][u_leg] = True
            present_t[d][d_leg] = True

    # ── Feasibility check: per directed edge, would Larger blow up at either
    # endpoint? If so, fall back to Average for that link and emit flag.
    # Threshold 0.95: a single linked leg can't legitimately exceed 95% of an
    # intersection's outflow total or the math has no room for other legs.
    method_per_directed = {}
    for (u, u_leg, d, d_leg, direction, link_idx) in link_directed:
        u_col_raw = col_t[u][u_leg]
        d_row_raw = row_t[d][d_leg]
        larger_val = max(u_col_raw, d_row_raw)
        u_col_total = sum(col_t[u])
        d_row_total = sum(row_t[d])
        infeasible_u = u_col_total > 0 and larger_val > u_col_total * 0.95
        infeasible_d = d_row_total > 0 and larger_val > d_row_total * 0.95
        if method == 'larger' and (infeasible_u or infeasible_d):
            method_per_directed[(u, d, direction)] = 'average'
            qc_flags.append({
                'check': 'NCHRP-LINK-INFEASIBLE',
                'int': u,
                'message': (
                    f"Link {u}→{d} {direction}: Larger resolution ({larger_val:.0f}) "
                    f"exceeds 95% of "
                    + ('upstream' if infeasible_u else 'downstream')
                    + " col/row total — falling back to Average for this link."
                ),
            })
        else:
            method_per_directed[(u, d, direction)] = method

    # ── Phase 0: ONE-SHOT initial link resolution per the chosen method.
    # The user-facing Larger/Average toggle determines the BIAS of the initial
    # link target (max vs mean of the two adjacent raw counts). After this,
    # the iterative link-equality step always averages — using max() in the
    # loop ratchets the linked targets up monotonically against the
    # geometric-mean conservation step, so it never converges under Larger.
    for (u, u_leg, d, d_leg, direction, _idx) in link_directed:
        m = method_per_directed[(u, d, direction)]
        v_u = col_t[u][u_leg]
        v_d = row_t[d][d_leg]
        v_init = max(v_u, v_d) if m == 'larger' else (v_u + v_d) / 2.0
        col_t[u][u_leg] = v_init
        row_t[d][d_leg] = v_init

    # ── Alternating projection outer loop
    converged = False
    outer_iters = 0
    for outer_it in range(max_outer):
        snap_row = {k: list(v) for k, v in row_t.items()}
        snap_col = {k: list(v) for k, v in col_t.items()}

        # (1) Link equality — always average to ensure convergence. The initial
        # Larger/Average bias was applied in Phase 0 above.
        for (u, u_leg, d, d_leg, direction, _idx) in link_directed:
            v_u = col_t[u][u_leg]
            v_d = row_t[d][d_leg]
            new = (v_u + v_d) / 2.0
            col_t[u][u_leg] = new
            row_t[d][d_leg] = new

        # (2) Intersection conservation — geometric-mean scaling per int
        for int_num in row_t:
            row_sum = sum(row_t[int_num])
            col_sum = sum(col_t[int_num])
            if row_sum <= 0 or col_sum <= 0:
                continue
            target_total = math.sqrt(row_sum * col_sum)
            rf = target_total / row_sum
            cf = target_total / col_sum
            for i in range(4):
                row_t[int_num][i] *= rf
                col_t[int_num][i] *= cf

        # Convergence check
        max_change = 0.0
        for int_num in row_t:
            for i in range(4):
                max_change = max(max_change, abs(row_t[int_num][i] - snap_row[int_num][i]))
                max_change = max(max_change, abs(col_t[int_num][i] - snap_col[int_num][i]))

        outer_iters = outer_it + 1
        if max_change < tol:
            converged = True
            break

    return row_t, col_t, present_t, outer_iters, converged, qc_flags


def furness_intersection(matrix, row_targets, col_targets, present, tol=0.5, max_iter=500):
    """STEP B — true biproportional iterative fitting (IPF / RAS / Sinkhorn).

    Iterates row-scaling and column-scaling on a 4×4 (or masked 3×3) matrix
    until the MATRIX STABILIZES — that is, until no cell changes by more
    than `tol` vehicles between consecutive iterations.

    This is the textbook IPF convergence criterion (NCHRP 765, also Sinkhorn-
    Knopp). It is well-defined regardless of whether the row and column
    targets sum to the same total. When row_total != col_total, IPF still
    converges to the KL-divergence-minimum matrix (the "closest" balanced
    matrix consistent with as much of both target sets as possible); the
    residual between row sums and row targets (or col sums and col targets)
    after convergence represents the inherent data inconsistency.

    Earlier versions of this function pre-normalized targets so their totals
    matched (averaging row_total and col_total). That was a workaround for
    the WRONG convergence criterion ("row residuals AND col residuals both <
    tol") — and it artificially shrank link-resolved targets, propagating
    bias into the balanced cells. True IPF doesn't need normalization.

    Returns: (matrix, converged_bool, iters_used, final_residual)
        final_residual = max abs(row_sum - row_target, col_sum - col_target)
                         across all present rows/cols at convergence — the
                         imbalance the math couldn't resolve.
    """
    M = [row[:] for row in matrix]   # local copy

    def row_sum(r):
        return sum(M[r][c] for c in range(4) if present[c])

    def col_sum(c):
        return sum(M[r][c] for r in range(4) if present[r])

    def compute_target_residual():
        res = 0.0
        for r in range(4):
            if present[r] and row_targets[r] is not None:
                res = max(res, abs(row_sum(r) - row_targets[r]))
        for c in range(4):
            if present[c] and col_targets[c] is not None:
                res = max(res, abs(col_sum(c) - col_targets[c]))
        return res

    iters_used = 0
    converged = False
    for it in range(max_iter):
        # Snapshot the matrix at the start of this iteration so we can measure
        # how much it changes — that's the IPF convergence signal.
        prev = [row[:] for row in M]

        # Row scaling
        for r in range(4):
            if not present[r] or row_targets[r] is None:
                continue
            cur = row_sum(r)
            if cur > 0:
                f = row_targets[r] / cur
                for c in range(4):
                    if present[c]:
                        M[r][c] *= f

        # Column scaling
        for c in range(4):
            if not present[c] or col_targets[c] is None:
                continue
            cur = col_sum(c)
            if cur > 0:
                f = col_targets[c] / cur
                for r in range(4):
                    if present[r]:
                        M[r][c] *= f

        iters_used = it + 1

        # Convergence by matrix stability: max |M[r][c] - prev[r][c]|
        max_cell_delta = 0.0
        for r in range(4):
            for c in range(4):
                if present[r] and present[c]:
                    max_cell_delta = max(max_cell_delta, abs(M[r][c] - prev[r][c]))
        if max_cell_delta < tol:
            converged = True
            break

    final_residual = compute_target_residual()
    return M, converged, iters_used, final_residual


def _build_matrix(int_vols):
    """Pull the 12 turn movements out of an intersection's raw volume dict
    into the 4×4 cell layout. Diagonal/U-turn cells stay 0."""
    M = [[0.0] * 4 for _ in range(4)]
    for (r, c), mv in CELL_MOVEMENT.items():
        if mv is None:
            continue
        M[r][c] = float(int_vols.get(mv, 0))
    return M


def _extract_matrix(matrix):
    """Inverse of _build_matrix — pull 12 turn movements back out of the
    balanced matrix into a {movement: value} dict."""
    out = {}
    for (r, c), mv in CELL_MOVEMENT.items():
        if mv is None:
            continue
        out[mv] = matrix[r][c]
    return out


def _round_up_5_nchrp(x, raw_x):
    """STEP D — round up to next multiple of 5; raw==0 keeps balanced at 0."""
    import math
    if raw_x is not None and raw_x == 0:
        return 0
    if abs(x) < 1e-9:
        return 0
    return int(math.ceil(x / 5.0) * 5)


def _adjust_leg_to_target(balanced_int, ltr_keys, raw_int, target, shared_keys=None):
    """Stage 4c.3 helper. Round each of the 3 L/T/R cells up to nearest 5
    (raw==0 stays 0), then add/subtract 5 from cells until the leg's L+T+R
    sum equals `target`.

    Cell-selection priority: cells NOT in `shared_keys` are preferred — this
    matters at corridor intersections where a cell (e.g. EBT) is in both a
    linked col (one direction's outflow) AND a linked row (another link's
    approach). Touching the shared cell breaks the other link's constraint;
    touching a non-shared cell doesn't. Falls back to shared cells if
    non-shared options are exhausted.

    Cells stay non-negative multiples of 5. The raw>0⇒balanced≥5 invariant
    applies to initial rounding but is relaxed during adjustment when link
    conservation requires (rare; corridor-stub edge case).

    Returns: target - final_sum.
    """
    import math
    shared = set(shared_keys or [])
    non_shared = [k for k in ltr_keys if k not in shared]
    shared_in_leg = [k for k in ltr_keys if k in shared]

    # Initial Step-D rounding (raw==0 stays 0; else ceil to next 5)
    for k in ltr_keys:
        if raw_int.get(k, 0) == 0:
            balanced_int[k] = 0
        else:
            balanced_int[k] = int(math.ceil(balanced_int.get(k, 0) / 5.0) * 5)

    for _ in range(1000):
        cur_sum = sum(balanced_int.get(k, 0) for k in ltr_keys)
        if cur_sum == target:
            return 0

        if cur_sum > target:
            # Decrement: try non-shared first, then shared. Within each tier,
            # pick the largest cell that's ≥ 5 (can drop by 5 without going
            # negative).
            for tier in (non_shared, shared_in_leg):
                cands = sorted(
                    [(balanced_int[k], k) for k in tier if balanced_int[k] >= 5],
                    reverse=True,
                )
                if cands:
                    balanced_int[cands[0][1]] -= 5
                    break
            else:
                return target - cur_sum     # cannot shrink further
        else:
            # Increment: prefer non-shared, then shared. Within each tier,
            # add 5 to the largest cell.
            for tier in (non_shared, shared_in_leg):
                if tier:
                    largest_k = max(tier, key=lambda k: balanced_int.get(k, 0))
                    balanced_int[largest_k] += 5
                    break
            else:
                return target - cur_sum

    return target - sum(balanced_int.get(k, 0) for k in ltr_keys)


def compute_link_conservation(balanced, resolved_links, link_modes=None):
    """For every directed link, compute upstream outflow vs downstream inflow
    on the BALANCED matrix and the resulting delta. Each entry is tagged with
    the link's mode ('Full' | 'Land Use' | 'None') if `link_modes` is provided.

    Args:
        balanced:        { int_num: { movement: value } }
        resolved_links:  { (u, d, direction): float } — key set drives iteration
        link_modes:      optional { (u, d, direction): 'Full'|'Land Use'|'None' }

    Returns:
        list of dicts with keys: fromNum, toNum, direction, upstream_outflow,
        downstream_inflow, delta, mode.
    """
    link_modes = link_modes or {}
    out = []
    for (u, d, direction) in sorted(resolved_links.keys()):
        u_vols = balanced.get(u, {})
        d_vols = balanced.get(d, {})
        spec = DIRECTION_SPEC[direction]
        outflow = sum(u_vols.get(k, 0) for k in spec['outflow']) + u_vols.get(spec['outflow_u'], 0)
        inflow  = sum(d_vols.get(k, 0) for k in spec['approach'])
        out.append({
            'fromNum': u,
            'toNum': d,
            'direction': direction,
            'upstream_outflow': float(outflow),
            'downstream_inflow': float(inflow),
            'delta': float(inflow - outflow),
            'mode': link_modes.get((u, d, direction), 'Full'),
        })
    return out


def compute_movements_review(raw_volumes, balanced):
    """Stage 5 (amendment v2): enumerate EVERY standard 12-movement entry at
    every intersection — including movements where balanced >= raw. The
    Review UI surfaces all values for engineer review; drops (balanced<raw)
    are visually highlighted by the frontend, not gated server-side.

    Args:
        raw_volumes: { int_num: { movement: value } }
        balanced:    { int_num: { movement: value } }  (post-round-up-5)

    Returns: list of dicts, one entry per (int_num, movement) pair, sorted
    by int_num asc then movement in standard L/T/R order. Movements with
    raw == 0 are skipped (no engineering meaning at a missing-leg cell).
        {
          'int_num': int, 'movement': str,
          'raw': int, 'balanced': int, 'delta': int,   # delta = balanced - raw
        }
    U-turns are excluded (passed through unchanged by IPF).
    """
    standard_movements = (
        'EBL', 'EBT', 'EBR',
        'WBL', 'WBT', 'WBR',
        'NBL', 'NBT', 'NBR',
        'SBL', 'SBT', 'SBR',
    )
    out = []
    for int_num in sorted(raw_volumes.keys()):
        raw = raw_volumes[int_num]
        bal = balanced.get(int_num, {})
        for mv in standard_movements:
            r = int(raw.get(mv, 0) or 0)
            b = int(bal.get(mv, 0) or 0)
            if r <= 0:
                continue
            out.append({
                'int_num': int_num,
                'movement': mv,
                'raw': r,
                'balanced': b,
                'delta': b - r,
            })
    return out


def _build_link_modes(links, coords=None):
    """Build {(u, d, direction): mode} mapping from a link list. Mirrors the
    geographic ordering used in resolve_link_volumes and _build_links_by_int."""
    coords = coords or {}
    out = {}
    for L in links:
        a, b = int(L['fromNum']), int(L['toNum'])
        axis = L.get('direction')
        mode = L.get('mode', 'Full')
        if axis == 'EB/WB':
            a_lng = coords.get(a, {}).get('lng')
            b_lng = coords.get(b, {}).get('lng')
            if a_lng is not None and b_lng is not None:
                west, east = (a, b) if a_lng < b_lng else (b, a)
            else:
                west, east = (a, b) if a < b else (b, a)
            out[(west, east, 'EB')] = mode
            out[(east, west, 'WB')] = mode
        elif axis == 'NB/SB':
            a_lat = coords.get(a, {}).get('lat')
            b_lat = coords.get(b, {}).get('lat')
            if a_lat is not None and b_lat is not None:
                south, north = (a, b) if a_lat < b_lat else (b, a)
            else:
                south, north = (a, b) if a < b else (b, a)
            out[(south, north, 'NB')] = mode
            out[(north, south, 'SB')] = mode
    return out


def _median(values):
    """Median of a non-empty iterable. Integer-safe; returns float."""
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def source_outlier_flags(raw_volumes, period=None,
                         sigma_threshold=3.0, abs_floor_veh=50.0,
                         min_intersections=3):
    """F3 — source-data QC: flag intersections whose leg-approach total is
    statistically implausible against the corridor's other intersections.

    Catches data-entry mistakes that Furness silently absorbs — e.g. a SBT
    count typed as 12 instead of 1200 reads as a normal balanced result if
    the only signal is "the algorithm converged." This is a read-only check
    on RAW inputs (the leg's L+T+R sum per approach direction) BEFORE
    balancing, peer to fractional_volume_flags.

    Uses median + median-absolute-deviation (MAD) — a single extreme typo
    inflates the sample stdev enough to mask itself, but the median + MAD
    pair is robust to contamination. Robust-σ ≈ 1.4826 × MAD makes the unit
    consistent with the spec's "X σ from the corridor center" reading.

    For each leg direction (EB / WB / NB / SB):
      1. Collect the leg approach total at every intersection that HAS that
         approach (T-intersection missing legs are excluded — their absence
         is structural, not an outlier).
      2. Skip if fewer than min_intersections samples (stats noisy on tiny
         corridors).
      3. Compute corridor median + MAD-based robust σ. Flag any intersection
         whose |total - median| exceeds BOTH sigma_threshold × robust σ AND
         abs_floor_veh. The absolute floor prevents low-volume corridors
         (median ≈ 15, MAD ≈ 1, robust σ ≈ 1.5 veh) from false-positiving on
         a 5-veh wobble that's statistically extreme but operationally
         meaningless.

    Args:
        raw_volumes: { int_num: { movement: value } }
        period:      optional 'AM'|'PM' baked into the message
        sigma_threshold:  multiples of robust σ to trigger (default 3.0)
        abs_floor_veh:    absolute deviation required in addition (default 50)
        min_intersections: minimum sample size before the leg's stats are
                          considered reliable (default 3)

    Returns: list of {'check','int','message'[,'period']} dicts, sorted by
    int_num then leg direction for deterministic order.
    """
    DIRECTIONS = ('EB', 'WB', 'NB', 'SB')
    LTR = ('L', 'T', 'R')
    # 1.4826 × MAD ≈ σ for Gaussian data; standard robust-σ conversion.
    MAD_TO_SIGMA = 1.4826
    flags = []

    for direction in DIRECTIONS:
        totals = {}
        for int_num in sorted(raw_volumes.keys()):
            vols = raw_volumes[int_num] or {}
            cells = [vols.get(f'{direction}{m}', 0) or 0 for m in LTR]
            # Skip missing legs (all-zero across L/T/R means structural absence
            # OR a fully-empty raw — neither case is statistically meaningful).
            if not any(c > 0 for c in cells):
                continue
            totals[int_num] = sum(c for c in cells if isinstance(c, (int, float)))

        if len(totals) < min_intersections:
            continue

        vals = list(totals.values())
        med = _median(vals)
        mad = _median([abs(v - med) for v in vals])
        # MAD == 0 → most of the values are identical; we have no scale to
        # measure deviation against. Skip rather than fire arbitrary alarms.
        if mad <= 0:
            continue
        robust_sigma = MAD_TO_SIGMA * mad

        for int_num in sorted(totals.keys()):
            total = totals[int_num]
            dev = total - med
            if abs(dev) < abs_floor_veh:
                continue
            sigma = abs(dev) / robust_sigma
            if sigma < sigma_threshold:
                continue
            pstr = f" ({period})" if period else ""
            direction_word = 'lower' if dev < 0 else 'higher'
            flag = {
                'check': 'SOURCE-OUTLIER',
                'int': int_num,
                'message': (
                    f"Int {int_num} {direction} approach total = {total:.0f} veh{pstr}, "
                    f"corridor median = {med:.0f} (robust σ={robust_sigma:.0f}) "
                    f"— {sigma:.1f}σ {direction_word}. Verify the source count."
                ),
            }
            if period:
                flag['period'] = period
            flags.append(flag)

    flags.sort(key=lambda f: (f['int'], f['message']))
    return flags


def fractional_volume_flags(raw_volumes, period=None, eps=1e-6):
    """Stage 10.1 — source-data QC: flag RAW movement values that aren't
    whole numbers (the fractional data-entry bug). This is a read-only
    check on raw inputs, run BEFORE balancing — NOT a balancing check.

    eps tolerates float-representation noise (e.g. 100.0000001 is treated
    as 100). bool is excluded (True/False are ints in Python but never a
    legitimate volume).

    Args:
        raw_volumes: { int_num: { movement: value } }
        period:      optional 'AM'|'PM' — baked into the message + 'period'
                     key when provided.

    Returns: list of {'check','int','message'[,'period']} dicts.
    """
    flags = []
    for int_num in sorted(raw_volumes.keys()):
        vols = raw_volumes[int_num] or {}
        for mv in sorted(vols.keys()):
            value = vols[mv]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if abs(value - round(value)) > eps:
                pstr = f" ({period})" if period else ""
                flag = {
                    'check': 'FRACTIONAL-VOLUME',
                    'int': int_num,
                    'message': (f"Int {int_num} {mv}{pstr}: raw value {value} "
                                f"is not a whole number — likely a data-entry "
                                f"error. Verify the source count."),
                }
                if period:
                    flag['period'] = period
                flags.append(flag)
    return flags


def balance_nchrp(
    raw_volumes,
    links,
    method='larger',
    coords=None,
    round_to_5=True,
    tol=0.5,
    max_iter=500,
):
    """Top-level NCHRP 255/765 turning-movement refinement.

    Three steps:
      A) resolve_link_volumes — collapse adjacent counts on each link into
         one volume per directed edge ('larger' or 'average')
      B) Per-intersection 4×4 biproportional iterative fitting (IPF / RAS /
         Sinkhorn) against link-resolved + raw row/col targets. NO target
         pre-normalization — IPF handles imbalanced targets natively by
         converging on matrix stability (KL-divergence minimum).
      D) Round balanced up to next multiple of 5; raw == 0 stays 0

    History notes (so future readers don't re-introduce broken steps):
      - Stage 4 included a post-processing "floor" step (clamp balanced ≥
        raw). Removed in 4b because it defeats Furness convergence and
        creates phantom link conservation violations.
      - Stage 4 also included a "target averaging" normalization step
        (scale row + col targets to their common mean before Furness).
        Removed in 4c because it (1) artificially shrank link-resolved
        targets, propagating bias into balanced cells, and (2) was only
        needed because the old convergence test was the WRONG one (residual-
        to-target). True IPF uses matrix-stability convergence and handles
        imbalanced targets natively — see furness_intersection() docstring.
      - Under 'larger' resolution Furness can still produce some cells
        below raw because col-scaling shrinks cells after row-scaling
        raised them; this is the mathematical truth, not a bug.

    Args:
        raw_volumes: { int_num: { movement: value } }
        links:       [{ 'fromNum', 'toNum', 'direction': 'EB/WB'|'NB/SB' }]
                     Pass `mode: 'None'` links pre-filtered out by caller.
        method:      'larger' (default) or 'average' — link disagreement
                     resolution per S5 setting.
        coords:      { int_num: {'lat','lng'} } — for geographic leg ordering.
        round_to_5:  round balanced up to next multiple of 5.
        tol:         convergence tolerance (max cell delta between iters,
                     vehicles).
        max_iter:    IPF iteration cap per intersection.

    Returns:
        {
          'balanced': { int_num: { movement: value } },
          'resolved_links': { (u, d, dir): float },
          'qc_flags': [ {check, int, message}, ... ],   # NCHRP-RESIDUAL, NCHRP-CONV
          'iterations':     { int_num: int },
          'converged':      { int_num: bool },
          'final_residual': { int_num: float },   # max |row_sum - row_target|
                                                  # or  |col_sum - col_target|
                                                  # after IPF converges — the
                                                  # irreducible imbalance.
          'method':         method,
        }
    """
    import copy

    # Step A: resolve link disagreements. Collect geometry-fallback events
    # (coords missing or coincident within COORD_DEGENERACY_EPS) so we can
    # emit GEOMETRY-FALLBACK qc_flags downstream — engineers see a named
    # warning rather than mystery NCHRP-LINK-DELTA residuals from a leg
    # whose orientation was guessed from int-number order.
    geometry_fallbacks = []
    raw_link_pairs = {}
    resolved = resolve_link_volumes(raw_volumes, links, method=method, coords=coords,
                                     geometry_fallbacks=geometry_fallbacks,
                                     raw_pairs_out=raw_link_pairs)
    links_by_int = _build_links_by_int(links, coords=coords)

    # ── Step B Level 1: balance_leg_totals (network leg-total reconciliation)
    # Produces row/col targets that are simultaneously link-consistent and
    # intersection-conserving, so Level 2 per-int IPF hits exact targets and
    # link conservation holds across the network.
    row_targets_per_int, col_targets_per_int, presents, level1_iters, level1_conv, level1_flags = (
        balance_leg_totals(raw_volumes, links, method=method, coords=coords, max_outer=500, tol=1e-7)
    )
    balanced = {}
    iterations = {}
    converged_map = {}
    final_residual_map = {}
    qc_flags = list(level1_flags)             # carry NCHRP-LINK-INFEASIBLE through

    # GEOMETRY-FALLBACK: one flag per link pair whose leg orientation couldn't
    # be resolved from lat/lng. period=None signals the flag is corridor-level
    # (not period-specific); app.py preserves that and dedupes across AM + PM.
    for (lo, hi) in geometry_fallbacks:
        qc_flags.append({
            'check': 'GEOMETRY-FALLBACK',
            'period': None,
            'fromNum': lo,
            'toNum': hi,
            'message': (
                f"Directional fallback used at Int {lo}↔{hi} "
                f"— verify leg orientation."
            ),
        })

    # Pass-through intersections (no present legs) — typically intersections
    # with no volumes and no links. Skip Level 2.
    matrices = {}
    skip_set = set()
    for int_num, int_vols in raw_volumes.items():
        if not any(presents[int_num]):
            balanced[int_num] = dict(int_vols)
            iterations[int_num] = 0
            converged_map[int_num] = True
            final_residual_map[int_num] = 0.0
            skip_set.add(int_num)
            continue
        matrices[int_num] = _build_matrix(int_vols)
        iterations[int_num] = 0
        converged_map[int_num] = False
        final_residual_map[int_num] = 0.0

    if not level1_conv:
        qc_flags.append({
            'check': 'NCHRP-LEVEL1',
            'int': 0,
            'message': (
                f"Level 1 (balance_leg_totals) did not converge in 500 outer iterations. "
                f"Final per-intersection IPF targets may not be link-consistent."
            ),
        })

    # ── Step B Level 2: per-intersection IPF against the reconciled targets.
    # Use a tight tolerance — Level 1 already balanced row/col totals, so IPF
    # should converge to exact targets except at thin-matrix intersections
    # (single-cell columns/rows from structural zeros) where structural
    # infeasibility leaves a small residual (typically a few veh). Link-enforcement post-processing was tried
    # (both as a nested outer loop and as a single-pass fixup) and found to
    # be mathematically intractable when raw counts have row/col-total
    # imbalance at one or more intersections — see balancer.py git history
    # 2026-05-27/28 for traces. Briefly: at multi-leg intersections, each
    # link's row-scale and col-scale interfere with every other link's at
    # the same node, and no fixed point exists that satisfies all link
    # conservation constraints AND intersection-internal IPF targets
    # simultaneously when local row_total != col_total. The honest answer
    # is to run IPF cleanly and surface the link deltas as informational
    # via compute_link_conservation; engineers see exactly where adjacent
    # counts disagree.
    for int_num, M in matrices.items():
        # Use 0.01 veh tolerance — far tighter than the default 0.5 — because
        # Level 1 already gave us balanced targets. The only sources of
        # non-zero residual are (a) IPF cell-stability tolerance and
        # (b) structural infeasibility from thin matrices.
        M_out, conv, iters_used, final_residual = furness_intersection(
            M, row_targets_per_int[int_num], col_targets_per_int[int_num],
            presents[int_num], tol=0.01, max_iter=max(max_iter, 2000),
        )
        matrices[int_num] = M_out
        iterations[int_num] = iters_used
        converged_map[int_num] = conv
        final_residual_map[int_num] = final_residual

    # Build balanced dict from final matrices (skip pass-through intersections)
    for int_num, M in matrices.items():
        movements = _extract_matrix(M)
        full = dict(raw_volumes[int_num])
        for mv, val in movements.items():
            full[mv] = val
        balanced[int_num] = full

    # Emit NCHRP-CONV for intersections whose INNER IPF didn't stabilize on
    # the last outer pass.
    for int_num, conv in converged_map.items():
        if int_num in skip_set:
            continue
        if not conv:
            qc_flags.append({
                'check': 'NCHRP-CONV',
                'int': int_num,
                'message': (
                    f"Int {int_num}: inner IPF did not stabilize in {max_iter} iter on "
                    f"last outer pass (max cell delta still > {tol} veh)."
                ),
            })

    # Step C (floor) intentionally removed — see docstring. Furness alone is
    # the algorithm; the floor was a post-processing override.

    # ── Pre-round snapshot for canonical-link-volume computation ─────────
    link_modes = _build_link_modes(links, coords=coords)
    pre_round_lc = compute_link_conservation(balanced, resolved, link_modes)
    canonical_by_link = {}
    import math
    for entry in pre_round_lc:
        key = (entry['fromNum'], entry['toNum'], entry['direction'])
        avg = (entry['upstream_outflow'] + entry['downstream_inflow']) / 2.0
        canonical_by_link[key] = int(math.ceil(avg / 5.0) * 5)

    # ── Step D: round up to next 5 (all cells) ──────────────────────────
    if round_to_5:
        for int_num, balanced_vols in balanced.items():
            raw = raw_volumes.get(int_num, {})
            for mv in list(balanced_vols.keys()):
                balanced_vols[mv] = _round_up_5_nchrp(balanced_vols[mv], raw.get(mv))

    # ── Stage 4c.3: post-round link reconciliation ──────────────────────
    # For each Full directed link, force both endpoints' leg L+T+R sums to
    # equal the canonical link volume (= round5(avg pre-round)). This makes
    # link conservation hold EXACTLY for Full links post-round, modulo the
    # rare case where _adjust_leg_to_target can't shrink due to raw-floor.
    #
    # Iterates because corridor intersections that are both downstream of
    # one link AND upstream of another (in the SAME direction) have a
    # shared cell (e.g. EBT at Int 2 sits in both the W-link approach row
    # and the E-link outflow col). The outer loop damps the interference.
    full_endpoints = {}    # (u, d, direction) → (u_leg_idx, d_leg_idx)
    for (u, d, direction) in resolved.keys():
        mode = link_modes.get((u, d, direction), 'Full')
        if mode != 'Full':
            continue
        u_leg = next((leg for (nb, leg, _ax) in links_by_int.get(u, []) if nb == d), None)
        d_leg = next((leg for (nb, leg, _ax) in links_by_int.get(d, []) if nb == u), None)
        if u_leg is None or d_leg is None:
            continue
        full_endpoints[(u, d, direction)] = (LEG_INDEX[u_leg], LEG_INDEX[d_leg])

    # Precompute which leg indices are linked at each intersection. A cell
    # at (r, c) of intersection X is "shared" with another linked leg iff
    # the OTHER axis index (the one NOT equal to the leg currently being
    # reconciled) is in linked_legs[X]. Used by _adjust_leg_to_target's
    # shared_keys arg.
    linked_legs_at = {}    # int_num → set of leg indices that have any link
    for int_num, entries in links_by_int.items():
        linked_legs_at[int_num] = {LEG_INDEX[leg] for (_nb, leg, _ax) in entries}

    def _shared_keys_outflow(int_num, ltr_keys, this_leg_idx):
        """For outflow cells (all in col this_leg_idx), shared with another
        linked row iff the cell's row index is also in linked_legs_at[int_num]."""
        linked = linked_legs_at.get(int_num, set())
        result = []
        for k in ltr_keys:
            r, _c = MOVEMENT_CELL.get(k, (None, None))
            if r is not None and r != this_leg_idx and r in linked:
                result.append(k)
        return result

    def _shared_keys_approach(int_num, ltr_keys, this_leg_idx):
        """For approach cells (all in row this_leg_idx), shared with another
        linked col iff the cell's col index is also linked."""
        linked = linked_legs_at.get(int_num, set())
        result = []
        for k in ltr_keys:
            _r, c = MOVEMENT_CELL.get(k, (None, None))
            if c is not None and c != this_leg_idx and c in linked:
                result.append(k)
        return result

    RECONCILE_MAX_OUTER = 500
    if round_to_5 and full_endpoints:
        for outer_it in range(RECONCILE_MAX_OUTER):
            any_change = False
            for (u, d, direction), (u_leg_idx, d_leg_idx) in full_endpoints.items():
                canonical = canonical_by_link[(u, d, direction)]
                spec = DIRECTION_SPEC[direction]

                # Upstream: leg-col cells. Cells whose row is also a linked
                # leg at u are "shared" — touching them perturbs that other
                # linked leg's row sum. Prefer non-shared.
                u_uturn = balanced[u].get(spec['outflow_u'], 0)
                u_target = canonical - u_uturn
                u_keys = spec['outflow']
                u_shared = _shared_keys_outflow(u, u_keys, u_leg_idx)
                u_sum_before = sum(balanced[u].get(k, 0) for k in u_keys)
                _adjust_leg_to_target(balanced[u], u_keys, raw_volumes.get(u, {}),
                                      u_target, shared_keys=u_shared)
                if sum(balanced[u].get(k, 0) for k in u_keys) != u_sum_before:
                    any_change = True

                # Downstream: leg-row cells. Same shared-cell logic for cols.
                d_target = canonical
                d_keys = spec['approach']
                d_shared = _shared_keys_approach(d, d_keys, d_leg_idx)
                d_sum_before = sum(balanced[d].get(k, 0) for k in d_keys)
                _adjust_leg_to_target(balanced[d], d_keys, raw_volumes.get(d, {}),
                                      d_target, shared_keys=d_shared)
                if sum(balanced[d].get(k, 0) for k in d_keys) != d_sum_before:
                    any_change = True
            if not any_change:
                break

    # ── Final link conservation (post-reconciliation) ───────────────────
    link_conservation = compute_link_conservation(balanced, resolved, link_modes)

    # F2: build a lookup so NCHRP-LINK-DELTA / -LANDUSE-DELTA flags can name
    # the GEOMETRY-FALLBACK they're likely a symptom of. A single coord
    # collision typically corrupts the 4 directed links touching the two
    # ints; surfacing the root prevents the engineer from chasing each delta
    # independently.
    geom_int_to_pair = {}
    for (lo, hi) in geometry_fallbacks:
        geom_int_to_pair[lo] = (lo, hi)
        geom_int_to_pair[hi] = (lo, hi)

    def _geometry_root_hint(entry):
        pair = geom_int_to_pair.get(entry['fromNum']) or geom_int_to_pair.get(entry['toNum'])
        if not pair:
            return ''
        return (f" Likely caused by GEOMETRY-FALLBACK at Int {pair[0]}↔{pair[1]} "
                f"(resolve coords there first).")

    # Flag Full links that still violate conservation (rare — happens when
    # _adjust_leg_to_target can't shrink due to raw-floor constraints).
    LINK_POST_ROUND_TOL = 10.0
    for entry in link_conservation:
        if entry.get('mode') != 'Full':
            continue
        if abs(entry['delta']) > 0.5:
            root = _geometry_root_hint(entry)
            base = (
                f"Link {entry['fromNum']}→{entry['toNum']} {entry['direction']} "
                f"({entry['mode']}): delta {entry['delta']:+.1f} veh post-reconciliation "
                f"— upstream {entry['upstream_outflow']:.0f}, "
                f"downstream {entry['downstream_inflow']:.0f}."
            )
            tail = (root if root
                    else " Likely a raw-floor clipping issue on one of the leg's L/T/R cells.")
            qc_flags.append({
                'check': 'NCHRP-LINK-DELTA',
                'int': entry['fromNum'],
                'message': base + tail,
            })

    # NCHRP-LANDUSE-DELTA: report Land Use link deltas as informational
    for entry in link_conservation:
        if entry.get('mode') != 'Land Use':
            continue
        if abs(entry['delta']) > 0.5:
            root = _geometry_root_hint(entry)
            qc_flags.append({
                'check': 'NCHRP-LANDUSE-DELTA',
                'int': entry['fromNum'],
                'message': (
                    f"Link {entry['fromNum']}→{entry['toNum']} {entry['direction']} "
                    f"(Land Use): downstream {entry['downstream_inflow']:.0f} − "
                    f"upstream {entry['upstream_outflow']:.0f} = "
                    f"{entry['delta']:+.0f} veh land-use delta (expected; counts are "
                    f"intentionally not reconciled on this link)." + root
                ),
            })

    movements_review = compute_movements_review(raw_volumes, balanced)

    return {
        'balanced': balanced,
        'resolved_links': resolved,
        # F7: parallel dict of raw-count pairs that fed each resolved entry.
        # Lets the deliverable surface the engineer-side question "how much did
        # the algorithm smooth?" — a 300-veh discrepancy between upstream and
        # downstream counts that the Larger method silently picked one side of
        # is no longer invisible.
        'raw_link_pairs': raw_link_pairs,
        'link_conservation': link_conservation,
        'movements_review': movements_review,
        'qc_flags': qc_flags,
        'iterations': iterations,
        'converged': converged_map,
        'final_residual': final_residual_map,
        'method': method,
    }
