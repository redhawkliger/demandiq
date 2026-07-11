"""Harness-owned deterministic NCHRP math — the independent trust path.

Everything here is re-derived from the NCHRP balancing spec
(Docs/demandiq_balancing_methods_spec.md) and the movement-set definitions,
NOT imported from backend/balancer.py. The point of the Examiner is to check
the tool against an independent implementation of the same public formulas;
importing the tool's own code here would make every check a tautology.

Only stdlib. No RNG. No LLM.
"""

import math

# Movement sets per directed link direction (NCHRP spec §2).
#   outflow   = movements that LEAVE the intersection heading that direction
#   outflow_u = the U-turn that physically heads that direction
#   approach  = movements that ARRIVE from that direction
DIRECTION_SPEC = {
    'EB': {'outflow': ['EBT', 'SBL', 'NBR'], 'outflow_u': 'WBU', 'approach': ['EBL', 'EBT', 'EBR']},
    'WB': {'outflow': ['WBT', 'NBL', 'SBR'], 'outflow_u': 'EBU', 'approach': ['WBL', 'WBT', 'WBR']},
    'NB': {'outflow': ['NBT', 'EBL', 'WBR'], 'outflow_u': 'SBU', 'approach': ['NBL', 'NBT', 'NBR']},
    'SB': {'outflow': ['SBT', 'WBL', 'EBR'], 'outflow_u': 'NBU', 'approach': ['SBL', 'SBT', 'SBR']},
}

STANDARD_MOVEMENTS = (
    'EBL', 'EBT', 'EBR',
    'WBL', 'WBT', 'WBR',
    'NBL', 'NBT', 'NBR',
    'SBL', 'SBT', 'SBR',
)

# Leg geometry: which approach-travel-direction enters via each physical leg,
# and which exits via it. Used for physical leg presence (phantom check).
LEG_IN_DIR = {'S': 'NB', 'N': 'SB', 'W': 'EB', 'E': 'WB'}   # cars entering via leg
LEG_OUT_DIR = {'S': 'SB', 'N': 'NB', 'W': 'WB', 'E': 'EB'}  # cars exiting via leg

# A movement occupies (approach leg, exit leg). Derived from turn geometry.
MOVEMENT_LEGS = {
    'NBT': ('S', 'N'), 'NBL': ('S', 'W'), 'NBR': ('S', 'E'),
    'SBT': ('N', 'S'), 'SBR': ('N', 'W'), 'SBL': ('N', 'E'),
    'EBR': ('W', 'S'), 'EBL': ('W', 'N'), 'EBT': ('W', 'E'),
    'WBL': ('E', 'S'), 'WBR': ('E', 'N'), 'WBT': ('E', 'W'),
}


def geh(m, c):
    """GEH statistic between model value m and count value c."""
    m = float(m)
    c = float(c)
    if m + c <= 0:
        return 0.0
    return math.sqrt(2.0 * (m - c) ** 2 / (m + c))


def leg_outflow(vols, direction):
    """Total flow leaving an intersection heading `direction` ('EB'...),
    including the U-turn that heads that way."""
    spec = DIRECTION_SPEC[direction]
    total = sum(float(vols.get(k, 0) or 0) for k in spec['outflow'])
    total += float(vols.get(spec['outflow_u'], 0) or 0)
    return total


def leg_approach(vols, direction):
    """Total flow arriving at an intersection from `direction`."""
    spec = DIRECTION_SPEC[direction]
    return sum(float(vols.get(k, 0) or 0) for k in spec['approach'])


def link_conservation_entry(balanced_by_num, from_num, to_num, direction):
    """Recompute one directed link's conservation numbers from balanced
    volumes: upstream outflow, downstream inflow, delta = inflow - outflow."""
    up = leg_outflow(balanced_by_num.get(from_num, {}), direction)
    dn = leg_approach(balanced_by_num.get(to_num, {}), direction)
    return {
        'fromNum': from_num,
        'toNum': to_num,
        'direction': direction,
        'upstream_outflow': float(up),
        'downstream_inflow': float(dn),
        'delta': float(dn - up),
    }


def raw_legs_present(raw_vols):
    """Physical leg presence from raw counts: a leg exists iff its raw
    approach total OR raw outflow total is > 0. Returns {'S','N','W','E'} set."""
    present = set()
    for leg in ('S', 'N', 'W', 'E'):
        rin = leg_approach(raw_vols, LEG_IN_DIR[leg])
        rout = leg_outflow(raw_vols, LEG_OUT_DIR[leg])
        if rin > 0 or rout > 0:
            present.add(leg)
    return present
