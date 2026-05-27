"""
DemandIQ — balancing engine.

Extracted from 3_demand_analysis.py and cleaned for use as a web-API module.

Cleanups vs original:
- print() statements removed; functions return data, callers decide what to log.
- CONVERGENCE_THRESHOLD and MAX_ITERATIONS are parameters of balance_corridor()
  (originally module-level constants).
- adjustments and qc flags returned as plain dicts (originally tuples).
- Defensive against intersection nums missing from the vols dict.
- run_qc slimmed to QC-04, QC-05, QC-06, QC-08 — the checks we have data
  for via the web app. QC-01/02/03/07 dropped (they need template-only
  fields like atypical-day flags or prohibited-movement lists).
- run_qc is corridor-direction aware: QC-08 compares EB↔EB / WB↔WB on an
  EB/WB corridor and NB↔NB / SB↔SB on an NB/SB corridor (original was
  hard-coded for EB/WB).
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


# ── Furness balancing ────────────────────────────────────────────────────────
def balance_corridor(
    intersections,
    unbalanced_vols,
    corridor_dir,
    period,
    balance_config=None,
    max_iterations=200,
    convergence_threshold=0.01,
):
    """Furness / Fratar balancing — NCHRP 255 Chapter 8. Balance to Average.

    Args:
        intersections: list of dicts with at least {'num': int}, ordered along
                       the corridor (S2 sort order).
        unbalanced_vols: {int_num: {movement: vol}}
        corridor_dir:  'EB/WB' or 'NB/SB'
        period:        'AM' or 'PM' — used only in returned messages.
        balance_config: optional {(up_num, dn_num): {'mode': 'Full'|'Land Use'|'None',
                                                     'threshold': int}}.
                        Both directions of each link must be present (caller
                        normalizes — endpoint duplicates "1-2" → both (1,2)
                        and (2,1)).
        max_iterations:        cap on Furness iterations.
        convergence_threshold: max relative gap (0..1) for convergence.

    Returns:
        (rounded_volumes, conv_log, adjustments)
            rounded_volumes: {int_num: {movement: rounded_int_vol}}
            conv_log:        [{'iteration': N, 'max_relative_gap': float}, ...]
            adjustments:     [{'iteration': N, 'intersection_num': int,
                              'movement': str, 'delta': float}, ...]
    """
    # Build the directed-link list along the corridor.
    if corridor_dir == 'EB/WB':
        out_in = [('EB', 'EB'), ('WB', 'WB')]
    else:
        out_in = [('NB', 'NB'), ('SB', 'SB')]

    links = []
    for i in range(len(intersections) - 1):
        up = intersections[i]['num']
        dn = intersections[i + 1]['num']
        # First direction follows corridor order; second direction is reverse.
        links.append((up, dn, out_in[0][0], out_in[0][1]))
        links.append((dn, up, out_in[1][0], out_in[1][1]))

    vols = {n: {mv: float(v) for mv, v in mvmt.items()}
            for n, mvmt in unbalanced_vols.items()}
    conv_log = []
    adjustments = []
    bc = balance_config or {}

    for iteration in range(1, max_iterations + 1):
        max_gap = 0.0

        for (up_int, dn_int, out_dir, in_dir) in links:
            # Defensive: skip links where one endpoint has no volume data.
            if up_int not in vols or dn_int not in vols:
                continue

            link_cfg = bc.get((up_int, dn_int), {'mode': 'Full', 'threshold': 0})
            mode = link_cfg.get('mode', 'Full')
            threshold = link_cfg.get('threshold', 0)

            if mode == 'None':
                continue

            out_vol = vols[up_int].get(f'{out_dir}T', 0)
            in_vol = vols[dn_int].get(f'{in_dir}T', 0)
            if out_vol + in_vol == 0:
                continue

            target = (out_vol + in_vol) / 2.0
            gap = abs(out_vol - in_vol) / target if target > 0 else 0

            # Land Use mode: stop balancing this link once within the threshold.
            if mode == 'Land Use' and abs(out_vol - in_vol) <= threshold:
                continue

            max_gap = max(max_gap, gap)
            if gap <= convergence_threshold:
                continue

            # Row scaling — upstream approach.
            up_moves = [mv for mv in MOVEMENTS if mv.startswith(out_dir)]
            if out_vol > 0:
                rf = target / out_vol
                for mv in up_moves:
                    if mv not in vols[up_int]:
                        continue
                    old = vols[up_int][mv]
                    vols[up_int][mv] = old * rf
                    if abs(old - vols[up_int][mv]) > 0.01:
                        adjustments.append({
                            'iteration': iteration,
                            'intersection_num': up_int,
                            'movement': mv,
                            'delta': vols[up_int][mv] - old,
                        })

            # Column scaling — downstream approach.
            dn_moves = [mv for mv in MOVEMENTS if mv.startswith(in_dir)]
            if in_vol > 0:
                cf = target / in_vol
                for mv in dn_moves:
                    if mv not in vols[dn_int]:
                        continue
                    old = vols[dn_int][mv]
                    vols[dn_int][mv] = old * cf
                    if abs(old - vols[dn_int][mv]) > 0.01:
                        adjustments.append({
                            'iteration': iteration,
                            'intersection_num': dn_int,
                            'movement': mv,
                            'delta': vols[dn_int][mv] - old,
                        })

        conv_log.append({'iteration': iteration, 'max_relative_gap': round(max_gap, 6)})
        if max_gap <= convergence_threshold:
            break

    # Round to nearest 5; floor at 5 for any movement with original > 0.
    rounded = {
        n: {
            mv: round_to_5(v, original=unbalanced_vols.get(n, {}).get(mv, 0))
            for mv, v in mvmt.items()
        }
        for n, mvmt in vols.items()
    }
    return rounded, conv_log, adjustments


# ── QC ───────────────────────────────────────────────────────────────────────
def run_qc(intersections, unbalanced_volumes, extracted_meta, balanced, corridor_dir):
    """Slimmed QC — checks we can run from web-app inputs alone.

    Args:
        intersections:        list of {'num': int, 'name': str}
        unbalanced_volumes:   {'AM': {num: {mv: vol}}, 'PM': {...}}
        extracted_meta:       {num: {'AM': {'phf': float, 'hv_pct': float}, 'PM': ...}}
        balanced:             {'AM': {num: {mv: int}}, 'PM': {...}}
        corridor_dir:         'EB/WB' or 'NB/SB'

    Returns: list of {'check', 'int', 'period', 'message'} dicts.
    """
    flags = []

    for inter in intersections:
        n = inter['num']

        for period in ['AM', 'PM']:
            meta = extracted_meta.get(n, {}).get(period, {}) or {}
            vols = unbalanced_volumes.get(period, {}).get(n, {}) or {}

            # QC-04: HV% > 15%
            hv = meta.get('hv_pct')
            if hv is not None and hv > 15:
                flags.append({
                    'check': 'QC-04', 'int': n, 'period': period,
                    'message': f"Int {n} {period}: HV% = {hv:.1f}% > 15%",
                })

            # QC-05: PHF out of range
            phf = meta.get('phf')
            if phf is not None and (phf < 0.60 or phf > 1.00):
                flags.append({
                    'check': 'QC-05', 'int': n, 'period': period,
                    'message': f"Int {n} {period}: PHF = {phf:.4f} out of range",
                })

            # QC-06: Zero approach volume on any LTR direction
            for direction in ['NB', 'SB', 'EB', 'WB']:
                dir_total = sum(vols.get(f'{direction}{m}', 0) for m in ['L', 'T', 'R'])
                if dir_total == 0:
                    flags.append({
                        'check': 'QC-06', 'int': n, 'period': period,
                        'message': f"Int {n} {period}: {direction} approach is zero — verify if stub",
                    })

    # QC-08: post-balance residual gap on through movements between consecutive ints.
    if corridor_dir == 'EB/WB':
        out_dir, in_dir = 'EB', 'WB'
    else:
        out_dir, in_dir = 'NB', 'SB'

    sorted_ints = sorted(intersections, key=lambda x: x['num'])
    for period in ['AM', 'PM']:
        bal = balanced.get(period, {})
        if not bal:
            continue
        for i in range(len(sorted_ints) - 1):
            up = sorted_ints[i]['num']
            dn = sorted_ints[i + 1]['num']
            if up not in bal or dn not in bal:
                continue
            out_gap = abs(bal[up].get(f'{out_dir}T', 0) - bal[dn].get(f'{out_dir}T', 0))
            in_gap = abs(bal[dn].get(f'{in_dir}T', 0) - bal[up].get(f'{in_dir}T', 0))
            if out_gap > 5:
                flags.append({
                    'check': 'QC-08', 'int': up, 'period': period,
                    'message': f"Int {up}→{dn} {period} {out_dir}: residual gap {out_gap} veh after balancing",
                })
            if in_gap > 5:
                flags.append({
                    'check': 'QC-08', 'int': dn, 'period': period,
                    'message': f"Int {dn}→{up} {period} {in_dir}: residual gap {in_gap} veh after balancing",
                })

    return flags


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3a: network-aware solver (ported from balancer_reference.py)
#
# This sits ALONGSIDE balance_corridor + run_qc above. The old single-corridor
# /balance endpoint keeps calling those. The new /balance-network endpoint
# calls balance_network() below. Both modes (conservative + furness) are
# ported here for a clean Stage 3b seam — but only Furness is exposed via
# the toggle in Stage 3a per the build sequencing.
# ──────────────────────────────────────────────────────────────────────────────

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


def _outflow(m, dirn):
    s = DIRECTION_SPEC[dirn]
    return sum(m.get(k, 0) for k in s['outflow']) + m.get(s['outflow_u'], 0)


def _approach(m, dirn):
    s = DIRECTION_SPEC[dirn]
    return sum(m.get(k, 0) for k in s['approach'])


def _link_delta(up, dn, dirn):
    """downstream approach minus upstream outflow. Zero = balanced."""
    return _approach(dn, dirn) - _outflow(up, dirn)


def _adjust_conservative(v, u, d, dirn, tol):
    """DEPRECATED Stage 3a/3b link-by-link adjustment (cascade-prone on real
    networks — see /tmp/balance_trace.log diagnostic from 2026-05-27).
    Kept so /balance-network keeps returning 200 for one cycle while the
    frontend migrates to /balance-nchrp. Do not call from new code."""
    delta = _link_delta(v[u], v[d], dirn)
    if abs(delta) < tol:
        return
    s = DIRECTION_SPEC[dirn]
    if delta > 0:
        tot = _outflow(v[u], dirn)
        if tot <= 0:
            return
        for k in s['outflow']:
            v[u][k] += delta * (v[u][k] / tot)
    else:
        tot = _approach(v[d], dirn)
        if tot <= 0:
            return
        for k in s['approach']:
            v[d][k] += abs(delta) * (v[d][k] / tot)


def _adjust_furness(v, u, d, dirn, tol):
    """Move both sides toward their average. No floor. NCHRP 255 proportional
    balancing. Ported verbatim from balancer_reference.py."""
    s = DIRECTION_SPEC[dirn]
    o = _outflow(v[u], dirn)
    a = _approach(v[d], dirn)
    if abs(a - o) < tol:
        return
    target = (o + a) / 2
    if o > 0:
        f = target / o
        for k in s['outflow']:
            v[u][k] *= f
    if a > 0:
        f = target / a
        for k in s['approach']:
            v[d][k] *= f


def _round_up_5(x):
    """Round UP to next multiple of 5, except exact-0 stays 0."""
    if abs(x) < 1e-9:
        return 0
    import math
    return int(math.ceil(x / 5.0) * 5)


def _round_and_reconcile(v, links_dir, adjust_fn, tol):
    """Round every value up to next 5 (0 stays 0), then ONE reconciliation
    pass so rounding doesn't leave small residual deltas, then re-round."""
    for i in v:
        for k in v[i]:
            v[i][k] = _round_up_5(v[i][k])
    for u, d, dn in links_dir:
        adjust_fn(v, u, d, dn, tol)
    for i in v:
        for k in v[i]:
            v[i][k] = _round_up_5(v[i][k])
    return v


def detect_chains(links_dir):
    """Group links into chains. Two links are in the same chain iff they share
    an intersection AND have the same direction. A shared intersection
    participates in multiple chains independently (one per direction).

    Implementation: per-direction union-find over node ids.

    Returns: list of dicts, one per chain:
        { 'id': 'chain_eb_0', 'direction': 'EB',
          'intersections': [sorted node ids],
          'edges': [(u, d, direction), ...] }
    """
    from collections import defaultdict

    # Index edges by direction
    by_dir = defaultdict(list)
    for u, d, dn in links_dir:
        by_dir[dn].append((u, d))

    chains = []
    for dn in sorted(by_dir.keys()):           # deterministic order
        edges = by_dir[dn]
        parent = {}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for u, d in edges:
            if u not in parent: parent[u] = u
            if d not in parent: parent[d] = d
            union(u, d)

        comp_nodes = defaultdict(set)
        comp_edges = defaultdict(list)
        for u, d in edges:
            r = find(u)
            comp_nodes[r].add(u)
            comp_nodes[r].add(d)
            comp_edges[r].append((u, d, dn))

        for idx, r in enumerate(sorted(comp_nodes.keys(), key=lambda x: (str(type(x)), x))):
            chains.append({
                'id': f'chain_{dn.lower()}_{idx}',
                'direction': dn,
                'intersections': sorted(comp_nodes[r], key=lambda x: (str(type(x)), x)),
                'edges': comp_edges[r],
            })
    return chains


def balance_network(
    raw_volumes,
    links_dir,
    mode='furness',
    max_iter=500,
    tol=1e-6,
    round_final=True,
):
    """DEPRECATED: link-by-link Gauss-Seidel balancer (Stage 3a/3b).

    Cascade-prone on real corridors — see /tmp/balance_trace.log from
    2026-05-27 showing EBT 1000→1290 / WBT 750→1600 on Bodger AM. Both
    modes (furness, conservative) are the same homemade per-link
    adjustment under the hood and share the same iteration-order
    amplification bug; neither is actually NCHRP. Use balance_nchrp()
    below for new work — that does real NCHRP 255/765 turning-movement
    refinement via per-intersection Fratar factoring.

    This function stays around so /balance-network keeps responding for
    backward compat through one cycle. Slated for removal after S6 cuts
    over to /balance-nchrp.

    --- Original docstring follows ---

    Shared solver scaffolding for both modes (spec §6, §9).

    Args:
        raw_volumes: { int_id: { movement: float } } — full precision input.
        links_dir:   [(upstream_id, downstream_id, direction), ...]
                     Direction is 'EB' | 'WB' | 'NB' | 'SB'.
        mode:        'conservative' | 'furness' — Stage 3a wires Furness only
                     from the endpoint, but both adjustment fns are present.
        max_iter:    iteration cap.
        tol:         convergence tolerance (absolute, on link_delta in vehicles).
        round_final: round up to next 5 + one reconciliation pass.

    Returns:
        {
          'balanced': { int_id: { movement: number } },
          'chains':   [{ id, direction, intersections, iterations, converged,
                         final_max_delta, log: [{iteration, max_delta}] }],
          'iterations': global iters_used,
          'converged': True iff ALL chains converged,
          'final_max_delta': max across all links,
          'mode': mode,
        }

    The solver walks EVERY link each iteration (spec §6: global convergence
    loop catches cross-direction shared-movement interference). Per-chain
    final_max_delta is computed from that chain's edges only.
    """
    import copy
    v = copy.deepcopy(raw_volumes)

    # Pre-fill any intersection referenced by a link but missing from
    # raw_volumes with all-zero movements. Real cause: a project may have
    # links + AM volumes but no PM data yet — the empty period would
    # otherwise raise KeyError in chain_max_delta. With zeros, both sides
    # are 0, _adjust_* short-circuits via the `if o > 0` guard, and the
    # output reports the link as already balanced.
    referenced = set()
    for u, d, _dn in links_dir:
        referenced.add(u); referenced.add(d)
    ZERO_MOVES = {k: 0.0 for k in (
        'EBL','EBT','EBR','EBU', 'WBL','WBT','WBR','WBU',
        'NBL','NBT','NBR','NBU', 'SBL','SBT','SBR','SBU'
    )}
    for n in referenced:
        if n not in v:
            v[n] = dict(ZERO_MOVES)

    adjust = _adjust_conservative if mode == 'conservative' else _adjust_furness
    chains = detect_chains(links_dir)

    def chain_max_delta(chain):
        return max(
            (abs(_link_delta(v[u], v[d], dn)) for u, d, dn in chain['edges']),
            default=0.0,
        )

    def global_max_delta():
        return max(
            (abs(_link_delta(v[u], v[d], dn)) for u, d, dn in links_dir),
            default=0.0,
        )

    # Per-chain iteration log: [{'iteration': N, 'max_delta': float}, ...]
    chain_logs = {c['id']: [] for c in chains}

    iters_used = 0
    converged = False
    for it in range(max_iter):
        # Pre-iter snapshot of per-chain max delta (so log[0] is the starting state)
        for c in chains:
            chain_logs[c['id']].append({
                'iteration': it,
                'max_delta': chain_max_delta(c),
            })

        if global_max_delta() < tol:
            converged = True
            iters_used = it
            break

        for u, d, dn in links_dir:
            adjust(v, u, d, dn, tol)
        iters_used = it + 1

    # Capture pre-rounding convergence per chain — that's the algorithm's real
    # answer. Post-rounding can introduce small residuals (a few veh per link)
    # that are expected and acceptable; we report them separately.
    pre_round_chain_delta = {c['id']: chain_max_delta(c) for c in chains}

    if round_final and len(links_dir) > 0:
        v = _round_and_reconcile(v, links_dir, adjust, tol)

    chain_results = []
    for c in chains:
        pre = pre_round_chain_delta[c['id']]
        post = chain_max_delta(c)
        chain_results.append({
            'id': c['id'],
            'direction': c['direction'],
            'intersections': c['intersections'],
            'iterations': iters_used,
            'converged': pre < tol,                    # algorithm convergence
            'final_max_delta': pre,                    # pre-round (true result)
            'post_round_max_delta': post,              # informational
            'log': chain_logs[c['id']],
        })

    return {
        'balanced': v,
        'chains': chain_results,
        'iterations': iters_used,
        'converged': all(c['converged'] for c in chain_results),
        'final_max_delta': max(pre_round_chain_delta.values(), default=0.0),
        'mode': mode,
    }


def network_qc_flags(intersections, links_dir, balanced):
    """Per spec §6: orphan intersections (no links) pass through unchanged AND
    get a QC flag. Returns a list of {'check', 'int', 'message'} dicts."""
    linked = set()
    for u, d, _dn in links_dir:
        linked.add(u)
        linked.add(d)
    flags = []
    for it in intersections:
        n = it.get('num')
        if n is None:
            continue
        if n not in linked:
            flags.append({
                'check': 'NB-01',
                'int': n,
                'message': f"Int {n} has no links — not balanced (orphan)",
            })
    return flags


# ══════════════════════════════════════════════════════════════════════════════
# Stage 4 / NCHRP rewrite: real per-intersection Fratar factoring.
#
# Replaces the link-by-link Gauss-Seidel scheme above (which has a cascade
# bug — see deprecation notice on balance_network). This is NCHRP 255/765
# turning-movement refinement: each intersection's 4×4 O-D matrix is
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
LEG_INDEX  = {'S': 0, 'N': 1, 'W': 2, 'E': 3}    # leg name → row/col index
LEG_IN_DIR  = {0: 'NB', 1: 'SB', 2: 'EB', 3: 'WB'}   # cars entering via leg
LEG_OUT_DIR = {0: 'SB', 1: 'NB', 2: 'WB', 3: 'EB'}   # cars exiting via leg


def resolve_link_volumes(volumes, links, method='larger', coords=None):
    """STEP A — collapse two adjacent intersection counts on the same link
    into ONE resolved volume per directed edge.

    Args:
        volumes: { int_num: { movement: value } }
        links:   [{ 'fromNum': int, 'toNum': int, 'direction': 'EB/WB'|'NB/SB' }]
        method:  'larger' (default) or 'average'
        coords:  { int_num: {'lat': float, 'lng': float} } — optional but
                 strongly recommended. Without coords, num-order is used as a
                 fallback geographic ordering (assumes lower num is west/south).

    Returns:
        { (upstream_num, downstream_num, dir_code): resolved_volume }
        where dir_code is one of 'EB' | 'WB' | 'NB' | 'SB'.
        EB direction has west→east upstream/downstream; SB has north→south.

    Stores BOTH directions of each link (an EB/WB link produces two entries:
    one EB, one WB).
    """
    coords = coords or {}
    out = {}
    for L in links:
        a, b = int(L['fromNum']), int(L['toNum'])
        axis = L.get('direction')
        if axis == 'EB/WB':
            # Determine which is west by longitude (or fallback: smaller num is west)
            a_lng = coords.get(a, {}).get('lng')
            b_lng = coords.get(b, {}).get('lng')
            if a_lng is not None and b_lng is not None:
                west, east = (a, b) if a_lng < b_lng else (b, a)
            else:
                west, east = (a, b) if a < b else (b, a)
            for dir_code, up, dn in (('EB', west, east), ('WB', east, west)):
                up_vols = volumes.get(up, {})
                dn_vols = volumes.get(dn, {})
                count_up = sum(up_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['outflow'])
                count_dn = sum(dn_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['approach'])
                resolved = max(count_up, count_dn) if method == 'larger' else (count_up + count_dn) / 2.0
                out[(up, dn, dir_code)] = float(resolved)
        elif axis == 'NB/SB':
            a_lat = coords.get(a, {}).get('lat')
            b_lat = coords.get(b, {}).get('lat')
            if a_lat is not None and b_lat is not None:
                south, north = (a, b) if a_lat < b_lat else (b, a)
            else:
                south, north = (a, b) if a < b else (b, a)
            for dir_code, up, dn in (('NB', south, north), ('SB', north, south)):
                up_vols = volumes.get(up, {})
                dn_vols = volumes.get(dn, {})
                count_up = sum(up_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['outflow'])
                count_dn = sum(dn_vols.get(k, 0) for k in DIRECTION_SPEC[dir_code]['approach'])
                resolved = max(count_up, count_dn) if method == 'larger' else (count_up + count_dn) / 2.0
                out[(up, dn, dir_code)] = float(resolved)
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


def compute_link_conservation(balanced, resolved_links):
    """For every directed link, compute upstream outflow vs downstream inflow
    on the BALANCED matrix and the resulting delta.

    Stage 4c.1: the real engineering question after balancing is "does
    upstream outflow == downstream inflow on every link?" — NOT "what's the
    internal IPF residual at each intersection." This function answers the
    former.

    Args:
        balanced:        { int_num: { movement: value } } (post-round-up-5)
        resolved_links:  { (u, d, direction): float } — only used for the
                         key set; resolved volumes are NOT compared (we want
                         the actual conservation on the balanced result, not
                         conformance to the link target).

    Returns:
        [
          {
            'fromNum': int, 'toNum': int, 'direction': 'EB'|'WB'|'NB'|'SB',
            'upstream_outflow': float, 'downstream_inflow': float, 'delta': float,
          },
          ...
        ]
    where delta = downstream_inflow - upstream_outflow. Zero = perfectly
    conserved. Small nonzero values (≤ few veh) can come from round-up-to-5
    on different sides of the link; that's expected and surfaced honestly.
    """
    out = []
    for (u, d, direction) in sorted(resolved_links.keys()):
        u_vols = balanced.get(u, {})
        d_vols = balanced.get(d, {})
        # Outflow = through + 2 turns + U-turn (per DIRECTION_SPEC)
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
        })
    return out


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

    # Step A: resolve link disagreements
    resolved = resolve_link_volumes(raw_volumes, links, method=method, coords=coords)
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

    # Step D: round up to next 5
    if round_to_5:
        for int_num, balanced_vols in balanced.items():
            raw = raw_volumes.get(int_num, {})
            for mv in list(balanced_vols.keys()):
                balanced_vols[mv] = _round_up_5_nchrp(balanced_vols[mv], raw.get(mv))

    # Stage 4c.2: compute link conservation on the ROUNDED balanced output.
    # Two-level Furness gets pre-round deltas near zero EXCEPT at thin-matrix
    # intersections (single-cell legs from structural zeros), which can leave
    # 5-15 veh structural residuals that no leg-total IPF can eliminate.
    # Round-up-to-5 adds another ~5 veh per side. Flag threshold of 10 veh
    # surfaces engineering-meaningful discrepancies without flooding on
    # structural artifacts.
    LINK_POST_ROUND_TOL = 10.0
    link_conservation = compute_link_conservation(balanced, resolved)
    for entry in link_conservation:
        if abs(entry['delta']) > LINK_POST_ROUND_TOL:
            qc_flags.append({
                'check': 'NCHRP-LINK-DELTA',
                'int': entry['fromNum'],
                'message': (
                    f"Link {entry['fromNum']}→{entry['toNum']} {entry['direction']}: "
                    f"delta {entry['delta']:+.1f} veh — "
                    f"upstream outflow {entry['upstream_outflow']:.0f}, "
                    f"downstream inflow {entry['downstream_inflow']:.0f}."
                ),
            })

    return {
        'balanced': balanced,
        'resolved_links': resolved,
        'link_conservation': link_conservation,
        'qc_flags': qc_flags,
        'iterations': iterations,
        'converged': converged_map,
        'final_residual': final_residual_map,
        'method': method,
    }
