"""
DemandIQ Forecasting — Corridor VMT (Milestone 1).

Pure deterministic math, riding behind Pass 2. VMT = Σ(volume × length) over the
corridor's through-links, rolled up link → corridor → network, for existing,
future, and delta. No buffer.

Failure modes designed out (see the spec):
  A. Length is CRS-correct MILES — SANDAG `len_mile` (model-native), geodesic
     fallback from the 4326 geometry. NEVER Euclidean on lat/lng degrees.
  B. Volume basis is pinned + labeled. Peak-hour is always clean. Daily is
     count-anchored: peak-hour forecast × the model's own per-corridor daily/peak
     ratio (Σ total_flow / Σ period_flow over the chain) — data-derived, no
     asterisk. Only the engineer-factor fallback gets the asterisk; with neither,
     daily is omitted (peak-hour still clean).
  C. Held/untraceable segments are hold-flat-and-flag — included at their value,
     corridor flagged. Never dropped (undercount) or substituted (overcount).
  D. Through-links are TRACED node→node along the model chain (not the single
     incident link) and lengths summed — so multi-link segments don't undercount.

Reuses balancer.resolve_link_volumes for the conserved directional link volumes
(on balanced movements, upstream == downstream, so 'larger' == the conserved
value) and the standard period/flow conventions.
"""

import math

from balancer import resolve_link_volumes

# Source columns for each period's directional model flow (SANDAG schema).
PERIOD_FLOW_COLS = {
    "EA": ("ab_ea_flow", "ba_ea_flow"),
    "AM": ("ab_am_flow", "ba_am_flow"),
    "MD": ("ab_md_flow", "ba_md_flow"),
    "PM": ("ab_pm_flow", "ba_pm_flow"),
    "EV": ("ab_ev_flow", "ba_ev_flow"),
}
DIRS = ("NB", "SB", "EB", "WB")


def _haversine_mi(lng1, lat1, lng2, lat2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _link_len_mi(link):
    """Model-native len_mile (CRS-correct); geodesic from geometry as fallback.
    Never Euclidean on degrees."""
    la = (link.source_attributes or {}).get("len_mile")
    try:
        v = float(la)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    g = link.geometry or []
    return sum(_haversine_mi(g[i][0], g[i][1], g[i + 1][0], g[i + 1][1])
               for i in range(len(g) - 1))


def _build_graph(layer):
    adj = {}
    for lk in layer.links:
        adj.setdefault(lk.from_node, []).append((lk.to_node, lk))
        adj.setdefault(lk.to_node, []).append((lk.from_node, lk))
    return adj


def _trace_chain(adj, src, dst):
    """Shortest (by length) model-link chain src→dst; [] if same node, None if
    unreachable."""
    import heapq
    if src is None or dst is None:
        return None
    if src == dst:
        return []
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    while pq:
        d, n = heapq.heappop(pq)
        if n == dst:
            break
        if d > dist.get(n, float("inf")):
            continue
        for nb, lk in adj.get(n, []):
            nd = d + _link_len_mi(lk)
            if nd < dist.get(nb, float("inf")):
                dist[nb] = nd
                prev[nb] = (n, lk)
                heapq.heappush(pq, (nd, nb))
    if dst not in prev:
        return None
    chain, cur = [], dst
    while cur != src:
        n, lk = prev[cur]
        chain.append(lk)
        cur = n
    return chain[::-1]


def _chain_daily_ratio(chain_links, period):
    """Model daily/peak ratio Σ total_flow / Σ (ab+ba period flow) over the chain.
    Data-derived (the model's own structure); None if no period flow."""
    ab_col, ba_col = PERIOD_FLOW_COLS[period]
    tot = per = 0.0
    for lk in chain_links:
        sa = lk.source_attributes or {}
        tot += float(sa.get("total_flow") or 0)
        per += float(sa.get(ab_col) or 0) + float(sa.get(ba_col) or 0)
    return (tot / per) if per > 0 else None


def _refinement_has_held(refinement):
    for r in refinement or []:
        for d in DIRS:
            leg = (r.get("approaches") or {}).get(d)
            if not leg:
                continue
            if leg.get("status") == "pending":
                return True
            for s in ("inbound", "outbound"):
                if (leg.get(s) or {}).get("status") == "held-flat":
                    return True
    return False


def corridor_vmt(corridor_links, coords, match_results, base_layer, horizon_layer,
                 existing_balanced, future_balanced, refinement, period, *,
                 expansion_factor=None):
    """Corridor VMT for one period. Returns {period, unit, corridor:{...}, links:[...]}.

    corridor_links: [{fromNum, toNum, direction}] (S2 corridor segments).
    coords: {int_num: {lat, lng}}.  match_results: matcher output (snapped_node).
    existing_balanced / future_balanced: {int_num: {movement: value}} for `period`.
    refinement: the period's refine_corridor output (for the held-segment flag).
    period: contract.Period.  expansion_factor: engineer peak→daily fallback.
    """
    p = period.value if hasattr(period, "value") else period
    ex_res = resolve_link_volumes(existing_balanced, corridor_links, method="larger", coords=coords)
    fu_res = resolve_link_volumes(future_balanced, corridor_links, method="larger", coords=coords)
    node_of = {m["intersection_num"]: m.get("snapped_node") for m in match_results}
    adj = _build_graph(base_layer)
    base_by_id = {l.link_id: l for l in base_layer.links}
    hor_by_id = {l.link_id: l for l in horizon_layer.links}

    links_out = []
    net = {"existing_vmt": 0.0, "future_vmt": 0.0, "length_mi": 0.0}
    seg_daily = []          # (ex_daily, fu_daily, source) per segment, or None
    gap = _refinement_has_held(refinement)

    for L in corridor_links:
        a, b = int(L["fromNum"]), int(L["toNum"])
        dirs = ("EB", "WB") if L["direction"] == "EB/WB" else ("NB", "SB")
        ex_vol = sum(v for (u, d, dc), v in ex_res.items() if {u, d} == {a, b} and dc in dirs)
        fu_vol = sum(v for (u, d, dc), v in fu_res.items() if {u, d} == {a, b} and dc in dirs)

        chain = _trace_chain(adj, node_of.get(a), node_of.get(b))
        held = chain is None
        if held:
            gap = True
            ca, cb = coords.get(a, {}), coords.get(b, {})
            length = (_haversine_mi(ca["lng"], ca["lat"], cb["lng"], cb["lat"])
                      if ca and cb else 0.0)
            chain_ids = []
        else:
            length = sum(_link_len_mi(lk) for lk in chain)
            chain_ids = [lk.link_id for lk in chain]

        ex_vmt, fu_vmt = ex_vol * length, fu_vol * length

        # Daily: data-derived ratio per year, else engineer factor, else omit.
        r_base = _chain_daily_ratio([base_by_id[i] for i in chain_ids if i in base_by_id], p) if chain_ids else None
        r_hor = _chain_daily_ratio([hor_by_id[i] for i in chain_ids if i in hor_by_id], p) if chain_ids else None
        if r_base is not None and r_hor is not None:
            seg_daily.append((ex_vmt * r_base, fu_vmt * r_hor, "data"))
        elif expansion_factor:
            seg_daily.append((ex_vmt * expansion_factor, fu_vmt * expansion_factor, "factor"))
        else:
            seg_daily.append(None)

        net["existing_vmt"] += ex_vmt
        net["future_vmt"] += fu_vmt
        net["length_mi"] += length
        links_out.append({
            "from_num": a, "to_num": b, "length_mi": round(length, 4),
            "existing_vol": round(ex_vol, 1), "future_vol": round(fu_vol, 1),
            "existing_vmt": round(ex_vmt, 1), "future_vmt": round(fu_vmt, 1),
            "delta": round(fu_vmt - ex_vmt, 1), "chain_link_ids": chain_ids, "held": held,
        })

    corridor = {
        "basis": "peak_hour", "unit": "veh-mi",
        "existing_vmt": round(net["existing_vmt"], 1),
        "future_vmt": round(net["future_vmt"], 1),
        "delta": round(net["future_vmt"] - net["existing_vmt"], 1),
        "corridor_length_mi": round(net["length_mi"], 4),
        "link_count": len(links_out),
        "gap_flag": gap,
        "daily_existing_vmt": None, "daily_future_vmt": None, "daily_delta": None,
        "daily_estimated": False, "expansion_factor": None,
    }
    # Daily reported only when EVERY segment resolved a daily value.
    if seg_daily and all(s is not None for s in seg_daily):
        dex = sum(s[0] for s in seg_daily)
        dfu = sum(s[1] for s in seg_daily)
        corridor["daily_existing_vmt"] = round(dex, 1)
        corridor["daily_future_vmt"] = round(dfu, 1)
        corridor["daily_delta"] = round(dfu - dex, 1)
        corridor["daily_estimated"] = any(s[2] == "factor" for s in seg_daily)
        if corridor["daily_estimated"]:
            corridor["expansion_factor"] = expansion_factor

    # v1 = one corridor, so network == corridor (link → corridor → network).
    return {"period": p, "unit": "veh-mi", "corridor": corridor,
            "network": dict(corridor), "links": links_out}
