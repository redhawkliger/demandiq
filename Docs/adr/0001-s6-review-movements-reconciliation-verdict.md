# ADR 0001 — S6 Review Movements: reconciliation verdict is a read-only function of solver output

Status: Accepted (2026-06-08)

## Context

The S6 "Review Movements" detail view (per-intersection inspection of balanced
turning movements) shows a flow-reconciliation verdict — "does this intersection's
flow balance?" — alongside the line diagram. The locked design originally framed
this as an `in = out` check displaying two totals with a ✓/⚠ verdict.

Investigation of the NCHRP balancer (`backend/balancer.py`) surfaced a correctness
trap. The obvious frontend implementation — sum the balanced movements entering the
intersection vs. exiting — is **wrong in two ways**:

1. **It is a tautology.** Total inbound and total outbound at an intersection are
   two summations of the *same* balanced matrix total (`balancer.py:516–524`), so
   they are *always* equal regardless of solver health. "1,840 = 1,840 ✓" renders
   `X = X` — a check that structurally cannot fail.

2. **It can contradict the solver.** `intConverged` is **matrix stability**
   (max inter-iteration cell delta `< tol`, `balancer.py:557–565`), *not* an
   in-vs-out balance. A naive total-in/total-out check would show ✓ even when
   `intConverged` is `false` — a visible self-contradiction between the page and
   the engine it reports on.

The honest reconciliation magnitude already exists and is already emitted:
`finalResidual` = `max` over present legs of `|balanced leg margin − target leg
margin|`, **in vehicles** (`balancer.py:516–524`, emitted `app.py:409–412`). It is
the worst-case leg that is off the volume it was supposed to carry.

`intConverged` and `finalResidual` are computed over the **12 standard movements
only**; U-turns are excluded from the matrix and pass through unchanged
(`balancer.py:13–19, 81, 800`).

## Decision

**The reconciliation verdict is a pure, read-only function of two solver outputs
already present in `lastRun` — `intConverged` and `finalResidual`. The frontend
NEVER re-derives it by summing movements.** (Constraint-B resolution, Path (a).)

```
gap       = round(lastRun.finalResidual[period][intNum])   // vehicles, from solver
converged = lastRun.intConverged[period][intNum]           // solver's own flag

verdict =
  !converged          -> "⚠ did not converge"
  converged && gap===0 -> "✓ balanced"
  converged && gap>0   -> "⚠ worst leg off target by {gap} veh"
```

Because the verdict *reads* `intConverged`, it can never disagree with the solver.
Because the magnitude is the solver's own residual, the frontend never replicates
the U-turn / stub-target / `DIRECTION_SPEC` leg-summation logic.

Locked sub-decisions:

1. **Drop the twin in/out totals.** Show only the single verdict line. Two
   always-equal numbers imply a pass/fail comparison that is not happening; the
   engineer must not read them instead of the real verdict.

2. **Defer per-leg localization (Option A).** On a gap, show "⚠ worst leg off
   target by N veh" without naming the leg. The API emits only the `max` residual,
   not per-leg residuals. Frontend per-leg re-derivation (Option C) is **rejected**
   — it reintroduces the exact fragility this ADR exists to prevent and can
   disagree with the solver. Naming the leg is a Phase-2 add only if engineers ask;
   it would require emitting per-leg residuals from `balance_nchrp`
   (`balancer.py:1412–1428`) and a superseding/extending ADR.

3. **Diagram Balanced⇄Changes toggle is free reuse.** `/intersection-diagram`
   (`app.py:435`) already accepts `view_mode ∈ {combined,balanced,unbalanced,delta}`
   and threads it to `render_single_diagram` (`line_diagram.py:488`). Toggle =
   `view_mode:'balanced'` (default) / `'delta'` (Changes). No backend change.

### Must-land pins (small, easy to lose)

- **Modal tolerance value.** The "Details / show the math" modal displays the
  tolerance that actually governs `intConverged` — the per-intersection IPF tol
  **hardcoded `0.01` veh** (`balancer.py:1161`) — **NOT** `config.convergenceThreshold`,
  which is a different (Level-1) value. This is a defend-the-work surface; showing
  the wrong tolerance misrepresents the math it claims to back.

- **Caption wording is exact.** The gap is phrased **"worst leg off its TARGET by
  N veh"**, never **"N veh unaccounted."** The intersection total always reconciles
  (the tautology finding above) — "unaccounted" would reintroduce the lie in words.

## Consequences

**Makes easy:**
- The whole Review Movements view is frontend composition over `lastRun` + reuse of
  existing components (diagram PNG, `MovementSvg`, delta colors, tokens). **No
  backend change for any element**, verdict included.
- The page can never show ✓ while the solver says not-converged; the verdict's
  meaning lives in exactly one place (`ReconciliationCard`'s verdict function) and
  nothing else re-derives it.

**Makes hard (accepted):**
- True per-leg localization ("the NORTH leg is short 30 veh") is not available
  without a backend change; deferred by decision (2).
- The verdict depends on the solver continuing to emit `intConverged` and
  `finalResidual` per intersection per period; a change to those fields breaks the
  contract and must reference this ADR.

## References

- Design context: memory `s6-review-movements-design`; corridor-order rule
  `corridor-order-invariant`.
- Code: `backend/balancer.py` (IPF `furness_intersection` 482–568; convergence
  557–565; residual 516–524; Level-2 tol 1161; movements_review 800–823),
  `backend/app.py` (response shaping 405–419; `/intersection-diagram` 435),
  `backend/line_diagram.py` (`render_single_diagram` 488; `VIEW_MODES` 460).
