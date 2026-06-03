"""
DemandIQ Forecasting — Module 5: NCHRP 255 link/approach refinement.

Refines model forecasts against observed counts at the LINK/approach level (not
turn level — that's Pass 1). For each matched leg, per period, it combines the
balanced base-year count with the model's base and future directional volumes to
produce a refined future approach total (inbound = row target) and exit total
(outbound = column target) for Pass 1.

PURE PYTHON — no geo deps (geo boundary is the ingest line). Operates on matcher
output, the two NetworkLayers, and the existing balanced TMCs.

Method policy (locked with Akshaey, driven by a verified data fact):
  SANDAG `*_flow` fields are PERIOD volumes (total_flow == Σ of the 10 period
  flows, exactly) while DemandIQ counts are PEAK-HOUR. So:
    - RATIO  F = C × (Mf / Mb)        — time-base-invariant; the operative method.
    - DIFF   F = C + K × (Mf − Mb)    — needs an engineer peak-hour factor K to be
                                        dimensionally valid; computed only when K
                                        is supplied, never silently wrong.
    - COMBINED = ½(ratio + diff)      — likewise gated on K.
  Default method is 'ratio'. Difference/Combined are exposed on drill-in once K
  is provided.

Count totals reuse balancer.DIRECTION_SPEC so the inbound (approach) and outbound
(exit) movement sets are single-sourced with the S6 balancer.
"""

from balancer import DIRECTION_SPEC

# ── Tuning knobs (revisit after the first real corridor pass) ─────────────────
# Flag when the model growth factor Mf/Mb exceeds this — usually a tiny Mb
# inflating the ratio rather than real growth.
REFINE_GROWTH_FACTOR_MAX = 4.0
# Flag when ratio and difference (K supplied) disagree by more than this fraction
# of the larger — the two methods telling different stories warrants a drill-in.
METHOD_DIVERGENCE_THRESHOLD = 0.5

APPROACHES = ("NB", "SB", "EB", "WB")
# Approach direction → the direction traffic EXITS the same physical leg.
OPPOSITE = {"NB": "SB", "SB": "NB", "EB": "WB", "WB": "EB"}


def _sum(counts, movements):
    return sum(float(counts.get(m, 0) or 0) for m in movements)


def _refine_one(count_base, model_base, model_future, *,
                peak_hour_factor, method, growth_factor_max):
    """NCHRP 255 refinement for one directional total (inbound or outbound)."""
    C, Mb, Mf = float(count_base), float(model_base), float(model_future)
    flags = []

    growth = (Mf / Mb) if Mb > 0 else None
    ratio = (C * growth) if growth is not None else None
    if peak_hour_factor is not None:
        difference = C + peak_hour_factor * (Mf - Mb)
        combined = 0.5 * (ratio + difference) if ratio is not None else difference
    else:
        difference = None
        combined = None

    if Mb <= 0:
        # Ratio undefined (model shows no base volume) — hold at the count; the
        # model carries no usable growth signal for this leg.
        flags.append({
            "code": "REFINE-MODEL-ZERO-BASE",
            "message": f"model base volume is 0 — ratio undefined; held at count {C:.0f}.",
        })
        return {
            "count_base": C, "model_base": Mb, "model_future": Mf,
            "growth_factor": None, "ratio": None, "difference": difference,
            "combined": combined, "refined": C, "method": "held-flat",
            "status": "held-flat", "flags": flags,
        }

    # Mb > 0 — pick the requested method, falling back to ratio when a method
    # needs K but none was supplied.
    if method == "ratio":
        selected, sel_method = ratio, "ratio"
    elif method in ("difference", "combined"):
        avail = difference if method == "difference" else combined
        if avail is None:
            selected, sel_method = ratio, "ratio"
            flags.append({
                "code": "REFINE-NO-K",
                "message": f"{method} requested but no peak_hour_factor — fell back to ratio.",
            })
        else:
            selected, sel_method = avail, method
    else:
        selected, sel_method = ratio, "ratio"

    if growth > growth_factor_max:
        flags.append({
            "code": "REFINE-GROWTH-OUTLIER",
            "message": (f"model growth factor {growth:.1f}× exceeds "
                        f"{growth_factor_max:.1f}× — verify the model volumes."),
        })
    if ratio is not None and difference is not None:
        denom = max(abs(ratio), abs(difference), 1.0)
        if abs(ratio - difference) / denom > METHOD_DIVERGENCE_THRESHOLD:
            flags.append({
                "code": "REFINE-METHOD-DIVERGENCE",
                "message": (f"ratio ({ratio:.0f}) and difference ({difference:.0f}) "
                            f"disagree by >{METHOD_DIVERGENCE_THRESHOLD:.0%} — drill in."),
            })

    refined = selected
    if refined < 0:
        flags.append({
            "code": "REFINE-NEGATIVE-CLAMP",
            "message": f"{sel_method} forecast {refined:.0f} < 0 — clamped to 0.",
        })
        refined = 0.0

    return {
        "count_base": C, "model_base": Mb, "model_future": Mf,
        "growth_factor": round(growth, 4), "ratio": ratio,
        "difference": difference, "combined": combined,
        "refined": refined, "method": sel_method, "status": "refined", "flags": flags,
    }


def _absent_leg():
    return {"status": "absent", "link_id": None, "inbound": None,
            "outbound": None, "flags": []}


def _pending_leg(link_id, reason, message):
    return {"status": "pending", "reason": reason, "link_id": link_id,
            "inbound": None, "outbound": None,
            "flags": [{"code": "REFINE-PENDING", "message": message}]}


def refine_corridor(
    match_results,
    base_layer,
    horizon_layer,
    balanced_tmcs,
    period,
    *,
    peak_hour_factor=None,
    method="ratio",
    growth_factor_max=REFINE_GROWTH_FACTOR_MAX,
):
    """Refine every matched leg of every intersection for one period.

    Args:
        match_results: output of matcher.match_network_to_legs (matched on BASE).
        base_layer / horizon_layer: NetworkLayers (same link_id set, per ingest's
            overlap check).
        balanced_tmcs: {int_num: {movement: value}} — the existing balanced TMCs
            for THIS period (the Q5 handoff). Counts are peak-hour.
        period: a contract.Period selecting the model flow period (Period.AM/PM).
        peak_hour_factor: optional K (period→peak-hour). Enables difference/
            combined; ratio ignores it (growth factor is K-invariant).
        method: 'ratio' (default/operative) | 'difference' | 'combined'.

    Returns:
        list of per-intersection dicts:
          { intersection_num, period, snapped_node,
            approaches: { "NB": { status: bound|pending|absent, link_id,
                                  inbound: {...} | None,    # row target
                                  outbound: {...} | None,   # column target
                                  flags: [...] }, ... } }
        Each inbound/outbound dict carries count_base, model_base, model_future,
        growth_factor, ratio, difference, combined, refined, method, status.
    """
    base_idx = {lk.link_id: lk for lk in base_layer.links}
    horizon_idx = {lk.link_id: lk for lk in horizon_layer.links}

    out = []
    for mr in match_results:
        num = mr["intersection_num"]
        node = mr["snapped_node"]
        counts = balanced_tmcs.get(num, {}) or {}
        approaches = {}

        for d in APPROACHES:
            leg = mr["legs"].get(d) or {"status": "unmatched"}
            mstatus = leg.get("status")

            if mstatus == "absent":
                approaches[d] = _absent_leg()
                continue
            if mstatus in ("unmatched", "ambiguous"):
                approaches[d] = _pending_leg(
                    leg.get("link_id"), mstatus,
                    f"leg {d} is {mstatus} in the matcher — confirm the link before refining.")
                continue

            link_id = leg["link_id"]
            base_link = base_idx.get(link_id)
            horizon_link = horizon_idx.get(link_id)
            if base_link is None or horizon_link is None:
                approaches[d] = _pending_leg(
                    link_id, "no-horizon-twin",
                    f"link {link_id} has no twin in the {'base' if base_link is None else 'horizon'} "
                    "network — cannot read model growth.")
                continue

            # Inbound (approach / row target) and outbound (exit / column target).
            try:
                mb_in = base_link.inbound_to(node).get(period, 0.0)
                mf_in = horizon_link.inbound_to(node).get(period, 0.0)
                mb_out = base_link.outbound_from(node).get(period, 0.0)
                mf_out = horizon_link.outbound_from(node).get(period, 0.0)
            except ValueError:
                approaches[d] = _pending_leg(
                    link_id, "node-mismatch",
                    f"link {link_id} is not incident to node {node} in both networks "
                    "— ID likely reused across model series.")
                continue

            c_in = _sum(counts, DIRECTION_SPEC[d]["approach"])
            out_dir = OPPOSITE[d]
            # Exclude the U-turn (outflow_u): the Pass 1 IPF matrix skips U-turn
            # cells (they pass through unchanged per the S6 convention), so a
            # column can only sum to the non-U exit movements. Matches
            # balancer.intersection_targets, which also omits outflow_u — keeping
            # the refined column target reachable by the IPF.
            c_out = _sum(counts, DIRECTION_SPEC[out_dir]["outflow"])

            kw = dict(peak_hour_factor=peak_hour_factor, method=method,
                      growth_factor_max=growth_factor_max)
            approaches[d] = {
                "status": "bound", "link_id": link_id,
                "inbound": _refine_one(c_in, mb_in, mf_in, **kw),
                "outbound": _refine_one(c_out, mb_out, mf_out, **kw),
                "flags": [],
            }

        out.append({
            "intersection_num": num,
            "period": period.value,
            "snapped_node": node,
            "approaches": approaches,
        })

    return out
