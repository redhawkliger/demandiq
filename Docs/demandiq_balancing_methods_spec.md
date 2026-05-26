# DemandIQ — Balancing Methods Spec (Conservative + Furness)

**Status:** Math proven in code against Akshaey's hand-worked example. Ready to build.
**Reference implementation:** `balancer_reference.py` (executable spec — port this logic).
**Scope:** This replaces the single-corridor balancer with a two-mode, link-driven engine.

---

## 1. The two methods (user picks via toggle in S5)

Both methods balance a corridor so that, on every link, the upstream intersection's **outflow** in a direction equals the downstream intersection's **approach** in that direction (delta = 0). They differ ONLY in how they adjust volumes to get there.

### Conservative (DemandIQ default)
- Never lets any movement drop below its raw collected value (the floor).
- Mechanism: on each link, identify the LOWER of (upstream outflow, downstream approach) and **raise it up to the higher**, distributing the delta across that side's movements proportional to each movement's share of its side's total.
- Because it only ever ADDS, the floor is automatic — nothing is ever reduced.
- Converges fast (1–3 iterations typical).
- **This is what Akshaey does by hand. It is the default and the reason DemandIQ exists.**

### Furness (standard NCHRP 255)
- Classic proportional balancing: move BOTH sides toward their average.
- No floor — CAN push volumes below raw collected (this is the known red flag).
- Provided as an option for engineers who explicitly want the textbook method or need to match legacy outputs.
- Slower to converge; results differ from Conservative (proven: up to ~75 veh/movement on a 5-intersection corridor).

**The toggle:** S5 setting, default **Conservative**. A hint explains:
> "Conservative (recommended): balanced volumes never fall below collected counts; excess flows into turning movements. Furness: standard proportional averaging; may reduce volumes below collected counts."

---

## 2. Direction movement sets (the heart of the math)

For each balancing direction, two sets matter:
- **Outflow feeders** — movements that leave the intersection heading that direction (through + the two turns that feed it + the U-turn).
- **Approach movements** — movements that arrive at the intersection from that direction (through + its two turns).

| Direction | Outflow feeders (adjustable) | U-turn (counted, NOT adjusted) | Approach movements |
|-----------|------------------------------|-------------------------------|--------------------|
| EB | EBT, SBL, NBR | WBU | EBL, EBT, EBR |
| WB | WBT, NBL, SBR | EBU | WBL, WBT, WBR |
| NB | NBT, EBL, WBR | SBU | NBL, NBT, NBR |
| SB | SBT, WBL, EBR | NBU | SBL, SBT, SBR |

- **EB outflow** = EBT + SBL + NBR + WBU
- **EB approach** = EBL + EBT + EBR
- **Link delta** = downstream approach − upstream outflow. Zero = balanced.

U-turns are included in the outflow SUM (they're real vehicles heading that way) but are NEVER given any of the distributed delta.

---

## 3. The Conservative algorithm (proven)

For each link `(upstream u, downstream d, direction)`:

```
delta = approach(d) − outflow(u)

if delta > 0:                      # downstream wants more than arrives
    # raise UPSTREAM outflow feeders
    total = outflow(u)
    for each feeder k in outflow_feeders[direction]:
        v[u][k] += delta * (v[u][k] / total)
    # U-turn excluded from receiving

else:                              # upstream sends more than downstream takes
    # raise DOWNSTREAM approach movements (the excess turns off / continues here)
    total = approach(d)
    for each move k in approach_moves[direction]:
        v[d][k] += |delta| * (v[d][k] / total)
```

Iterate over all links until `max |delta| < tol` (or max_iter). Because each step only adds, no movement ever drops below raw → floor is automatic.

**Verified output (Akshaey's example, EB, 3 intersections):**
- Input EBT: 1000 / 1050 / 600
- Conservative result EBT: 1095.2 / 1050 / 857.1; Int3 EBL 100→142.9, EBR 70→100 (the 330-veh excess from the floor-blocked 2→3 link lands in Int 3's approach, split by share)
- Both link deltas = 0, floor intact. **Matches the hand sheet exactly.**

---

## 4. The Furness algorithm

For each link, move both sides to their average:
```
target = (outflow(u) + approach(d)) / 2
scale upstream outflow feeders by target/outflow(u)
scale downstream approach moves by target/approach(d)
```
Iterate to convergence. No floor clamp (the user chose this mode knowing it can dip below raw).

---

## 5. Rounding (both modes)

- Iterate at FULL PRECISION (no rounding mid-loop).
- After convergence: round every value UP to the next multiple of 5, EXCEPT exact-zero movements stay 0.
- Then run ONE reconciliation pass (re-balance once) so rounding doesn't leave small residual deltas, and re-round the touched values.

---

## 6. Chain detection (shared by both modes)

Links carry a direction. Group links into chains: links are in the same chain if they share an intersection AND have the same direction. EB/WB links form EB/WB chains; NB/SB links form NB/SB chains. A shared node participates in multiple chains independently.

The solver walks every link (across all chains) each iteration until global convergence. Orphan intersections (no links) pass through unchanged and get a QC flag.

---

## 7. Known edge cases (MUST handle, surfaced in testing)

1. **Shared-movement interference (branching networks).** Some movements belong to BOTH an approach in one direction AND an outflow feeder in another. Example: EBL is in EB-approach AND in NB-outflow. If an EB chain and an NB chain both adjust EBL, they can interfere — fixing one re-opens the other. Mitigation: process directions grouped (all EB/WB, then all NB/SB), then re-check global convergence and keep iterating. The global convergence loop catches residual interference; document this and test on a branching network (the Bodger 5↔6 leg + spine is the real test).

2. **Zero-volume side.** If outflow(u) or approach(d) is 0, skip distribution (can't take proportional shares of 0). Flag if a link can't balance because a side is all-zero.

3. **U-turn handling.** WBU etc. counted in outflow totals, never adjusted. Confirm they pass through unchanged.

4. **Max-iter without convergence.** Report `converged: false` + final max delta; never silently return a half-balanced result.

---

## 8. Build sequencing

- **Stage 3a:** chain detection + the shared solver scaffolding + Furness mode (matches existing behavior, network-aware). Verify per-chain on Bodger.
- **Stage 3b:** Conservative mode (port section 3) + the S5 toggle + the hint. Verify against this spec's worked numbers (Int1 EBT 1095.2 etc.).
- Both modes share `balance(raw, links_dir, mode, ...)`. The only branch is the adjustment function.

---

## 9. Output shape (per-chain)

```
{
  "balanced": { "AM": {int_id: {movements}}, "PM": {...} },
  "mode": "conservative" | "furness",
  "chains": [
    { "id", "direction", "intersections": [...],
      "convergence": { "AM": {iterations, converged, final_max_delta},
                       "PM": {...} } }
  ],
  "qc_flags": [ "Int N has no links — not balanced", ... ],
}
```
