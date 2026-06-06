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
