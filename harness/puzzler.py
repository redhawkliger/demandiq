"""Puzzler — deterministic seeded corridor generator (answer key + puzzle).

Backwards construction: build a corridor-wide PERFECTLY balanced movement set
first (exact link conservation on every directed edge, all 12 movements
present on every leg, all values multiples of 5 in [50, 1000]) — that is the
ANSWER KEY. Then perturb every movement (±5% or ±15%, minimum ±10 veh) to
create the PUZZLE, serialized to the exact `localStorage['demandiq:project']`
schema the frontend persists.

Everything is driven by one `random.Random(seed)` — same seed, same corridor,
same perturbations, forever. No LLM, no wall clock, no global state.

The same abstract corridor is emitted in BOTH orientations (E–W and N–S) via
a 90° rotation of movement codes and coordinates, so the orientation-sweep
probe compares true rotations of one corridor, not two different corridors.
"""

import random

# 90° counter-clockwise rotation of travel direction: E→N, N→W, W→S, S→E.
# A movement code is <travel-direction><turn>; the turn letter is relative to
# the driver so it survives rotation unchanged.
_ROTATE_DIR = {'EB': 'NB', 'NB': 'WB', 'WB': 'SB', 'SB': 'EB'}

_CROSS_NAMES = [
    'Maple Ave', 'Oak St', 'Cedar Ln', 'Birch Rd', 'Walnut Ave', 'Palm Dr',
    'Juniper Way', 'Sycamore St', 'Magnolia Blvd', 'Laurel Ave', 'Aspen Ct',
    'Hawthorn Rd', 'Poplar St', 'Alder Ave', 'Chestnut Dr', 'Willow Ln',
]
_MAIN_NAMES = [
    'El Camino Real', 'Main St', 'Grand Ave', 'Harbor Blvd', 'Foothill Blvd',
    'Pacific Coast Hwy', 'Central Ave', 'Broadway',
]

PERTURB_TIERS = (0.05, 0.15)
MIN_PERTURB_VEH = 10
MOVEMENT_MIN = 50
MOVEMENT_MAX = 1000

# ── Difficulty tiers (v2) ────────────────────────────────────────────────────
# A: 3-6 ints, all 4-leg — the original v1 config, byte-identical per seed.
# B: 5-20 ints, all 4-leg — error propagation down long chains.
# C: 3-6 ints, seeded ~50/50 mix of 4-leg and 3-leg (T).
# D: 5-20 ints, mixed per Tier C rules.
TIERS = ('A', 'B', 'C', 'D')
DEFAULT_TIER_MIX = {'A': 20, 'B': 30, 'C': 30, 'D': 20}
_LONG_TIERS = ('B', 'D')      # 5-20 intersections
_T_TIERS = ('C', 'D')         # may generate 3-leg (T) intersections
T_PROBABILITY = 0.5

# For a T-intersection, the absent leg is one of the two cross-street legs —
# corridor through-legs are always present so the chain stays connected. In
# the EW-canonical frame the corridor sits on the W/E legs, so only N or S
# may be absent. Every movement that references the absent leg (approaches
# from it, exits onto it, or is the cross-street through that needs both
# cross legs) is omitted from the answer key and the puzzle. Derived from
# turn geometry: leg N carries the SB approach; NBT/EBL/WBR exit onto it.
_LEG_MOVEMENTS = {
    'N': ('SBL', 'SBT', 'SBR', 'NBT', 'EBL', 'WBR'),
    'S': ('NBL', 'NBT', 'NBR', 'SBT', 'EBR', 'WBL'),
}
# absent leg → the approach travel-direction that enters from it (EW frame)
_LEG_APPROACH_DIR = {'N': 'SB', 'S': 'NB'}


def tier_for_seed(seed, mix=None):
    """Seeded tier rotation for the loop: deterministic per (seed, mix).

    Uses its own RNG stream (string-seeded — sha512-based, stable across
    processes) so tier selection never perturbs puzzle generation."""
    mix = mix or DEFAULT_TIER_MIX
    tiers = sorted(mix)
    weights = [mix[t] for t in tiers]
    rng = random.Random(f'examiner-tier-mix:{seed}')
    return rng.choices(tiers, weights=weights)[0]


def _m5(rng, lo, hi):
    """Random multiple of 5 in [lo, hi] (inclusive, both multiples of 5)."""
    return rng.randrange(lo // 5, hi // 5 + 1) * 5


def _split_two(rng, total):
    """Split `total` (multiple of 5, >= 100) into two multiples of 5, each >= 50."""
    a = _m5(rng, 50, total - 50)
    return a, total - a


def _fill_pair(rng, mv, members, constrained, total):
    """Assign the two non-through members of one leg constraint.

    `members` lists the pair's surviving movements in canonical order — a
    T-intersection's absent leg removes at most one of them. When the pair is
    corridor-constrained, the survivors must sum to `total` (the link volume
    minus the through); otherwise each survivor is free-drawn. The draw
    sequence with both members present is byte-identical to the pre-tier
    generator (Tier A regression contract).
    """
    if constrained:
        if len(members) == 2:
            mv[members[0]], mv[members[1]] = _split_two(rng, total)
        elif members:
            mv[members[0]] = total       # single survivor takes the whole remainder
    else:
        for m in members:
            mv[m] = _m5(rng, 50, 600)


def _generate_period_volumes(rng, n, absent=None):
    """One period's perfectly balanced corridor in EW-canonical movement codes.

    Intersections are indexed 0..n-1 west→east. Segment i joins int i and
    int i+1; V_fwd[i] is its EB volume, V_bwd[i] its WB volume. Returns
    (volumes list of {movement: veh}, seg_volumes for the log).

    `absent` (difficulty tiers C/D): per-intersection absent cross-street leg,
    None | 'N' | 'S'. Movements referencing an absent leg are never generated,
    and each corridor constraint's remainder goes entirely to its surviving
    member — link conservation stays exact by construction. With absent all-
    None (tiers A/B) the RNG draw sequence is byte-identical to the pre-tier
    generator.
    """
    absent = absent or [None] * n
    v_fwd = [_m5(rng, 300, 900) for _ in range(n - 1)]
    v_bwd = [_m5(rng, 300, 900) for _ in range(n - 1)]

    vols = []
    for i in range(n):
        west = i > 0            # has a segment to the west (constraints A, D)
        east = i < n - 1        # has a segment to the east (constraints B, C)
        gone = set(_LEG_MOVEMENTS[absent[i]]) if absent[i] else ()
        mv = {}

        # EBT is shared between the west-approach (A: EBL+EBT+EBR = V_fwd[i-1])
        # and east-outflow (B: EBT+SBL+NBR = V_fwd[i]) constraints. Cap it so
        # each applicable constraint leaves >= 100 for its other two movements.
        caps = []
        if west:
            caps.append(v_fwd[i - 1])
        if east:
            caps.append(v_fwd[i])
        ebt = _m5(rng, 50, min(caps) - 100)
        mv['EBT'] = ebt
        _fill_pair(rng, mv, [m for m in ('EBL', 'EBR') if m not in gone],
                   west, v_fwd[i - 1] - ebt if west else 0)
        _fill_pair(rng, mv, [m for m in ('SBL', 'NBR') if m not in gone],
                   east, v_fwd[i] - ebt if east else 0)

        # WBT is shared between east-approach (C: WBL+WBT+WBR = V_bwd[i]) and
        # west-outflow (D: WBT+NBL+SBR = V_bwd[i-1]).
        caps = []
        if east:
            caps.append(v_bwd[i])
        if west:
            caps.append(v_bwd[i - 1])
        wbt = _m5(rng, 50, min(caps) - 100)
        mv['WBT'] = wbt
        _fill_pair(rng, mv, [m for m in ('WBL', 'WBR') if m not in gone],
                   east, v_bwd[i] - wbt if east else 0)
        _fill_pair(rng, mv, [m for m in ('NBL', 'SBR') if m not in gone],
                   west, v_bwd[i - 1] - wbt if west else 0)

        # Cross-street throughs are unconstrained by corridor links (and need
        # both cross legs, so a T-intersection has neither).
        if 'NBT' not in gone:
            mv['NBT'] = _m5(rng, 50, 600)
        if 'SBT' not in gone:
            mv['SBT'] = _m5(rng, 50, 600)
        vols.append(mv)

    segs = [
        {'segment': i, 'fwd': v_fwd[i], 'bwd': v_bwd[i]}
        for i in range(n - 1)
    ]
    return vols, segs


def rotate_movements(vols):
    """Rotate one intersection's {movement: veh} dict 90° CCW (EW → NS)."""
    return {_ROTATE_DIR[mv[:2]] + mv[2:]: v for mv, v in vols.items()}


def _perturb(rng, key_vols_by_period, tier):
    """Perturb every movement of every intersection independently.

    delta = round(key * uniform(-tier, +tier)), pushed to at least
    MIN_PERTURB_VEH in magnitude (sign preserved; a dead-zero draw gets a
    seeded coin-flip sign). Returns (puzzle volumes, perturbation log)."""
    puzzle = {}
    log = []
    for period in ('AM', 'PM'):
        puzzle[period] = []
        for i, key_mv in enumerate(key_vols_by_period[period]):
            out = {}
            for mv in sorted(key_mv):
                key_val = key_mv[mv]
                frac = rng.uniform(-tier, tier)
                delta = round(key_val * frac)
                if abs(delta) < MIN_PERTURB_VEH:
                    sign = 1 if (frac > 0 or (frac == 0 and rng.random() < 0.5)) else -1
                    delta = sign * MIN_PERTURB_VEH
                val = max(5, key_val + delta)
                out[mv] = val
                log.append({
                    'period': period, 'int_index': i, 'movement': mv,
                    'key': key_val, 'delta': val - key_val, 'puzzle': val,
                })
            puzzle[period].append(out)
    return puzzle, log


def _street_names(rng, n):
    main = rng.choice(_MAIN_NAMES)
    if n <= len(_CROSS_NAMES):
        crosses = rng.sample(_CROSS_NAMES, n)
    else:
        # Long-corridor tiers can exceed the name pool; extend with numbered
        # variants (names are cosmetic — ids/nums are the real identity).
        crosses = rng.sample(_CROSS_NAMES, len(_CROSS_NAMES))
        crosses += [f'{rng.choice(_CROSS_NAMES)} No {k}'
                    for k in range(2, n - len(_CROSS_NAMES) + 2)]
    return main, crosses


def generate(seed, tier='A'):
    """Generate one run's corpus for a difficulty tier. Returns a dict with:

      n, tier (perturbation magnitude), difficulty ('A'|'B'|'C'|'D'),
      primary_orientation ('EW'|'NS'),
      absent_legs: [None|'N'|'S', ...]        EW-frame absent leg per int
      key:    {'AM': [...], 'PM': [...]}      EW-canonical answer key
      puzzle_vols: same shape, perturbed      EW-canonical puzzle volumes
      seg_volumes: {'AM': [...], 'PM': [...]} link volumes used in construction
      perturbation_log: [...]
      projects: {'EW': <demandiq:project dict>, 'NS': <...>}
      keys_by_num: {'EW': {'AM': {num_str: {mv: veh}}, ...}, 'NS': ...}

    Both orientations are exact rotations of one abstract corridor; graders
    compare each orientation's tool output against that orientation's key.

    Determinism contract: generation is a pure function of (seed, tier).
    Tier A runs on random.Random(seed) with the exact pre-tier draw sequence
    (byte-identical per seed, pinned by goldens/tier_a_hashes.json); the other
    tiers use their own string-seeded stream so they can never perturb it.
    """
    if tier not in TIERS:
        raise ValueError(f'unknown difficulty tier {tier!r} — one of {TIERS}')
    if tier == 'A':
        rng = random.Random(seed)
        n = rng.randint(3, 6)
    else:
        rng = random.Random(f'examiner:{tier}:{seed}')
        n = rng.randint(5, 20) if tier in _LONG_TIERS else rng.randint(3, 6)
    primary = rng.choice(('EW', 'NS'))
    perturb_tier = rng.choice(PERTURB_TIERS)
    main, crosses = _street_names(rng, n)

    # Tiers C/D: seeded per-intersection leg config — ~50/50 four-leg vs T,
    # absent leg seeded among the two cross-street legs. Tiers A/B draw
    # nothing here (Tier A's stream must stay byte-identical).
    absent = [None] * n
    if tier in _T_TIERS:
        for i in range(n):
            if rng.random() < T_PROBABILITY:
                absent[i] = rng.choice(('N', 'S'))

    key = {}
    segs = {}
    for period in ('AM', 'PM'):
        key[period], segs[period] = _generate_period_volumes(rng, n, absent)

    puzzle_vols, perturbation_log = _perturb(rng, key, perturb_tier)

    # Anchor coordinates: seeded point in a plausible SoCal box, spaced ~200 m.
    lat0 = round(rng.uniform(33.6, 34.2), 6)
    lng0 = round(rng.uniform(-118.4, -117.6), 6)
    step = 0.002

    projects = {}
    keys_by_num = {}
    for orientation in ('EW', 'NS'):
        rot = orientation == 'NS'
        ints = []
        for i in range(n):
            if rot:
                lat, lng = round(lat0 + step * i, 6), lng0
            else:
                lat, lng = lat0, round(lng0 + step * i, 6)
            vols = {}
            for period in ('AM', 'PM'):
                src = puzzle_vols[period][i]
                mvs = rotate_movements(src) if rot else src
                vols[period] = {
                    mv: {'value': int(v), '_source': 'manual'}
                    for mv, v in sorted(mvs.items())
                }
            # T-intersection serialization matches the real frontend exactly
            # (S3_ApproachConfig.jsx toggleDne): the absent approach key stays
            # present with exists:false and lanes:[]; its movement keys are
            # simply omitted from volumes (already true — the key/puzzle dicts
            # never contained them).
            absent_dir = _LEG_APPROACH_DIR[absent[i]] if absent[i] else None
            if rot and absent_dir:
                absent_dir = _ROTATE_DIR[absent_dir]
            ints.append({
                'id': f'int-{seed}-{i + 1}',
                'num': i + 1,
                'name': f'{main} & {crosses[i]}',
                'lat': lat,
                'lng': lng,
                'approaches': {
                    d: ({'exists': False, 'lanes': [], 'stopControlled': False}
                        if d == absent_dir else
                        {'exists': True,
                         'lanes': [{'movement': 'L'}, {'movement': 'T'}, {'movement': 'R'}],
                         'stopControlled': False})
                    for d in ('EB', 'WB', 'NB', 'SB')
                },
                'volumes': vols,
            })

        axis = 'NB/SB' if rot else 'EB/WB'
        links = [
            {'id': f'lnk-{seed}-{i + 1}', 'fromId': ints[i]['id'], 'toId': ints[i + 1]['id'],
             'direction': axis, 'mode': 'Full', 'landUseThreshold': None}
            for i in range(n - 1)
        ]
        link_modes = {
            f"{ints[i]['id']}__{ints[i + 1]['id']}": {'mode': 'Full', 'threshold': 0}
            for i in range(n - 1)
        }

        projects[orientation] = {
            'project': {
                'name': f'Examiner seed {seed}',
                'client': 'DemandIQ Examiner',
                'projectNumber': f'EX-{seed}',
                'analyst': 'Examiner',
                'checker': 'Examiner',
                'date': '2026-01-01',
                'scenario': 'Existing',
                'projectType': 'Corridor',
                'analysisPeriods': ['AM', 'PM'],
            },
            'analysis': {'corridorDir': orientation},  # 'EW' | 'NS'
            'intersections': ints,
            'links': links,
            'balancing': {
                'enabled': True,
                'linkResolution': 'larger',
                'corridorDir': axis,
                'peakMode': 'Corridor',
                'amWindow': {'start': '07:00', 'end': '09:00'},
                'pmWindow': {'start': '16:00', 'end': '18:00'},
                'convergenceThreshold': 0.01,
                'maxIterations': 500,
                'linkBalanceModes': link_modes,
                'overrides': {'AM': {}, 'PM': {}},
            },
        }

        keys_by_num[orientation] = {}
        for period in ('AM', 'PM'):
            keys_by_num[orientation][period] = {}
            for i in range(n):
                mvs = key[period][i]
                if rot:
                    mvs = rotate_movements(mvs)
                keys_by_num[orientation][period][str(i + 1)] = {
                    mv: int(v) for mv, v in sorted(mvs.items())
                }

    return {
        'seed': seed,
        'n': n,
        'tier': perturb_tier,        # perturbation magnitude (0.05 | 0.15)
        'difficulty': tier,          # difficulty tier ('A'|'B'|'C'|'D')
        'absent_legs': absent,       # EW-frame absent cross leg per int
        'primary_orientation': primary,
        'key': key,
        'puzzle_vols': puzzle_vols,
        'seg_volumes': segs,
        'perturbation_log': perturbation_log,
        'projects': projects,
        'keys_by_num': keys_by_num,
    }
