"""Focused properties on the pure numeric core: furness_intersection (IPF) and
balance_future (corridor balance)."""
import math

from hypothesis import given

from balancer import furness_intersection, balance_nchrp
from forecasting.pass2 import balance_future
from tests.forecasting.fuzz import generators as g


# Invariant #4 — IPF terminates by MATRIX STABILITY on consistent positive
# margins; Invariant #2 — the resulting matrix is finite and non-negative.
# NOTE: furness_intersection defines convergence as matrix stability, NOT target
# satisfaction. converged=True does NOT promise final_residual < tol — see the
# balancer.py docstring and test_pass1.test_in_out_imbalance_residual, which
# documents converged=True coexisting with a positive residual. So we assert the
# residual is a finite, non-negative number, not that it clears tol.
# (Follow-up, out of scope here: audit whether any furness_intersection caller
# wrongly trusts `converged` without also checking `final_residual`.)
@given(g.consistent_ipf())
def test_ipf_converges_on_consistent_margins(case):
    M, row_t, col_t, present = case
    out, converged, iters, residual = furness_intersection(M, row_t, col_t, present)
    assert converged is True
    assert math.isfinite(residual) and residual >= 0.0
    # Invariant #2 — every cell stays finite and non-negative.
    for r in range(4):
        for c in range(4):
            assert math.isfinite(out[r][c])
            assert out[r][c] >= 0.0


# Invariants #1 (link conservation), #2 (non-negativity), #3 (round-to-5),
# #6 (corridor-order: conservation edges follow the GIVEN links, never re-sorted).
@given(g.ew_corridor())
def test_balance_future_corridor_invariants(corridor):
    nums, coords, links, volumes = corridor
    res = balance_future(volumes, links, coords=coords)
    balanced = res["balanced"]

    # #2 non-negativity + #3 round-to-5 on every balanced movement.
    for vols in balanced.values():
        for v in vols.values():
            assert v >= 0
            assert v % 5 == 0, f"{v} not a multiple of 5"

    # #1 every Full link conserves exactly after reconciliation.
    full = [c for c in res["link_conservation"] if c["mode"] == "Full"]
    assert full, "expected Full links in a corridor"
    for c in full:
        assert c["delta"] == 0, f"link {c['fromNum']}->{c['toNum']} delta {c['delta']}"

    # #6 the conservation graph edges are EXACTLY the given links — never
    # reconnected by sorted intersection number.
    # link_conservation always has TWO directed entries per EB/WB link (one per
    # flow direction), so we compare unordered intersection pairs (frozensets)
    # rather than ordered (fromNum,toNum) pairs. This still catches the
    # corridor-order bug: a re-sorted connector would produce a different pair.
    got_pairs = {frozenset([c["fromNum"], c["toNum"]]) for c in res["link_conservation"]}
    want_pairs = {frozenset([l["fromNum"], l["toNum"]]) for l in links}
    assert got_pairs == want_pairs


# Invariant — NO MOVEMENT ON AN ABSENT LEG (the int-7 phantom-EBT class). The
# balancer must never assign positive flow to a movement whose approach or exit
# leg has no raw demand (the leg doesn't physically exist) — even when a Full
# corridor link lands on a stub intersection's absent E/W leg. Leg presence is
# re-derived INDEPENDENTLY here from the generated counts (a leg exists iff some
# movement touching it has raw demand), so this checks the balancer's output, not
# its own guardrail.
@given(g.stub_leg_corridor())
def test_no_movement_on_absent_leg(case):
    nums, coords, links, volumes = case
    res = balance_nchrp(volumes, links, method="larger", coords=coords, round_to_5=True)
    for n, bvols in res["balanced"].items():
        present = [False, False, False, False]
        for mv, (r, c) in g.MV_LEGS.items():
            if volumes[n].get(mv, 0) > 0:
                present[r] = True
                present[c] = True
        for mv, (r, c) in g.MV_LEGS.items():
            if bvols.get(mv, 0) > 0:
                assert present[r] and present[c], (
                    f"int {n}: balanced {mv}={bvols[mv]} on absent leg "
                    f"(legs present S/N/W/E={present}, raw {mv}={volumes[n].get(mv, 0)})")
