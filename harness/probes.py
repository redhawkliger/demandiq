"""Probes — deterministic cross-checks run on every cycle. No LLM anywhere.

Each probe returns {'probe': str, 'ok': bool, 'details': [...]} — details are
human-readable strings pinpointing the first mismatches (capped, never empty
on failure). The Grader folds probe failures into the verdict.

Telemetry-truthfulness scope note: the endpoint's `final_residual` is
computed INSIDE the solver from its pre-rounding IPF matrix against Level-1
leg targets that are not part of the response, so it cannot be recomputed
from the response alone without re-running the tool's own code (which would
verify nothing). What IS independently recomputable from (puzzle, response)
is checked exactly instead:
  - link_conservation: upstream/downstream/delta from the balanced volumes
  - movements_review: raw/balanced/delta per movement from puzzle + balanced
Both are solver-reported telemetry that downstream views (S6/S7) trust.
"""

from . import nchrp_math as nm

EPS = 1e-6

# standard L/T/R enumeration order used by the tool's movements_review
_REVIEW_ORDER = (
    'EBL', 'EBT', 'EBR',
    'WBL', 'WBT', 'WBR',
    'NBL', 'NBT', 'NBR',
    'SBL', 'SBT', 'SBR',
)


def _raw_by_num(project, period):
    """Puzzle raw volumes, keyed by str(num), bare numbers (UI strip path)."""
    out = {}
    for it in project.get('intersections') or []:
        cells = (it.get('volumes') or {}).get(period) or {}
        vals = {mv: c['value'] for mv, c in cells.items()
                if (c or {}).get('value') not in (None, '')}
        if vals:
            out[str(it['num'])] = vals
    return out


def probe_telemetry_truthfulness(project, tool_output):
    """Recompute link_conservation + movements_review from the response's own
    balanced volumes (and the puzzle's raw counts); compare to what the tool
    REPORTED. Any mismatch means the telemetry lies about the volumes."""
    details = []
    balanced = tool_output.get('balanced') or {}

    for period in ('AM', 'PM'):
        bal = {int(n): v for n, v in (balanced.get(period) or {}).items()}

        # link_conservation: recompute each reported entry's numbers
        for entry in (tool_output.get('link_conservation') or {}).get(period) or []:
            mine = nm.link_conservation_entry(
                bal, entry['fromNum'], entry['toNum'], entry['direction'])
            for field in ('upstream_outflow', 'downstream_inflow', 'delta'):
                if abs(mine[field] - float(entry[field])) > EPS:
                    details.append(
                        f"{period} link {entry['fromNum']}→{entry['toNum']} "
                        f"{entry['direction']}: reported {field}="
                        f"{entry[field]}, recomputed {mine[field]:.6f}")

        # movements_review: recompute the full list
        raw = _raw_by_num(project, period)
        expected = []
        for n_str in sorted(raw, key=int):
            b = balanced.get(period, {}).get(n_str) or {}
            for mv in _REVIEW_ORDER:
                r = int(raw[n_str].get(mv, 0) or 0)
                if r <= 0:
                    continue
                bv = int(b.get(mv, 0) or 0)
                expected.append({'int_num': int(n_str), 'movement': mv,
                                 'raw': r, 'balanced': bv, 'delta': bv - r})
        reported = (tool_output.get('movements_review') or {}).get(period) or []
        if reported != expected:
            rep = {(e['int_num'], e['movement']): e for e in reported}
            exp = {(e['int_num'], e['movement']): e for e in expected}
            for k in sorted(set(rep) | set(exp)):
                if rep.get(k) != exp.get(k):
                    details.append(
                        f'{period} movements_review int {k[0]} {k[1]}: '
                        f'reported {rep.get(k)}, recomputed {exp.get(k)}')
                    if len(details) > 40:
                        break

    return {'probe': 'telemetry-truthfulness', 'ok': not details,
            'details': details[:40]}


def probe_idempotency(first_raw, second_raw):
    """Balance the same puzzle twice; the raw response bytes must be
    identical. (The orchestrator makes both calls; this just compares.)"""
    ok = first_raw == second_raw
    details = [] if ok else [
        f'two identical /balance-nchrp POSTs returned different bytes '
        f'(lengths {len(first_raw)} vs {len(second_raw)})']
    return {'probe': 'idempotency', 'ok': ok, 'details': details}


def probe_s8_export(diagram_response, n_links):
    """The corridor-diagram export must return real image payloads for both
    periods, and — when the corridor has links — draw at least one segment."""
    import base64
    details = []
    for period_key in ('am', 'pm'):
        img = (diagram_response or {}).get(period_key) or {}
        b64 = img.get('png_base64') or ''
        if not b64:
            details.append(f'{period_key}: empty/missing png_base64')
            continue
        try:
            blob = base64.b64decode(b64)
        except Exception as e:
            details.append(f'{period_key}: png_base64 not decodable: {e}')
            continue
        if not blob.startswith(b'\x89PNG'):
            details.append(f'{period_key}: payload is not a PNG ({blob[:8]!r})')
    if n_links > 0:
        counts = (diagram_response or {}).get('segment_counts') or {}
        for period in ('AM', 'PM'):
            if not counts.get(period):
                details.append(
                    f'{period}: segment_counts={counts.get(period)} with '
                    f'{n_links} links configured — no segment labels drawn')
    return {'probe': 's8-export', 'ok': not details, 'details': details}


def probe_orientation_equivalence(balanced_ew, balanced_ns, rotate):
    """The same corridor run as E–W and as N–S must produce identical
    balanced volumes under the 90° movement-code rotation. `rotate` is the
    EW→NS movement mapping (a pure code mapping, from the Puzzler)."""
    details = []
    for period in ('AM', 'PM'):
        ew = (balanced_ew or {}).get(period) or {}
        ns = (balanced_ns or {}).get(period) or {}
        if set(ew) != set(ns):
            details.append(f'{period}: intersection sets differ: '
                           f'{sorted(ew)} vs {sorted(ns)}')
            continue
        for n_str in sorted(ew, key=int):
            mapped = rotate(ew[n_str])
            for mv in sorted(set(mapped) | set(ns[n_str])):
                a, b = mapped.get(mv), ns[n_str].get(mv)
                if a != b:
                    details.append(
                        f'{period} int {n_str} {mv}: EW-rotated={a}, NS={b}')
                    if len(details) > 40:
                        break
    return {'probe': 'orientation-sweep', 'ok': not details,
            'details': details[:40]}
