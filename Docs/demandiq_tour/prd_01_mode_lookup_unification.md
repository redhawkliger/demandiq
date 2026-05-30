# PRD-01 — Mode-lookup unification

**Status:** ready to build
**Owner:** frontend
**Order:** 1 of 6 (prereq for PRD-02 + PRD-06)
**Est:** ~½ day

## Why

S6 `ResolvedTargets` and S7 `finalVolumeFor` both need to resolve a link's mode (Full / Land Use / None) for a given pair of intersections, but they do it via different paths:

- **S6** (`S6_RunAnalysis.jsx:589–672` — `modeFor` inside `ResolvedTargets`) hand-rolls a composite `${fromId}__${toId}` key against `balancing.linkBalanceModes`, then falls back to scanning `store.links`.
- **S7** (`S7_ReviewDrops.jsx:52–56` — `finalVolumeFor`) is the source of truth for override-shadowed *volumes* but doesn't expose mode; mode-aware logic lives separately.

At scale these will silently diverge — when an engineer changes a mode in S5 between runs but hasn't re-run, S6's resolved-targets card and S7's flow map will report different effective modes for the same link. The Architect made this the gating push-back at the kickoff.

## What (scope in / out)

**In:**
- One exported helper in `projectStore.js`: `resolveLinkMode(fromId, toId): 'Full' | 'Land Use' | 'None'`.
- Refactor `S6 ResolvedTargets.modeFor` to delegate to the helper.
- Audit S7 for any inline mode reads and route them through the helper.
- The helper handles both directions (a→b and b→a) and the linkBalanceModes key scheme + store.links fallback inside it — once, in one place.

**Out:**
- No UI change. Modes render exactly as today.
- No store-shape migration. `linkBalanceModes` keys stay as they are.
- No change to backend or `lastRun` shape.

## How

- Add `resolveLinkMode` in `projectStore.js` (near the link helpers around line 355–401).
- Replace `S6_RunAnalysis.jsx:589–672` `modeFor` with `import { resolveLinkMode } from '../store/projectStore'` + a one-line call.
- Grep `frontend/src/sessions/` for `linkBalanceModes` and `.mode` reads on store links; route any non-helper reads through `resolveLinkMode`.

## Acceptance criteria

- [ ] `projectStore.js` exports `resolveLinkMode(fromId, toId)` with explicit JSDoc.
- [ ] `S6_RunAnalysis.jsx:589–672` no longer contains an inline `modeFor` body — uses the helper.
- [ ] `grep -n "linkBalanceModes\[" frontend/src/sessions/` returns zero hits (all reads go through the helper).
- [ ] On the Bodger fixture: S6 ResolvedTargets and S7 flow map show identical modes for every link, pre- and post-refactor (visual diff or test fixture snapshot).
- [ ] Lint clean on touched files.
- [ ] No new dependencies introduced.

## Risks / open

- If S5 also reads `linkBalanceModes` directly for *editing*, leave that alone — the helper is for *reading the effective mode*, not for mutating the config.
- The helper must return a sane default when an intersection pair has no recorded mode (default `'Full'`, matching today's S6 fallback).
