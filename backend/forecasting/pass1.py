"""
DemandIQ Forecasting — Module 6: Future Furness Pass 1 (per-intersection IPF).

Distributes the refined future approach (inbound = row) and exit (outbound =
column) totals from module 5 into a future 4×4 turning-movement matrix per
intersection, seeded by the base-year turn pattern. NCHRP 765 turn forecasting:
future turns = base pattern Fratar-factored to the future margins.

PURE GLUE — no new solver. The IPF engine, matrix builders, and direction
convention are reused unchanged from the S6 balancer:
    furness_intersection, _build_matrix, _extract_matrix,
    CELL_MOVEMENT, LEG_INDEX, LEG_IN_DIR, DIRECTION_SPEC.
Reusing furness_intersection means inheriting its convergence guarantees and its
matrix-stability handling of imbalanced targets — independent ratio refinement
gives Σinbound ≠ Σoutbound at a node, and the solver reports that as
final_residual rather than hiding it. Pass 2 (balance_nchrp) reconciles the
imbalance across intersections.

Known IPF property (documented, acceptable for v1): a zero seed cell stays zero —
IPF cannot create flow in a movement the base count shows as 0 (0 × factor = 0).
A banned movement becoming allowed in the future is engineer-override territory
(a later editor module), not Pass 1.

Pending legs (matcher unmatched/ambiguous, or no horizon twin) carry no refined
target. Default: HOLD FLAT (future = base, no growth) with a prominent flag, so
Pass 1 always produces a complete matrix. An engineer manual target overrides it.
"skip from Pass 2" stays where it belongs — Pass 2's link mode='None'.

U-turns are not part of the 4×4 (the diagonal cells are skipped); they pass
through from the base unchanged, per the S6 convention.
"""

from balancer import (
    DIRECTION_SPEC,
    LEG_INDEX,
    LEG_IN_DIR,
    _build_matrix,
    _extract_matrix,
    furness_intersection,
)

# Approach direction → the direction traffic EXITS the same physical leg.
OPPOSITE = {"NB": "SB", "SB": "NB", "EB": "WB", "WB": "EB"}
U_TURNS = ("NBU", "SBU", "EBU", "WBU")

# Reuse the balancer's convergence defaults — the whole point of reusing
# furness_intersection is inheriting its guarantees; don't fork them.
DEFAULT_TOL = 0.5
DEFAULT_MAX_ITER = 500


def _sum(vols, movements):
    return sum(float(vols.get(m, 0) or 0) for m in movements)


def forecast_intersection(base_tmc, refined_approaches, *, manual_targets=None,
                          tol=DEFAULT_TOL, max_iter=DEFAULT_MAX_ITER):
    """Fit one intersection's future turning-movement matrix.

    Args:
        base_tmc: {movement: base_vol} — the base-year balanced TMCs (the seed
            pattern; same source as refinement's count C).
        refined_approaches: the 'approaches' dict from refine_corridor for this
            intersection: {D: {status, link_id, inbound:{...}|None, outbound:{...}|None}}.
        manual_targets: optional {D: {"inbound": x, "outbound": y}} applied to
            pending legs before IPF.
        tol / max_iter: passed to furness_intersection.

    Returns:
        (future_tmc, meta) where future_tmc is {movement: future_vol} (12 turn
        movements + any base U-turns passed through) and meta is
        {converged, iterations, residual, flags}.
    """
    manual_targets = manual_targets or {}
    seed = _build_matrix(base_tmc)
    row_targets = [None] * 4
    col_targets = [None] * 4
    present = [False] * 4
    flags = []

    for leg_name, idx in LEG_INDEX.items():        # S→0, N→1, W→2, E→3
        approach = LEG_IN_DIR[idx]                  # idx0→NB, 1→SB, 2→EB, 3→WB
        leg = refined_approaches.get(approach)
        if leg is None or leg.get("status") == "absent":
            continue                                # 3-leg T: row/col masked

        present[idx] = True
        status = leg.get("status")
        if status == "bound":
            row_targets[idx] = leg["inbound"]["refined"]
            col_targets[idx] = leg["outbound"]["refined"]
        else:                                       # pending
            mt = manual_targets.get(approach)
            if mt is not None:
                row_targets[idx] = float(mt["inbound"])
                col_targets[idx] = float(mt["outbound"])
                flags.append({
                    "code": "PASS1-PENDING-MANUAL",
                    "message": f"{approach} leg pending — used engineer manual target.",
                })
            else:
                # Hold flat: future = base leg total (no growth). Outbound omits
                # the U-turn, matching the refined column target.
                row_targets[idx] = _sum(base_tmc, DIRECTION_SPEC[approach]["approach"])
                col_targets[idx] = _sum(base_tmc, DIRECTION_SPEC[OPPOSITE[approach]]["outflow"])
                flags.append({
                    "code": "PASS1-PENDING-HELD-FLAT",
                    "message": (f"{approach} leg pending ({leg.get('reason', 'unbound')}) "
                                "— held flat (no growth applied); engineer review needed."),
                })

    fitted, converged, iters, residual = furness_intersection(
        seed, row_targets, col_targets, present, tol=tol, max_iter=max_iter)

    future = _extract_matrix(fitted)
    # U-turns are outside the 4×4 — carry the base value through unchanged.
    for u in U_TURNS:
        if u in base_tmc:
            future[u] = float(base_tmc[u])

    return future, {
        "converged": converged,
        "iterations": iters,
        "residual": round(float(residual), 4),
        "flags": flags,
    }


def forecast_corridor(refinement_results, base_tmcs, *, manual_targets=None,
                      tol=DEFAULT_TOL, max_iter=DEFAULT_MAX_ITER):
    """Run Pass 1 for every intersection of one period.

    Args:
        refinement_results: list from refine_corridor (one per intersection).
        base_tmcs: {int_num: {movement: base_vol}} — the period's balanced TMCs.
        manual_targets: optional {int_num: {direction: {"inbound", "outbound"}}}.
        tol / max_iter: passed through to the IPF.

    Returns:
        (futures, meta):
            futures: {int_num: {movement: future_vol}} — feeds Pass 2 as
                     raw_volumes (full precision; Pass 2 rounds).
            meta:    {int_num: {period, converged, iterations, residual, flags}}.
    """
    manual_targets = manual_targets or {}
    futures = {}
    meta = {}
    for rr in refinement_results:
        num = rr["intersection_num"]
        base = base_tmcs.get(num, {}) or {}
        future, m = forecast_intersection(
            base, rr["approaches"], manual_targets=manual_targets.get(num),
            tol=tol, max_iter=max_iter)
        futures[num] = future
        meta[num] = {"period": rr["period"], **m}
    return futures, meta
