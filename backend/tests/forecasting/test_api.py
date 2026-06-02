"""Tests for the forecasting HTTP API (router in isolation).

The router is mounted on a bare FastAPI() + TestClient — no app.py, no
ANTHROPIC_API_KEY, no auth. Geo-dependent ingest is exercised via a real-file
gated test and a monkeypatched happy path; the 503 degrade is forced by
monkeypatching ingest to raise ModuleNotFoundError.

Run from backend/ with the combined venv:
    .venv-forecasting/bin/python -m pytest tests/forecasting/test_api.py -v
"""

import math
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from forecasting.api import router
from forecasting.contract import DirectionalFlow, NetworkLayer, NetworkLink, Period
from forecasting.matcher import match_network_to_legs

app = FastAPI()
app.include_router(router, prefix="/forecast")
client = TestClient(app)

CENTER_LNG, CENTER_LAT = -117.160, 32.720
C_XY = (CENTER_LNG, CENTER_LAT)


def _dest(brng, dist_ft=500.0):
    r = 3958.8 * 5280.0
    d = dist_ft / r
    th = math.radians(brng)
    phi1, lam1 = math.radians(CENTER_LAT), math.radians(CENTER_LNG)
    phi2 = math.asin(math.sin(phi1) * math.cos(d) + math.cos(phi1) * math.sin(d) * math.cos(th))
    lam2 = lam1 + math.atan2(math.sin(th) * math.sin(d) * math.cos(phi1),
                             math.cos(d) - math.sin(phi1) * math.sin(phi2))
    return (math.degrees(lam2), math.degrees(phi2))


def _link(lid, fn, tn, fxy, txy, ab, ba):
    return NetworkLink(link_id=str(lid), from_node=fn, to_node=tn,
                       geometry=[fxy, txy], from_node_xy=fxy, to_node_xy=txy,
                       functional_class="Major Arterial",
                       flow=DirectionalFlow(ab={Period.AM: ab}, ba={Period.AM: ba}))


_SPEC = {"N": (100, 1, C_XY, _dest(0)), "S": (2, 100, _dest(180), C_XY),
         "E": (100, 3, C_XY, _dest(90)), "W": (4, 100, _dest(270), C_XY)}
_DEF = {"N": (900, 1200), "S": (1000, 1160), "E": (700, 800), "W": (600, 650)}


def _layer(scale=1.0):
    links = [_link(k, *_SPEC[k], ab * scale, ba * scale) for k, (ab, ba) in _DEF.items()]
    return NetworkLayer(region="SANDAG", source_crs_epsg=2230, crs_epsg=4326,
                        scenario_year=int(2025 * 1), links=links)


COUNTS = {"NBL": 100, "NBT": 500, "NBR": 50, "SBL": 80, "SBT": 480, "SBR": 40,
          "EBL": 60, "EBT": 300, "EBR": 30, "WBL": 70, "WBT": 320, "WBR": 35}
INTX = {"num": 1, "lat": CENTER_LAT, "lng": CENTER_LNG}


# ── /ingest-match validation (no geo) ─────────────────────────────────────────
def test_ingest_match_requires_intersections():
    r = client.post("/forecast/ingest-match", json={"networks": [{"role": "base", "scenario_year": 2025}]})
    assert r.status_code == 400


def test_ingest_match_requires_networks():
    r = client.post("/forecast/ingest-match", json={"intersections": [INTX]})
    assert r.status_code == 400


def test_ingest_match_sanitizes_path_to_data_dir(monkeypatch):
    # A traversal attempt must be stripped to a basename under data/sandag — the
    # client can never read outside the server's network data dir.
    captured = {}

    def _capture(intersections, networks, **kw):
        captured["networks"] = networks
        return {"base": NetworkLayer(region="SANDAG", source_crs_epsg=2230,
                                     crs_epsg=4326, scenario_year=2025, links=[])}

    monkeypatch.setattr("forecasting.api.ingest_networks", _capture)
    r = client.post("/forecast/ingest-match", json={
        "intersections": [INTX],
        "networks": [{"role": "base", "scenario_year": 2025, "path": "../../../etc/passwd"}],
    })
    assert r.status_code == 200
    p = captured["networks"][0]["path"].replace("\\", "/")
    assert p.endswith("/data/sandag/passwd")


def test_ingest_match_503_without_geo(monkeypatch):
    def _boom(*a, **k):
        raise ModuleNotFoundError("No module named 'geopandas'")
    monkeypatch.setattr("forecasting.api.ingest_networks", _boom)
    r = client.post("/forecast/ingest-match", json={
        "intersections": [INTX], "networks": [{"role": "base", "scenario_year": 2025}],
    })
    assert r.status_code == 503
    assert "geo dependencies" in r.json()["detail"]


def test_ingest_match_happy_mocked(monkeypatch):
    base = _layer()
    monkeypatch.setattr("forecasting.api.ingest_networks", lambda *a, **k: {"base": base})
    r = client.post("/forecast/ingest-match", json={
        "intersections": [INTX], "networks": [{"role": "base", "scenario_year": 2025}],
    })
    assert r.status_code == 200
    body = r.json()
    assert "base" in body["layers"]
    assert body["layers"]["base"]["crs_epsg"] == 4326
    assert len(body["matches"]) == 1
    legs = body["matches"][0]["legs"]
    assert all(legs[d]["status"] == "matched" for d in ("NB", "SB", "EB", "WB"))


# ── /run ──────────────────────────────────────────────────────────────────────
def _run_payload(periods=("AM",)):
    base, horizon = _layer(1.0), _layer(1.5)
    matches = match_network_to_legs([INTX], base)
    return {
        "layers": {"base": base.model_dump(mode="json"),
                   "horizon": horizon.model_dump(mode="json")},
        "matches": matches,
        "balanced_tmcs": {"AM": {1: COUNTS}, "PM": {1: COUNTS}},
        "links": [],
        "coords": {1: {"lat": CENTER_LAT, "lng": CENTER_LNG}},
        "periods": list(periods),
    }


def test_run_requires_both_layers():
    payload = _run_payload()
    payload["layers"].pop("horizon")
    r = client.post("/forecast/run", json=payload)
    assert r.status_code == 400
    assert "two model years" in r.json()["detail"]


def test_run_rejects_bad_period():
    payload = _run_payload(periods=("XX",))
    r = client.post("/forecast/run", json=payload)
    assert r.status_code == 400


def test_run_happy_path():
    r = client.post("/forecast/run", json=_run_payload(periods=("AM",)))
    assert r.status_code == 200
    am = r.json()["AM"]
    assert isinstance(am["refinement"], list)
    balanced = am["pass2"]["balanced"]["1"]
    assert balanced, "expected balanced future TMCs"
    for v in balanced.values():
        assert v % 5 == 0
    # NB approach grew ~1.5× from the base count of 650.
    assert sum(balanced[m] for m in ("NBL", "NBT", "NBR")) > 900


# ── Integration: real ingest-match end to end (gated) ─────────────────────────
REAL_SHP = Path(__file__).resolve().parents[3] / "data" / "sandag" / "hwyLoad.shp"


@pytest.mark.skipif(not REAL_SHP.exists(),
                    reason="real SANDAG hwyLoad.shp not present (local-only)")
def test_ingest_match_real_file():
    r = client.post("/forecast/ingest-match", json={
        "intersections": [{"num": 1, "lat": 32.624067, "lng": -116.959736}],
        "networks": [{"role": "base", "scenario_year": 2025, "path": str(REAL_SHP)}],
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["layers"]["base"]["links"]) > 0
    assert body["matches"][0]["snapped_node"] is not None
