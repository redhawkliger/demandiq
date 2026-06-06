"""Focused properties on the pure numeric core: furness_intersection (IPF) and
balance_future (corridor balance)."""
import math

from hypothesis import given

from balancer import furness_intersection
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
