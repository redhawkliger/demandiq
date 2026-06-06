"""End-to-end spine + VMT properties on the pure numeric pipeline."""
from hypothesis import given

from forecasting.contract import Period
from forecasting.matcher import match_network_to_legs
from forecasting.refinement import refine_corridor
from forecasting.pass1 import forecast_corridor
from forecasting.pass2 import balance_future
from tests.forecasting.fuzz import generators as g


# Invariant #7 — identity growth (horizon == base) returns the base counts on
# every bound leg; plus #2 non-negativity through the whole spine.
@given(g.single_intersection_spine(identity=True))
def test_identity_growth_conserves_counts(case):
    base, horizon, intersections, counts, growth = case
    assert growth == 1.0
    mr = match_network_to_legs(intersections, base)
    rr = refine_corridor(mr, base, horizon, counts, Period.AM)
    [r] = rr
    bound = [d for d in ("NB", "SB", "EB", "WB")
             if r["approaches"][d]["status"] == "bound"]
    for d in bound:
        for direction in ("inbound", "outbound"):
            sub = r["approaches"][d][direction]
            if sub["status"] != "held-flat":           # held legs also equal count
                assert sub["refined"] == sub["count_base"] or \
                    abs(sub["refined"] - sub["count_base"]) < 1e-6

    futures, meta = forecast_corridor(rr, counts)
    for vols in futures.values():                       # #2 non-negativity
        for v in vols.values():
            assert v >= 0

    res = balance_future(futures, [], coords={1: intersections[0]})
    for vols in res["balanced"].values():               # #3 round-to-5 holds end-to-end
        for v in vols.values():
            assert v >= 0 and v % 5 == 0


from forecasting.vmt import corridor_vmt   # noqa: E402


# Invariants #8 (scenario linearity), #10 (daily all-or-none), #2 (non-negativity).
@given(g.vmt_case())
def test_vmt_scenario_and_daily_invariants(case):
    layer, existing, future, factor = case
    out = corridor_vmt(g.VMT_CORRIDOR, g.VMT_COORDS, g.VMT_MATCHES, layer, layer,
                       existing, future, [], Period.AM, scenario_factor=factor)
    c = out["corridor"]

    # #2 non-negativity of peak-hour VMT.
    assert c["existing_vmt"] >= 0 and c["future_vmt"] >= 0

    # #8 scenario VMT is within rounding of baseline * (1 - factor).
    # corridor_vmt rounds outputs to 1 decimal place. The scenario re-runs with
    # unrounded volumes, then rounds; baseline_vmt echoes the already-rounded
    # future VMT. The two rounding operations (one on x, one on x*(1-f)) each
    # contribute up to 0.05, so the total tolerance is 0.1 per corridor segment.
    sc = out["scenario"]
    assert sc is not None
    assert sc["vmt"] == _approx(sc["baseline_vmt"] * (1.0 - factor), tol=0.1)
    assert sc["baseline_vmt"] == _approx(c["future_vmt"])

    # #10 daily fields are all-or-none, never partially populated.
    daily_fields = [c["daily_existing_vmt"], c["daily_future_vmt"]]
    assert all(x is None for x in daily_fields) or all(x is not None for x in daily_fields)


def _approx(x, tol=1e-6):
    class _A:
        def __eq__(self, other):
            return abs(other - x) <= tol + 1e-9 * abs(x)
    return _A()
