"""Tests for the network ingest orchestration (module 3).

Run from backend/ with the forecasting venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting/test_ingest.py -v
"""

from pathlib import Path

import pytest

from forecasting.ingest import ingest_networks
from forecasting.contract import NetworkLayer, Period


def _by_id(layer):
    return {l.link_id: l for l in layer.links}


# ── Two-year happy path ───────────────────────────────────────────────────────
def test_two_year_ingest_returns_both(
    synthetic_sandag_shp, synthetic_sandag_shp_horizon, project_points_near
):
    out = ingest_networks(project_points_near, [
        {"role": "base", "scenario_year": 2025, "path": synthetic_sandag_shp},
        {"role": "horizon", "scenario_year": 2030, "path": synthetic_sandag_shp_horizon},
    ])
    assert set(out) == {"base", "horizon"}
    assert isinstance(out["base"], NetworkLayer)
    assert out["base"].scenario_year == 2025
    assert out["horizon"].scenario_year == 2030
    # Same corridor → identical link_id sets.
    assert {l.link_id for l in out["base"].links} == {l.link_id for l in out["horizon"].links}


def test_horizon_flows_exceed_base(
    synthetic_sandag_shp, synthetic_sandag_shp_horizon, project_points_near
):
    out = ingest_networks(project_points_near, [
        {"role": "base", "scenario_year": 2025, "path": synthetic_sandag_shp},
        {"role": "horizon", "scenario_year": 2030, "path": synthetic_sandag_shp_horizon},
    ])
    b = _by_id(out["base"])["58"]
    h = _by_id(out["horizon"])["58"]
    assert h.flow.ab[Period.AM] > b.flow.ab[Period.AM]


# ── Single-year (our actual situation until the 2nd file arrives) ─────────────
def test_single_layer_skips_overlap_check(synthetic_sandag_shp, project_points_near):
    out = ingest_networks(project_points_near, [
        {"role": "base", "scenario_year": 2025, "path": synthetic_sandag_shp},
    ])
    assert set(out) == {"base"}
    assert len(out["base"].links) == 6


# ── Overlap sanity ────────────────────────────────────────────────────────────
def test_overlap_failure_raises(
    synthetic_sandag_shp, synthetic_sandag_shp_disjoint, project_points_near
):
    with pytest.raises(ValueError, match="overlap"):
        ingest_networks(project_points_near, [
            {"role": "base", "scenario_year": 2025, "path": synthetic_sandag_shp},
            {"role": "horizon", "scenario_year": 2030, "path": synthetic_sandag_shp_disjoint},
        ])


# ── Input validation / fail-loud ──────────────────────────────────────────────
def test_unknown_region_not_implemented(project_points_near):
    with pytest.raises(NotImplementedError):
        ingest_networks(
            project_points_near,
            [{"role": "base", "scenario_year": 2025, "path": "x.shp"}],
            region="MTC",
        )


def test_empty_networks_raises(project_points_near):
    with pytest.raises(ValueError, match="no networks"):
        ingest_networks(project_points_near, [])


def test_duplicate_role_raises(synthetic_sandag_shp, project_points_near):
    with pytest.raises(ValueError, match="duplicate"):
        ingest_networks(project_points_near, [
            {"role": "base", "scenario_year": 2025, "path": synthetic_sandag_shp},
            {"role": "base", "scenario_year": 2030, "path": synthetic_sandag_shp},
        ])


def test_unresolvable_path_raises(project_points_near):
    with pytest.raises(ValueError, match="no path"):
        ingest_networks(project_points_near, [{"role": "base", "scenario_year": 2025}])


def test_missing_scenario_year_raises(synthetic_sandag_shp, project_points_near):
    with pytest.raises(ValueError, match="scenario_year"):
        ingest_networks(project_points_near, [{"role": "base", "path": synthetic_sandag_shp}])


# ── Integration: single real network as base (only one file available) ───────
REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_real_single_network_ingest():
    pts = [{"num": 1, "lat": 32.624067, "lng": -116.959736}]   # DISCOVERY FALLS node
    out = ingest_networks(pts, [{"role": "base", "scenario_year": 2025, "path": REAL_SHP}])
    assert set(out) == {"base"}
    assert out["base"].region == "SANDAG"
    assert out["base"].scenario_year == 2025
    assert len(out["base"].links) > 0
