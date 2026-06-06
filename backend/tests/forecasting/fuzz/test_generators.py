"""Self-tests: every generator must emit STRUCTURALLY VALID inputs, so a
property failure later means a real math bug, not a malformed-input artifact."""
from hypothesis import given

from forecasting.contract import NetworkLayer
from tests.forecasting.fuzz import generators as g


@given(g.ew_corridor())
def test_ew_corridor_is_valid(corridor):
    nums, coords, links, volumes = corridor
    assert len(nums) == len(set(nums)) >= 2          # distinct intersection numbers
    assert set(volumes) == set(nums)                 # one volume dict per intersection
    # corridor order is the GIVEN order, deliberately not sorted by number
    assert [l["fromNum"] for l in links] == nums[:-1]
    assert [l["toNum"] for l in links] == nums[1:]
    for v in volumes.values():
        assert all(x >= 0 for x in v.values())       # non-negative seeds only


@given(g.single_intersection_spine())
def test_spine_layers_are_valid(case):
    base, horizon, intersections, counts, growth = case
    assert isinstance(base, NetworkLayer)            # pydantic validation passed (unique link_id)
    assert isinstance(horizon, NetworkLayer)
    assert set(counts[1]) == set(g.ALL12)
    assert growth > 0


@given(g.consistent_ipf())
def test_ipf_inputs_have_matching_totals(case):
    M, row_t, col_t, present = case
    assert all(present)
    assert abs(sum(row_t) - sum(col_t)) < 1e-6       # consistent margins => IPF must converge
    assert all(M[r][c] > 0 for r in range(4) for c in range(4))
