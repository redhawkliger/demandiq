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
    """Raise whichever side is LOWER up to the higher, distributing the delta
    proportional to each movement's share. Only ever ADDS → floor is automatic.
    Ported verbatim from balancer_reference.py.

    NOTE: Stage 3a leaves the S5 toggle wired to Furness only. This function
    exists so Stage 3b only needs to flip the toggle and verify hand-worked
    Conservative numbers — no algorithmic work."""
    delta = _link_delta(v[u], v[d], dirn)
    if abs(delta) < tol:
        return
    s = DIRECTION_SPEC[dirn]
    if delta > 0:
        # downstream wants more than upstream sends → raise UPSTREAM outflow feeders
        tot = _outflow(v[u], dirn)
        if tot <= 0:
            return
        for k in s['outflow']:                     # U-turn excluded from receiving
            v[u][k] += delta * (v[u][k] / tot)
    else:
        # upstream sends more than downstream takes → raise DOWNSTREAM approach moves
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
    """Shared solver scaffolding for both modes (spec §6, §9).

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
