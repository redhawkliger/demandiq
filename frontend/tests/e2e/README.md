# End-to-end tests

## `s1_s8.spec.mjs`

PRD-06 — happy-path S1→S8 + intersection-reorder stress.

### What it covers

1. **Happy path** — project create → 5 intersections + 4 corridor links → S4 bulk-paste (exercising PRD-04 K-suffix tolerance) → S5 defaults → S6 run → S7 override → S8 export. Asserts URL transitions through all 8 sessions; `lastRun.intConverged` keys match seeded int nums; no GEOMETRY-FALLBACK flag on distinct-coord fixture; Excel download with the PRD-02 3-tab schema (`Provenance` / `Combined View` / `Raw Movements`); both PRD-03 corridor-diagram PNGs in the download bundle.
2. **Reorder stress** — 10 ints + completed run → drop int #5 → assert `lastRun` cascaded to `null` AND `/approaches` does not redirect to `/volumes` (the S3↔S4 oscillation trap Frontend flagged at the kickoff).

### Prerequisites

- Vite dev server: `cd frontend && npm run dev` (listens on `localhost:3000`)
- FastAPI backend:   `cd backend  && python3.12 app.py`     (listens on `localhost:8000`)
- `playwright-core` — auto-installed into `/tmp/node_modules` on first run

### Run

```
node frontend/tests/e2e/s1_s8.spec.mjs
```

Wall-clock target: under 60s. Current: ~11s.

### Notes

- Uses system Chrome (`channel: 'chrome'`) — no chrome-headless-shell download required.
- Uses `localhost`, not `127.0.0.1` (the dev server binds IPv6-only on `127.0.0.1`).
- Seeds project state directly into `localStorage` so the test exercises the real flow without slow UI clicks (5 map clicks + 12 movement-cell entries × 10 intersections is not what this test is for — bulk-paste, run, export, and the reorder cascade are).
- If the backend was started before a backend-touching PR shipped, it holds the old code in memory. Restart `app.py` before re-running.
