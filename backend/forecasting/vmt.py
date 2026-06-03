"""
DemandIQ Forecasting — Corridor VMT (Milestone 1).

Pure deterministic math, riding behind Pass 2. VMT = Σ(volume × length) over the
corridor's through-links, rolled up link → corridor → network, for existing,
future, and delta. No buffer.

Failure modes designed out (see the spec):
  A. Length is CRS-correct MILES — read from the canonical NetworkLink.length_mi
     (the adapter set it from the model-native length, else a great-circle
     fallback from the 4326 geometry). NEVER Euclidean on lat/lng degrees.
  B. Volume basis is pinned + labeled. Peak-hour is always clean. Daily is
     count-anchored: peak-hour forecast × the model's own per-corridor daily/period
     ratio (Σ link.daily_total / Σ period flow over the chain, both from the
     canonical contract) — data-derived, no asterisk. Only the engineer-factor
     fallback gets the asterisk; with neither, daily is omitted (peak-hour clean).
  C. Held/untraceable segments are hold-flat-and-flag — included at their value,
     corridor flagged. Never dropped (undercount) or substituted (overcount).
  D. Through-links are TRACED node→node along the model chain (not the single
     incident link) and lengths summed — so multi-link segments don't undercount.

Reuses balancer.resolve_link_volumes for the conserved directional link volumes
(on balanced movements, upstream == downstream, so 'larger' == the conserved
value) and the standard period/flow conventions.
"""

from balancer import resolve_link_volumes
from forecasting.geo import haversine_mi, polyline_length_mi

DIRS = ("NB", "SB", "EB", "WB")


def _link_len_mi(link):
    """Canonical length in miles — the adapter-set NetworkLink.length_mi, with a
    great-circle fallback from geometry for hand-built links that lack it. Reads
    the contract, never a region-specific source column. Never Euclidean."""
    if link.length_mi is not None:
        return link.length_mi
    return polyline_length_mi(link.geometry)


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
    """Model daily/period ratio Σ daily_total / Σ (ab+ba period flow) over the
    chain — read from the canonical contract (NetworkLink.daily_total and .flow),
    not region-specific columns. Data-derived; None if no period flow."""
    tot = per = 0.0
    for lk in chain_links:
        tot += lk.daily_total or 0.0
        per += (lk.flow.ab.get(period) or 0.0) + (lk.flow.ba.get(period) or 0.0)
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
                 expansion_factor=None, scenario_factor=None):
    """Corridor VMT for one period. Returns {period, unit, corridor, links, scenario}.

    corridor_links: [{fromNum, toNum, direction}] (S2 corridor segments).
    coords: {int_num: {lat, lng}}.  match_results: matcher output (snapped_node).
    existing_balanced / future_balanced: {int_num: {movement: value}} for `period`.
    refinement: the period's refine_corridor output (for the held-segment flag).
    period: contract.Period.  expansion_factor: engineer peak→daily fallback.

    scenario_factor: an engineer-supplied demand-reduction fraction (0 < f < 1,
    e.g. a TDM/bike-lane assumption sourced from CAPCOA or their own study). When
    set, the forecast volumes are scaled by (1 - f) and the SAME math re-runs to
    produce a labeled `scenario` block (baseline vs. scenario vs. delta). The tool
    APPLIES the factor — it never generates, suggests, or stores one. `scenario`
    is None when no factor (or 0) is given; the baseline fields are unchanged.
    A v1 single corridor-wide factor (per-link/per-direction is a later refinement).
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
            length = (haversine_mi(ca["lng"], ca["lat"], cb["lng"], cb["lat"])
                      if ca and cb else 0.0)
            chain_ids = []
        else:
            length = sum(_link_len_mi(lk) for lk in chain)
            chain_ids = [lk.link_id for lk in chain]

        ex_vmt, fu_vmt = ex_vol * length, fu_vol * length

        # Daily: data-derived ratio per year, else engineer factor, else omit.
        r_base = _chain_daily_ratio([base_by_id[i] for i in chain_ids if i in base_by_id], period) if chain_ids else None
        r_hor = _chain_daily_ratio([hor_by_id[i] for i in chain_ids if i in hor_by_id], period) if chain_ids else None
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

    # ── Scenario: one multiplier on the forecast volumes, same engine re-run ──
    # Reduction is uniform corridor-wide (v1). By linearity, scaling every future
    # movement by (1 - f) and re-running corridor_vmt yields exactly the baseline
    # future VMT × (1 - f) per link and corridor-wide — so length, the daily ratio,
    # and the held/gap logic all recompute identically and inherit for free.
    scenario = None
    if scenario_factor:
        if not 0 < scenario_factor < 1:
            raise ValueError(
                "scenario_factor must be a fraction strictly between 0 and 1, "
                f"got {scenario_factor}")
        scaled = {i: {mv: v * (1 - scenario_factor) for mv, v in (mvs or {}).items()}
                  for i, mvs in future_balanced.items()}
        s = corridor_vmt(corridor_links, coords, match_results, base_layer,
                         horizon_layer, existing_balanced, scaled, refinement, period,
                         expansion_factor=expansion_factor)
        sc = s["corridor"]
        base_fut = corridor["future_vmt"]
        delta = round(sc["future_vmt"] - base_fut, 1)
        d_base, d_scen = corridor["daily_future_vmt"], sc["daily_future_vmt"]
        scenario = {
            "factor": scenario_factor,
            "basis": "peak_hour", "unit": "veh-mi",
            "vmt": sc["future_vmt"],            # mitigated (scenario) forecast VMT
            "baseline_vmt": base_fut,           # unmitigated forecast VMT (echoed)
            "delta": delta,                     # scenario − baseline (≤ 0)
            "pct": round(delta / base_fut, 4) if base_fut else None,
            "daily_vmt": d_scen,
            "daily_baseline_vmt": d_base,
            "daily_delta": (round(d_scen - d_base, 1)
                            if d_scen is not None and d_base is not None else None),
            "daily_estimated": sc["daily_estimated"],
            "expansion_factor": sc["expansion_factor"],
            "links": [
                {"from_num": b["from_num"], "to_num": b["to_num"],
                 "baseline_future_vmt": b["future_vmt"],
                 "scenario_future_vmt": sv["future_vmt"],
                 "delta": round(sv["future_vmt"] - b["future_vmt"], 1)}
                for b, sv in zip(links_out, s["links"])
            ],
        }

    # v1 = one corridor, so network == corridor (link → corridor → network).
    return {"period": p, "unit": "veh-mi", "corridor": corridor,
            "network": dict(corridor), "links": links_out, "scenario": scenario}
