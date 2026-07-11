"""Grader — deterministic verdict library. The LLM never runs in here.

Tier 1 (hard invariants — any failure is a FAIL regardless of accuracy):
  T1-convergence   every intersection's `converged` flag is true, AM and PM
  T1-conservation  recomputed |downstream inflow − upstream outflow| ≤ 0.5 veh
                   on every Full link the tool itself resolved
  T1-phantom       no positive balanced movement on a leg with no raw demand
  T1-floor         no balanced movement in the open interval (0, 5)

Tier 2 (accuracy vs the answer key): GEH per standard movement, both periods.
  PASS all ≤ 5 · MARGINAL all ≤ 10 · FAIL any > 10.

Probe results (telemetry truthfulness, idempotency, S8 export, orientation
sweep) are folded in as additional hard checks. The verdict and category are
decided ENTIRELY here, in code; the narrator only explains afterwards.
"""

import hashlib
import json

from . import nchrp_math as nm

GEH_PASS = 5.0
GEH_MARGINAL = 10.0
CONSERVATION_TOL_VEH = 0.5

# Worst-first category precedence: a run's failure_category is the highest-
# ranked category among its failed checks.
CATEGORY_ORDER = (
    'pipeline-crash',
    'input/schema',
    'phantom-movement',
    'floor-violation',
    'convergence',
    'conservation',
    'unknown',
    'accuracy-drift',
)

_PROBE_CATEGORY = {
    'telemetry-truthfulness': 'unknown',   # narrator refines per spec
    'idempotency': 'unknown',
    's8-export': 'unknown',
    'orientation-sweep': 'unknown',
}


def _check(name, category, ok, details):
    return {'check': name, 'category': category, 'ok': ok,
            'details': details[:40]}


def check_convergence(tool_output, key_by_num):
    """Every intersection in the answer key must be REPORTED converged — an
    under-reporting response (missing ints, empty map) is a failure, not a
    vacuous pass."""
    details = []
    for period in ('AM', 'PM'):
        conv = (tool_output.get('converged') or {}).get(period) or {}
        for n_str in sorted(key_by_num.get(period) or {}, key=int):
            if n_str not in conv:
                details.append(f'{period} int {n_str}: missing from the '
                               f"response's converged map")
            elif not conv[n_str]:
                iters = ((tool_output.get('iterations') or {})
                         .get(period, {}).get(n_str))
                details.append(f'{period} int {n_str}: converged=false '
                               f'(iterations={iters})')
    return _check('T1-convergence', 'convergence', not details, details)


def check_conservation(tool_output, expected_pairs=None):
    """Recompute conservation on every Full link the tool resolved, from the
    tool's own balanced volumes — the tool's resolved targets, our math.

    `expected_pairs` (optional): list of unordered (a, b) intersection-num
    pairs the corridor is configured with. Each must appear as exactly two
    directed link_conservation entries per period — a response that silently
    drops the section (or individual links) fails instead of passing
    vacuously."""
    details = []
    balanced = tool_output.get('balanced') or {}
    for period in ('AM', 'PM'):
        entries = (tool_output.get('link_conservation') or {}).get(period) or []
        for (a, b) in expected_pairs or []:
            n_dir = sum(1 for e in entries
                        if {e['fromNum'], e['toNum']} == {a, b})
            if n_dir != 2:
                details.append(
                    f'{period} link {a}↔{b}: expected 2 directed '
                    f'link_conservation entries, response has {n_dir}')
        bal = {int(n): v for n, v in (balanced.get(period) or {}).items()}
        for entry in entries:
            if entry.get('mode') != 'Full':
                continue
            mine = nm.link_conservation_entry(
                bal, entry['fromNum'], entry['toNum'], entry['direction'])
            if abs(mine['delta']) > CONSERVATION_TOL_VEH:
                details.append(
                    f"{period} link {entry['fromNum']}→{entry['toNum']} "
                    f"{entry['direction']} (Full): recomputed delta "
                    f"{mine['delta']:+.1f} veh (outflow "
                    f"{mine['upstream_outflow']:.0f}, inflow "
                    f"{mine['downstream_inflow']:.0f})")
    return _check('T1-conservation', 'conservation', not details, details)


def check_phantom(raw_by_period, tool_output):
    """No positive balanced movement may sit on a leg with zero raw demand."""
    details = []
    balanced = tool_output.get('balanced') or {}
    for period in ('AM', 'PM'):
        raw_p = raw_by_period.get(period) or {}
        for n_str, bvols in sorted((balanced.get(period) or {}).items(), key=lambda kv: int(kv[0])):
            present = nm.raw_legs_present(raw_p.get(n_str, {}))
            for mv, val in sorted(bvols.items()):
                if mv not in nm.MOVEMENT_LEGS or not val or val <= 0:
                    continue
                a_leg, e_leg = nm.MOVEMENT_LEGS[mv]
                missing = [leg for leg in (a_leg, e_leg) if leg not in present]
                if missing:
                    details.append(
                        f'{period} int {n_str}: balanced {mv}={val} on absent '
                        f'leg(s) {"/".join(missing)}')
    return _check('T1-phantom', 'phantom-movement', not details, details)


def check_floor(tool_output):
    details = []
    balanced = tool_output.get('balanced') or {}
    for period in ('AM', 'PM'):
        for n_str, bvols in sorted((balanced.get(period) or {}).items(), key=lambda kv: int(kv[0])):
            for mv, val in sorted(bvols.items()):
                if val is not None and 0 < val < 5:
                    details.append(f'{period} int {n_str}: balanced {mv}={val} '
                                   f'is below the 5-veh floor')
    return _check('T1-floor', 'floor-violation', not details, details)


def grade_geh(key_by_num, tool_output):
    """Tier 2: GEH per standard movement vs the answer key, both periods.
    Returns (rows ranked worst-first, worst row or None)."""
    rows = []
    balanced = tool_output.get('balanced') or {}
    for period in ('AM', 'PM'):
        key_p = key_by_num.get(period) or {}
        bal_p = balanced.get(period) or {}
        for n_str in sorted(key_p, key=int):
            bvols = bal_p.get(n_str) or {}
            for mv in nm.STANDARD_MOVEMENTS:
                c = key_p[n_str].get(mv)
                if c is None:
                    continue
                m = bvols.get(mv, 0) or 0
                rows.append({
                    'period': period, 'int_num': int(n_str), 'movement': mv,
                    'key': c, 'tool': m, 'geh': round(nm.geh(m, c), 4),
                })
    rows.sort(key=lambda r: (-r['geh'], r['period'], r['int_num'], r['movement']))
    return rows, (rows[0] if rows else None)


def grade(key_by_num, raw_by_period, tool_output, probe_results,
          expected_pairs=None):
    """Full deterministic grade. Returns the grade dict (verdict, category,
    checks, geh table, signature)."""
    checks = [
        check_convergence(tool_output, key_by_num),
        check_conservation(tool_output, expected_pairs),
        check_phantom(raw_by_period, tool_output),
        check_floor(tool_output),
    ]
    for p in probe_results:
        checks.append(_check(f"probe-{p['probe']}", _PROBE_CATEGORY[p['probe']],
                             p['ok'], p['details']))

    geh_rows, worst = grade_geh(key_by_num, tool_output)
    geh_fail = [r for r in geh_rows if r['geh'] > GEH_MARGINAL]
    geh_marginal = [r for r in geh_rows if GEH_PASS < r['geh'] <= GEH_MARGINAL]
    checks.append(_check(
        'T2-geh', 'accuracy-drift', not geh_fail,
        [f"{r['period']} int {r['int_num']} {r['movement']}: "
         f"key={r['key']} tool={r['tool']} GEH={r['geh']:.2f}"
         for r in geh_fail]))

    failed = [c for c in checks if not c['ok']]
    if failed:
        verdict = 'FAIL'
        category = min((c['category'] for c in failed),
                       key=CATEGORY_ORDER.index)
    elif geh_marginal:
        verdict = 'MARGINAL'
        category = 'accuracy-drift'
    else:
        verdict = 'PASS'
        category = None

    return {
        'verdict': verdict,
        'failure_category': category,
        'checks': checks,
        'geh': {
            'worst': worst['geh'] if worst else 0.0,
            'worst_movement': (f"{worst['period']} int {worst['int_num']} "
                               f"{worst['movement']}") if worst else '',
            'n_over_marginal': len(geh_fail),
            'n_marginal': len(geh_marginal),
            'rows': geh_rows,
        },
        'signature': compute_signature(category, failed, geh_fail),
    }


def compute_signature(category, failed_checks, geh_fail_rows):
    """Deterministic hash of the failure SHAPE — category + which checks
    failed + which movement codes / link directions are involved — but NOT
    seed-specific values (int nums, volumes), so the same bug hit by 300
    seeds dedups to one ledger row."""
    if category is None:
        return ''
    shape = {
        'category': category,
        'checks': sorted(c['check'] for c in failed_checks),
        'movements': sorted({r['movement'] for r in geh_fail_rows}),
    }
    blob = json.dumps(shape, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:12]
