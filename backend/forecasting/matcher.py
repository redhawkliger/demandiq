"""
DemandIQ Forecasting — Module 4: link-to-leg matcher.

Binds a project intersection's configured legs (S3 approach codes NB/SB/EB/WB)
to the SANDAG network links that represent them, and reads the inbound model
volume on each via the contract's AB/BA convention.

PURE PYTHON — no geo dependencies. It runs on the already-ingested, already-
filtered NetworkLayer (tens of links, EPSG:4326), so bearings and distances are
~10 lines of haversine/bearing (the Python twins of frontend `geo.js` — a port,
not a rebuilt engine). The geo-dep boundary is the ingest line and nowhere else:
matcher, refinement, and Pass 1/2 all run in the lean production image.

The direction convention is shared with S6: the approach→leg-bearing map is
derived from balancer.LEG_INDEX / balancer.LEG_IN_DIR, so the balancer, the S3
legs, and this matcher all agree on what "the NB approach" means physically.

Philosophy (carried over from frontend `matching.js`): favour false negatives
(flag for the engineer to map) over false positives (silently bind the wrong
link). Low-confidence bindings are surfaced as `ambiguous`/`unmatched`, never
guessed.
"""

import math

from balancer import LEG_INDEX, LEG_IN_DIR

# ── Tuning knobs (revisit after the first real corridor pass) ─────────────────
# Max node-snap distance. Half the 300 ft ingest radius — beyond this the
# intersection is genuinely off-model; flag and DON'T bind. Tune down if real
# placements are tighter.
SNAP_TOLERANCE_FT = 150.0
# A bound leg more than this far off its cardinal is too skewed to auto-trust →
# `ambiguous`. SD's arterial grid has 30-35° skew, so 35° is a lenient start;
# tighten toward the "favour false negatives" philosophy if engineers find
# matches they'd rather have reviewed.
BEARING_DEVIATION_THRESHOLD_DEG = 35.0
# Two incident links whose deviations to the same slot fall within this band
# contest it → `ambiguous`, both surfaced as candidates.
AMBIGUITY_BAND_DEG = 20.0

# Physical compass bearing each leg points AWAY from the intersection center.
_LEG_NAME_BEARING = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}

# approach code → outward bearing of the physical leg it sits on. Derived through
# S6/balancer semantics so the convention is single-sourced: LEG_INDEX maps leg
# name → index; LEG_IN_DIR maps index → the approach entering via that leg. E.g.
# the S leg (idx 0) carries the 'NB' approach and points 180°.
# Result: {'NB': 180, 'SB': 0, 'EB': 270, 'WB': 90}.
APPROACH_LEG_BEARING = {
    LEG_IN_DIR[idx]: _LEG_NAME_BEARING[name]
    for name, idx in LEG_INDEX.items()
}

APPROACHES = ("NB", "SB", "EB", "WB")


# ── Geodesy — Python twins of frontend geo.js ─────────────────────────────────
def _bearing(lng1, lat1, lng2, lat2):
    """Bearing p1→p2, degrees clockwise from north [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lng2 - lng1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _haversine_ft(lng1, lat1, lng2, lat2):
    """Great-circle distance in feet."""
    r_ft = 3958.8 * 5280.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r_ft * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _angular_diff(a, b):
    """Smallest absolute difference between two bearings, [0, 180]."""
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


# ── Layer topology ────────────────────────────────────────────────────────────
def _node_coords(layer):
    """node_id → (lng, lat), from link endpoints."""
    coords = {}
    for lk in layer.links:
        coords.setdefault(lk.from_node, lk.from_node_xy)
        coords.setdefault(lk.to_node, lk.to_node_xy)
    return coords


def _incident_links(layer):
    """node_id → [links touching it]."""
    inc = {}
    for lk in layer.links:
        inc.setdefault(lk.from_node, []).append(lk)
        inc.setdefault(lk.to_node, []).append(lk)
    return inc


def _other_endpoint(link, node):
    """The (node_id, (lng, lat)) at the far end of `link` from `node`."""
    if link.from_node == node:
        return link.to_node, link.to_node_xy
    return link.from_node, link.from_node_xy


def _snap_node(lat, lng, node_coords):
    """Nearest network node to (lat, lng); returns (node_id, distance_ft)."""
    best_node, best_dist = None, None
    for node, (nlng, nlat) in node_coords.items():
        d = _haversine_ft(lng, lat, nlng, nlat)
        if best_dist is None or d < best_dist:
            best_node, best_dist = node, d
    return best_node, best_dist


def _absent_leg():
    return {"status": "absent", "link_id": None, "bearing_deg": None,
            "deviation_deg": None, "inbound": None, "candidates": []}


def _unmatched_leg():
    return {"status": "unmatched", "link_id": None, "bearing_deg": None,
            "deviation_deg": None, "inbound": None, "candidates": []}


def _match_one(it, node_coords, incident, snap_tol, bearing_thr, amb_band):
    num = it["num"]
    result = {
        "intersection_num": num,
        "snapped_node": None,
        "snap_distance_ft": None,
        "legs": {},
        "unbound_links": [],
        "flags": [],
    }
    approaches = it.get("approaches") or {}
    # A leg exists unless explicitly marked exists:false (S3 "Does not exist").
    existing = [d for d in APPROACHES if (approaches.get(d) or {}).get("exists", True)]
    for d in APPROACHES:
        if d not in existing:
            result["legs"][d] = _absent_leg()

    if not node_coords:                       # defensive — ingest guarantees ≥1
        for d in existing:
            result["legs"][d] = _unmatched_leg()
        return result

    node, dist = _snap_node(it["lat"], it["lng"], node_coords)
    result["snapped_node"] = node
    result["snap_distance_ft"] = round(dist, 1)

    if dist > snap_tol:
        result["flags"].append({
            "code": "SNAP-DISTANCE",
            "message": (f"Int {num}: nearest model node is {dist:.0f} ft away "
                        f"(> {snap_tol:.0f} ft) — off-model; legs not bound."),
        })
        for d in existing:
            result["legs"][d] = _unmatched_leg()
        return result

    # Incident links and their outward bearings from the snapped node.
    n_lng, n_lat = node_coords[node]
    link_bearings = {}                        # link_id → (link, bearing)
    for lk in incident.get(node, []):
        _, (o_lng, o_lat) = _other_endpoint(lk, node)
        link_bearings[lk.link_id] = (lk, _bearing(n_lng, n_lat, o_lng, o_lat))

    # Link-centric assignment: each incident link picks its NEAREST existing
    # approach. A link can never be force-filled into a slot it doesn't point at
    # (a slot with no natural link stays unmatched, not bound to whatever's left
    # over) — that's what keeps an opposite-pointing link off an empty leg.
    slot_links = {d: [] for d in existing}    # approach → [(deviation, link_id)]
    for lid, (lk, b) in link_bearings.items():
        best_d, best_dev = None, None
        for d in existing:
            dev = _angular_diff(b, APPROACH_LEG_BEARING[d])
            if best_dev is None or dev < best_dev:
                best_dev, best_d = dev, d
        if best_d is not None:
            slot_links[best_d].append((best_dev, lid))
    for d in existing:
        slot_links[d].sort()

    candidate_ids = set()                     # links surfaced for engineer review
    bound_ids = set()                         # leading link per matched/ambiguous slot
    for d in existing:
        cands = slot_links[d]
        if not cands:                         # no link points at this leg
            result["legs"][d] = _unmatched_leg()
            continue
        best_dev, best_lid = cands[0]
        # Contenders within AMBIGUITY_BAND of the best fit for this slot.
        close = sorted(lid for dev, lid in cands if dev <= best_dev + amb_band)
        lk, b = link_bearings[best_lid]
        inbound = {p.value: v for p, v in lk.inbound_to(node).items()}
        if len(close) >= 2:
            status, candidates = "ambiguous", close
        elif best_dev > bearing_thr:          # lone link too skewed to auto-trust
            status, candidates = "ambiguous", [best_lid]
        else:
            status, candidates = "matched", []
        bound_ids.add(best_lid)
        candidate_ids.update(candidates)
        result["legs"][d] = {
            "status": status, "link_id": best_lid,
            "bearing_deg": round(b, 1), "deviation_deg": round(best_dev, 1),
            "inbound": inbound, "candidates": candidates,
        }

    # Unbound = incident links that are neither the leading link of a slot nor a
    # review candidate (ramps, frontage roads, or a leg the engineer marked DNE).
    for lid, (lk, b) in link_bearings.items():
        if lid not in bound_ids and lid not in candidate_ids:
            result["unbound_links"].append({
                "link_id": lid, "bearing_deg": round(b, 1),
                "functional_class": lk.functional_class,
            })
    result["unbound_links"].sort(key=lambda u: u["link_id"])

    return result


def match_network_to_legs(
    intersections,
    layer,
    *,
    snap_tolerance_ft=SNAP_TOLERANCE_FT,
    bearing_threshold_deg=BEARING_DEVIATION_THRESHOLD_DEG,
    ambiguity_band_deg=AMBIGUITY_BAND_DEG,
):
    """Match each project intersection's legs to network links on one layer.

    Args:
        intersections: iterable of mappings with 'num', 'lat', 'lng', and
            optional 'approaches' ({NB/SB/EB/WB → {exists, lanes}} per S3).
            Match on the BASE layer; refinement reads both years by link_id.
        layer: a NetworkLayer (already filtered, EPSG:4326).
        snap_tolerance_ft / bearing_threshold_deg / ambiguity_band_deg: tuning
            knobs (see module constants).

    Returns:
        list of per-intersection match results:
          { intersection_num, snapped_node, snap_distance_ft,
            legs: { "NB": { status, link_id, bearing_deg, deviation_deg,
                            inbound: {period: vol} | None, candidates: [...] },
                    ... },                      # status ∈ matched|ambiguous|
                                                #          unmatched|absent
            unbound_links: [ {link_id, bearing_deg, functional_class}, ... ],
            flags: [ {code, message}, ... ] }   # SNAP-DISTANCE, SNAP-COLLISION
    """
    node_coords = _node_coords(layer)
    incident = _incident_links(layer)
    results = [
        _match_one(it, node_coords, incident,
                   snap_tolerance_ft, bearing_threshold_deg, ambiguity_band_deg)
        for it in intersections
    ]

    # Snap collisions: two intersections bound to the same model node.
    by_node = {}
    for r in results:
        if r["snapped_node"] is not None and r["snap_distance_ft"] is not None \
                and r["snap_distance_ft"] <= snap_tolerance_ft:
            by_node.setdefault(r["snapped_node"], []).append(r["intersection_num"])
    for node, nums in by_node.items():
        if len(nums) > 1:
            for r in results:
                if r["intersection_num"] in nums:
                    r["flags"].append({
                        "code": "SNAP-COLLISION",
                        "message": (f"Intersections {sorted(nums)} snapped to the "
                                    f"same model node {node} — verify placement."),
                    })

    return results
