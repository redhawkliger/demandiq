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


def _m5(rng, lo, hi):
    """Random multiple of 5 in [lo, hi] (inclusive, both multiples of 5)."""
    return rng.randrange(lo // 5, hi // 5 + 1) * 5


def _split_two(rng, total):
    """Split `total` (multiple of 5, >= 100) into two multiples of 5, each >= 50."""
    a = _m5(rng, 50, total - 50)
    return a, total - a


def _generate_period_volumes(rng, n):
    """One period's perfectly balanced corridor in EW-canonical movement codes.

    Intersections are indexed 0..n-1 west→east. Segment i joins int i and
    int i+1; V_fwd[i] is its EB volume, V_bwd[i] its WB volume. Returns
    (volumes list of {movement: veh}, seg_volumes for the log).
    """
    v_fwd = [_m5(rng, 300, 900) for _ in range(n - 1)]
    v_bwd = [_m5(rng, 300, 900) for _ in range(n - 1)]

    vols = []
    for i in range(n):
        west = i > 0            # has a segment to the west (constraints A, D)
        east = i < n - 1        # has a segment to the east (constraints B, C)
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
        if west:
            mv['EBL'], mv['EBR'] = _split_two(rng, v_fwd[i - 1] - ebt)
        else:
            mv['EBL'], mv['EBR'] = _m5(rng, 50, 600), _m5(rng, 50, 600)
        if east:
            mv['SBL'], mv['NBR'] = _split_two(rng, v_fwd[i] - ebt)
        else:
            mv['SBL'], mv['NBR'] = _m5(rng, 50, 600), _m5(rng, 50, 600)

        # WBT is shared between east-approach (C: WBL+WBT+WBR = V_bwd[i]) and
        # west-outflow (D: WBT+NBL+SBR = V_bwd[i-1]).
        caps = []
        if east:
            caps.append(v_bwd[i])
        if west:
            caps.append(v_bwd[i - 1])
        wbt = _m5(rng, 50, min(caps) - 100)
        mv['WBT'] = wbt
        if east:
            mv['WBL'], mv['WBR'] = _split_two(rng, v_bwd[i] - wbt)
        else:
            mv['WBL'], mv['WBR'] = _m5(rng, 50, 600), _m5(rng, 50, 600)
        if west:
            mv['NBL'], mv['SBR'] = _split_two(rng, v_bwd[i - 1] - wbt)
        else:
            mv['NBL'], mv['SBR'] = _m5(rng, 50, 600), _m5(rng, 50, 600)

        # Cross-street throughs are unconstrained by corridor links.
        mv['NBT'] = _m5(rng, 50, 600)
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
    crosses = rng.sample(_CROSS_NAMES, n)
    return main, crosses


def generate(seed):
    """Generate one run's corpus. Returns a dict with:

      n, tier, primary_orientation ('EW'|'NS'),
      key:    {'AM': [...], 'PM': [...]}      EW-canonical answer key
      puzzle_vols: same shape, perturbed      EW-canonical puzzle volumes
      seg_volumes: {'AM': [...], 'PM': [...]} link volumes used in construction
      perturbation_log: [...]
      projects: {'EW': <demandiq:project dict>, 'NS': <...>}
      keys_by_num: {'EW': {'AM': {num_str: {mv: veh}}, ...}, 'NS': ...}

    Both orientations are exact rotations of one abstract corridor; graders
    compare each orientation's tool output against that orientation's key.
    """
    rng = random.Random(seed)
    n = rng.randint(3, 6)
    primary = rng.choice(('EW', 'NS'))
    tier = rng.choice(PERTURB_TIERS)
    main, crosses = _street_names(rng, n)

    key = {}
    segs = {}
    for period in ('AM', 'PM'):
        key[period], segs[period] = _generate_period_volumes(rng, n)

    puzzle_vols, perturbation_log = _perturb(rng, key, tier)

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
            ints.append({
                'id': f'int-{seed}-{i + 1}',
                'num': i + 1,
                'name': f'{main} & {crosses[i]}',
                'lat': lat,
                'lng': lng,
                'approaches': {
                    d: {'exists': True,
                        'lanes': [{'movement': 'L'}, {'movement': 'T'}, {'movement': 'R'}],
                        'stopControlled': False}
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
        'tier': tier,
        'primary_orientation': primary,
        'key': key,
        'puzzle_vols': puzzle_vols,
        'seg_volumes': segs,
        'perturbation_log': perturbation_log,
        'projects': projects,
        'keys_by_num': keys_by_num,
    }
