"""
DemandIQ Conservative + Furness Balancer — REFERENCE IMPLEMENTATION
Proven against the hand-worked example. This is the algorithm spec in executable form.
Claude Code should port this logic into backend/balancer.py.
"""
import copy

# Movement sets per direction.
# OUTFLOW feeders = what leaves the intersection in that direction (fed by through + 2 turns + U).
# APPROACH moves  = what arrives at the intersection from that direction (through + 2 turns).
# U-turns: counted in the OUTFLOW total but NEVER adjusted.
DIRECTION_SPEC = {
    'EB': {'outflow': ['EBT','SBL','NBR'],   'outflow_u': 'WBU', 'approach': ['EBL','EBT','EBR']},
    'WB': {'outflow': ['WBT','NBL','SBR'],   'outflow_u': 'EBU', 'approach': ['WBL','WBT','WBR']},
    'NB': {'outflow': ['NBT','EBL','WBR'],   'outflow_u': 'SBU', 'approach': ['NBL','NBT','NBR']},
    'SB': {'outflow': ['SBT','WBL','EBR'],   'outflow_u': 'NBU', 'approach': ['SBL','SBT','SBR']},
}

def _outflow(m, dirn):
    s = DIRECTION_SPEC[dirn]
    return sum(m.get(k,0) for k in s['outflow']) + m.get(s['outflow_u'],0)

def _approach(m, dirn):
    s = DIRECTION_SPEC[dirn]
    return sum(m.get(k,0) for k in s['approach'])

def _link_delta(up, dn, dirn):
    """downstream approach - upstream outflow. Zero = balanced."""
    return _approach(dn, dirn) - _outflow(up, dirn)


# ─────────────────────────────────────────────────────────────────────
# CONSERVATIVE adjustment: raise whichever side is LOWER, up to the higher,
# distributing proportional to each movement's share of its side's total.
# Only ever ADDS -> floor (never below raw) is automatic.
# ─────────────────────────────────────────────────────────────────────
def _adjust_conservative(v, u, d, dirn, tol):
    delta = _link_delta(v[u], v[d], dirn)
    if abs(delta) < tol:
        return
    s = DIRECTION_SPEC[dirn]
    if delta > 0:
        # downstream approach higher -> raise UPSTREAM outflow feeders
        tot = _outflow(v[u], dirn)
        if tot <= 0: return
        for k in s['outflow']:                      # U-turn excluded from receiving
            v[u][k] += delta * (v[u][k] / tot)
    else:
        # upstream outflow higher -> raise DOWNSTREAM approach movements
        tot = _approach(v[d], dirn)
        if tot <= 0: return
        for k in s['approach']:
            v[d][k] += abs(delta) * (v[d][k] / tot)


# ─────────────────────────────────────────────────────────────────────
# FURNESS adjustment: move BOTH sides toward their average. No floor.
# Standard NCHRP 255 proportional balancing. Can push below raw.
# ─────────────────────────────────────────────────────────────────────
def _adjust_furness(v, u, d, dirn, tol):
    s = DIRECTION_SPEC[dirn]
    o = _outflow(v[u], dirn); a = _approach(v[d], dirn)
    if abs(a - o) < tol: return
    target = (o + a) / 2
    if o > 0:
        f = target / o
        for k in s['outflow']: v[u][k] *= f
    if a > 0:
        f = target / a
        for k in s['approach']: v[d][k] *= f


# ─────────────────────────────────────────────────────────────────────
# CHAIN-WALKING SOLVER (shared scaffolding for both modes)
# links_dir: list of (upstream_id, downstream_id, direction)
# mode: 'conservative' | 'furness'
# ─────────────────────────────────────────────────────────────────────
def balance(raw_volumes, links_dir, mode='conservative',
            max_iter=500, tol=1e-6, round_final=True):
    v = copy.deepcopy(raw_volumes)
    adjust = _adjust_conservative if mode == 'conservative' else _adjust_furness

    def max_delta():
        return max((abs(_link_delta(v[u], v[d], dn)) for u,d,dn in links_dir), default=0)

    iters_used = 0
    converged = False
    for it in range(max_iter):
        if max_delta() < tol:
            converged = True; iters_used = it; break
        # process directions grouped so cross-direction shared-movement
        # interference is minimized: do all EB/WB, then NB/SB, then recheck.
        for u,d,dn in links_dir:
            adjust(v, u, d, dn, tol)
        iters_used = it + 1

    # FURNESS-mode floor clamp is intentionally NOT applied (user chose the
    # textbook method knowing it can dip below raw). Conservative never dips.

    if round_final:
        v = _round_and_reconcile(v, links_dir, mode, tol)

    return {
        'balanced': v,
        'converged': converged,
        'iterations': iters_used,
        'final_max_delta': max_delta(),
        'mode': mode,
    }


def _round_up_5(x):
    """Round UP to next multiple of 5, except exact 0 stays 0."""
    if abs(x) < 1e-9: return 0
    import math
    return int(math.ceil(x / 5.0) * 5)

def _round_and_reconcile(v, links_dir, mode, tol):
    """Round all values up to next 5 (0 stays 0), then ONE reconciliation pass
    so rounding doesn't leave small residual deltas."""
    for i in v:
        for k in v[i]:
            v[i][k] = _round_up_5(v[i][k])
    # one reconciliation pass after rounding
    adjust = _adjust_conservative if mode == 'conservative' else _adjust_furness
    for u,d,dn in links_dir:
        adjust(v, u, d, dn, tol)
    # re-round the touched values
    for i in v:
        for k in v[i]:
            v[i][k] = _round_up_5(v[i][k])
    return v


# ─────────────────────────────────────────────────────────────────────
# SELF-TEST against the hand-worked example
# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    FULL = {'EBL':0,'EBT':0,'EBR':0,'WBL':0,'WBT':0,'WBR':0,'NBL':0,'NBT':0,
            'NBR':0,'SBL':0,'SBT':0,'SBR':0,'WBU':0,'EBU':0,'NBU':0,'SBU':0}
    def mk(d): m=dict(FULL); m.update(d); return m
    RAW = {
        1: mk({'EBL':80,'EBT':1000,'EBR':50,'SBL':25,'NBR':25}),
        2: mk({'EBL':60,'EBT':1050,'EBR':40,'SBL':30,'NBR':20}),
        3: mk({'EBL':100,'EBT':600,'EBR':70,'SBL':40,'NBR':35}),
    }
    links = [(1,2,'EB'),(2,3,'EB')]

    print("CONSERVATIVE (full precision, pre-round):")
    r = balance(RAW, links, mode='conservative', round_final=False)
    for i in (1,2,3):
        m=r['balanced'][i]
        print(f"  Int{i}: EBT={m['EBT']:.1f} EBL={m['EBL']:.1f} EBR={m['EBR']:.1f} SBL={m['SBL']:.1f} NBR={m['NBR']:.1f}")
    print(f"  converged={r['converged']} iters={r['iterations']} maxdelta={r['final_max_delta']:.4f}")
    print(f"  EXPECTED from your sheet: Int1 EBT=1095.2  Int3 EBT=857.1  Int3 EBL=142.9")

    print("\nCONSERVATIVE (rounded final):")
    r2 = balance(RAW, links, mode='conservative', round_final=True)
    for i in (1,2,3):
        m=r2['balanced'][i]
        print(f"  Int{i}: EBT={m['EBT']} EBL={m['EBL']} EBR={m['EBR']} SBL={m['SBL']} NBR={m['NBR']}")

    print("\nFURNESS (no floor — will dip below raw):")
    r3 = balance(RAW, links, mode='furness', round_final=True)
    for i in (1,2,3):
        m=r3['balanced'][i]
        flag = " <-- below raw!" if m['EBT'] < RAW[i]['EBT'] else ""
        print(f"  Int{i}: EBT={m['EBT']}{flag}")
