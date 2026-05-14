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
