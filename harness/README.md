# DemandIQ Examiner (v1) — closed-loop known-answer test harness

All-night, unattended, end-to-end testing of the real DemandIQ balance
pipeline against constructed ground truth. Per run: generate a perfectly
balanced corridor (**answer key**) → perturb it realistically (**puzzle**) →
push the puzzle through the real `/balance-nchrp` endpoint the way the UI
does → grade the output against the key → document → next seed. Forever.

## Run it

```bash
# backend must be up on :8000
cd backend && python3.12 app.py &

# all-night loop (caffeinate keeps the laptop awake while it runs)
caffeinate -i python3.12 -m harness.loop

# reproduce one run from its seed — every failure reproduces exactly
python3.12 -m harness.run_one --seed 1234
```

Optional: `ANTHROPIC_API_KEY` enables LLM failure narration (post-verdict
only). Without it, failures get a deterministic fallback narration — the
verdict pipeline is identical either way.

Optional: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` enable Telegram
notifications (`notify.py`) — exactly four message types: a checkpoint every
50 runs, first-occurrence-only new failure signatures, loop death (the loop
itself crashed, distinct from `pipeline-crash` which it survives), and a
morning summary with trend vs the previous session (sent at loop stop or
7:00 AM, whichever first). With the env vars unset the notifier is a silent
no-op; a notify error is logged to `harness_errors.log` and never raised —
notification reads results, never influences them.

## Where results land

| Path | What |
|---|---|
| `results.csv` | one row per run (seed, verdict, category, signature, worst GEH) |
| `summary.md` | pass rate + severity-ranked histogram + fix-first list (10-second digest at top) |
| `failures/<run_id>/` | full case file per FAIL: report.md, evidence.md, puzzle/key/output/grade JSON, repro command — kept forever |
| `failures/index.csv` | failure ledger deduped by signature (300 hits of one bug = one row) |
| `runs/<run_id>/` | per-run artifacts; PASS artifacts pruned to the latest 50 |
| `knowledge/known-behaviors.md` | correct-but-surprising NCHRP behaviors — read before "fixing" anything |
| `knowledge/lessons.md` | append-only; the Mechanic (Phase 2) writes here |
| `harness_errors.log` | harness-side exceptions (loop always continues) |

## Firewalls (structural)

1. **No LLM in the numerical trust path.** Puzzler, probes, Grader,
   Scorekeeper are seeded/deterministic code. The only LLM call is
   `narrator.py`, invoked strictly after the verdict is decided, and it can
   only write prose + refine an `unknown` category.
2. **`balancer.py` and the frontend are never modified.** All harness code
   lives under `harness/`; the independent math lives in `nchrp_math.py`
   (re-derived from the spec, never imported from the tool).
3. **Module boundary on the Operator.** `operate.py` receives only the
   puzzle — it has no import path to the answer key or perturbation log.
4. **Every failure reproduces from its seed** (`run_one.py`); one
   `random.Random(seed)` drives the entire generation.

## What a run checks

Tier 1 hard invariants (any failure = FAIL): every intersection converged;
recomputed link conservation |delta| ≤ 0.5 veh on Full links; no phantom
movement on an absent leg; no balanced value in (0, 5). Probes (every cycle):
telemetry truthfulness (recompute `link_conservation` + `movements_review`
from the response), idempotency (two identical POSTs → byte-identical),
orientation sweep (E–W vs N–S rotations must match exactly), S8
`/corridor-diagram` export (real PNGs, segment labels drawn). Tier 2: GEH per
movement vs the answer key — PASS ≤ 5, MARGINAL ≤ 10, FAIL > 10.

Note on `finalResidual`: it is computed pre-rounding against Level-1 targets
not present in the response, so it cannot be independently recomputed without
re-running the tool's own code (which would verify nothing). The
truthfulness probe therefore exactly recomputes the response's other
telemetry surfaces instead. See `knowledge/known-behaviors.md`.

## Determinism precondition (satisfied 2026-07-10)

Before the harness was built, one fixed imbalanced corridor was POSTed to
`/balance-nchrp` 50×: all 50 responses byte-identical under canonical JSON
(8–12 IPF iterations per intersection, so the float path was exercised).

## CI

`harness/schema/check_drift.py` re-checks the frontend source markers the
frozen `project.schema.json` was derived from — frontend schema drift breaks
the build, not the harness's honesty. `harness/tests/` runs the detector
fail-then-pass suite offline (no backend needed).

## Non-goals (v1)

No Mechanic/auto-fix (Phase 2). No UI driving. No golden cases yet
(`goldens/` hook is ready). No ±30% tier, T-intersections, missing
legs/movements, AM+PM dual-period consistency checks, or forecasting
coverage.
