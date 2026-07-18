"""Forger Grader — deterministic per-movement error taxonomy. No LLM.

Per movement, classify the extraction against the answer key:

  CORRECT            right value at the right movement code
  DIGIT-ERR          wrong value at the right code, within ±DIGIT_DELTA or
                     digit edit distance ≤ 1 (misread digits)
  MAP-ERR            the TRUE value of movement X appears at movement Y —
                     the mis-mapping disease. Sub-patterns: NS-FLIP,
                     EW-FLIP, LTR-SHIFT (same approach, shifted turn slot),
                     OTHER-SWAP
  TOTAL-AS-MOVEMENT  an approach-total or grand-total value in a movement slot
  OMISSION           true > 0 extracted as missing/0
  HALLUCINATION      a value matching nothing on the sheet (incl. nonzero
                     U-turns — the Forger never places U-turn volumes)

Exact-value matching is sound because the Forger generates all 17 numbers
per period (12 movements + 4 approach totals + grand total) pairwise >10
apart — an exact match to another slot can never also be within the
DIGIT-ERR window of the true value.

Sheet-level: intersection-total ratio (extracted/true — the 2.2× symptom)
per period, and one verdict:
  PASS         every movement CORRECT (both periods)
  DIGIT-ONLY   errors are exclusively DIGIT-ERR
  MAP-FAIL     errors are exclusively mapping-class (MAP-ERR / TOTAL-AS-MOVEMENT)
  MIXED        anything else
  CRASH        extraction failed / unparseable / no intersections

Signatures: sha256 of (style, sorted error classes, sorted MAP sub-patterns)
truncated to 12 hex — same dedup discipline as the Examiner: the same
failure shape across many seeds is one ledger row; seed-specific values
never enter the hash.
"""

import hashlib
import json

from .sheets import APPROACHES, MOVEMENTS_12

DIGIT_DELTA = 10
U_TURNS = ('EBU', 'WBU', 'NBU', 'SBU')

_FLIP_NS = {'NB': 'SB', 'SB': 'NB'}
_FLIP_EW = {'EB': 'WB', 'WB': 'EB'}


def _digit_edit_distance(a, b):
    """Levenshtein distance between two digit strings (tiny inputs)."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _as_int(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _map_subpattern(true_mv, source_mv):
    """Which mis-mapping pattern moved source_mv's value into true_mv's slot."""
    ap_t, turn_t = true_mv[:2], true_mv[2]
    ap_s, turn_s = source_mv[:2], source_mv[2]
    if ap_s == _FLIP_NS.get(ap_t) and turn_s == turn_t:
        return 'NS-FLIP'
    if ap_s == _FLIP_EW.get(ap_t) and turn_s == turn_t:
        return 'EW-FLIP'
    if ap_s == ap_t and turn_s != turn_t:
        return 'LTR-SHIFT'
    return 'OTHER-SWAP'


def classify_period(true_vols, extracted_vols, approach_totals, grand_total):
    """Per-movement classification for one period. Returns
    { movement: {'class', 'true', 'got'[, 'sub'][, 'source']} } covering the
    12 standard movements plus any nonzero extracted U-turn (HALLUCINATION)."""
    value_owner = {v: mv for mv, v in true_vols.items()}
    total_values = set(approach_totals.values()) | {grand_total}
    rows = {}
    for mv in MOVEMENTS_12:
        t = true_vols[mv]
        e = _as_int((extracted_vols or {}).get(mv))
        row = {'true': t, 'got': e}
        if e == t:
            row['class'] = 'CORRECT'
        elif e in total_values:
            row['class'] = 'TOTAL-AS-MOVEMENT'
        elif e in value_owner:                    # exact value of another movement
            row['class'] = 'MAP-ERR'
            row['source'] = value_owner[e]
            row['sub'] = _map_subpattern(mv, value_owner[e])
        elif e is None or e == 0:
            row['class'] = 'OMISSION'
        elif abs(e - t) <= DIGIT_DELTA or _digit_edit_distance(str(t), str(e)) <= 1:
            row['class'] = 'DIGIT-ERR'
        else:
            row['class'] = 'HALLUCINATION'
        rows[mv] = row
    for u in U_TURNS:
        e = _as_int((extracted_vols or {}).get(u))
        if e:                                     # Forger never places U volumes
            rows[u] = {'true': 0, 'got': e, 'class': 'HALLUCINATION'}
    return rows


def compute_signature(style, verdict, error_classes, subpatterns):
    """Failure-shape hash: (style, classes, MAP sub-patterns) — never
    seed-specific values. PASS → empty signature."""
    if verdict == 'PASS':
        return ''
    shape = {'style': style, 'verdict': verdict,
             'classes': sorted(error_classes),
             'subpatterns': sorted(subpatterns)}
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()) \
        .hexdigest()[:12]


def grade(sheet, extraction, error=None):
    """Full deterministic grade of one extraction against its answer key."""
    style = sheet['style']
    if error or not extraction or not extraction.get('intersections'):
        return {
            'verdict': 'CRASH',
            'error': error or 'no intersections in extraction',
            'per_movement': {'AM': {}, 'PM': {}},
            'classes': {},
            'map_subpatterns': [],
            'total_ratio': {'AM': None, 'PM': None},
            'signature': compute_signature(style, 'CRASH', ['CRASH'], []),
        }

    volumes = (extraction['intersections'][0].get('volumes') or {})
    per_movement = {}
    classes = {}
    subs = set()
    total_ratio = {}
    for period in ('AM', 'PM'):
        rows = classify_period(
            sheet['periods'][period],
            volumes.get(period) or {},
            sheet['approach_totals'][period],
            sheet['grand_total'][period],
        )
        per_movement[period] = rows
        for row in rows.values():
            classes[row['class']] = classes.get(row['class'], 0) + 1
            if row['class'] == 'MAP-ERR':
                subs.add(row['sub'])
        extracted_total = sum(
            _as_int((volumes.get(period) or {}).get(mv)) or 0
            for mv in MOVEMENTS_12)
        total_ratio[period] = (extracted_total / sheet['grand_total'][period]
                               if sheet['grand_total'][period] else None)

    error_classes = {c for c in classes if c != 'CORRECT'}
    if not error_classes:
        verdict = 'PASS'
    elif error_classes <= {'DIGIT-ERR'}:
        verdict = 'DIGIT-ONLY'
    elif error_classes <= {'MAP-ERR', 'TOTAL-AS-MOVEMENT'}:
        verdict = 'MAP-FAIL'
    else:
        verdict = 'MIXED'

    return {
        'verdict': verdict,
        'error': None,
        'per_movement': per_movement,
        'classes': classes,
        'map_subpatterns': sorted(subs),
        'total_ratio': total_ratio,
        'signature': compute_signature(style, verdict, error_classes, subs),
    }
