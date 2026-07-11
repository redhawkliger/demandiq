# CLAUDE.md

Project-level notes for working in this repo with Claude Code.

## Environment: harness tmpfs ENOSPC (Bash output failures)

**Symptom.** Bash tool calls intermittently fail with:

> the temp filesystem at `/private/tmp/claude-502/.../tasks` is full (0MB free).
> The child process's stdout/stderr writes failed with ENOSPC.

The real disk has space (`df` shows plenty free). The harness captures each
command's stdout/stderr to a small tmpfs that fills as `.output` files
accumulate over a long session, so commands that print more than a few bytes
start failing. Commands that produce **no** stdout still run fine.

**Workarounds**, in order of preference:

1. **Route output to a file on the main disk, then Read it.** The harness sees
   empty stdout (no tmpfs write), and the Read tool is unaffected:
   ```bash
   { cmd1; cmd2; } > /Users/Ak47/dq_scratch.txt 2>&1; true
   ```
   then Read `/Users/Ak47/dq_scratch.txt`. Delete the scratch file when done.
   This is the reliable approach for anything verbose (`gh run watch`, test
   suites, builds, multi-line greps).

2. **Clear the accumulated output files** (produces no stdout, so it runs even
   when the tmpfs is full):
   ```bash
   find /private/tmp/claude-502 -name '*.output' -type f -delete 2>/dev/null; true
   ```
   This also deletes the current command's own output file, so the tool result
   shows a benign `ENOENT ... could not be read` — the command still executed.

3. A no-output command such as `true` always works; use it to confirm recovery.

**Prefer dedicated tools over Bash** for file reads/edits/searches — Read, Write,
and Edit never hit this tmpfs; only Bash stdout capture does.

## Frontend verification gate (REQUIRED before committing frontend changes)

Run **`scripts/verify-frontend.sh`** and make it pass before you commit any
frontend change. It's the single-line gate; do not hand-roll browser drivers or
skip it.

- **Every frontend task** → `scripts/verify-frontend.sh` (runs `npm run lint`, the
  exact `eslint .` CI runs). Must exit 0 before commit.
- **Tasks that touch a component's render, or a fetch/effect** →
  `scripts/verify-frontend.sh --render` (also renders the app in headless Chrome,
  seeds a synthetic project, and asserts the target actually rendered — root
  present, the anchor `<img>` has real pixels, zero console errors). Must exit 0.
- Redirect its output to a scratch file then Read it (tmpfs, above). The `--render`
  mode needs the Vite dev server (:3000) and backend (:8000) running; it fails
  loudly with start instructions if either is down.
- No dependency: `--render` drives system Chrome over the DevTools Protocol via
  Node built-ins (`scripts/render-check.mjs`). Defaults target the S6
  `/review-movements` view; override with `--route/--root/--image`, and for routes
  gated on extra data or an interaction, `--seed <file>` / `--click "<text>"`.

**Diagram-route coverage (run the one matching the view you touched).** All flags
after `--render` pass through to the render check. Each renders the real diagram
and asserts the `<img>` has pixels + zero console errors:

```bash
# S6 Review Movements — anchor diagram (default seed, eager)
scripts/verify-frontend.sh --render

# S7 Results — per-intersection diagram cards (default seed, eager)
scripts/verify-frontend.sh --render --route /results \
  --root .di-s7 --image ".di-s7-card__img"

# F4 Future Results — existing+forecast diagrams. Needs a forecasting.results
# slice the default seed lacks, or it renders the "Run the forecast first" empty
# state and FALSELY passes — so seed it:
scripts/verify-frontend.sh --render --route /forecast/results \
  --root .di-fc --image ".di-fc-fig img" --seed scripts/fixtures/forecast.json

# S8 Export — corridor line diagram, which only renders after a button click:
scripts/verify-frontend.sh --render --route /export \
  --root .di-s8 --image ".di-s8-corridor-preview__fig img" --click "Preview AM + PM"
```

If you add a new diagram route, add its invocation here so nobody has to
rediscover its seed/interaction gating. All four above are proven fail-then-pass:
breaking the response field read (`png_base64` → `png`) turns each one red.

**Why this exists (do not remove the gate).** Two bugs shipped to CI/merge in the
S6 work because every build-time check passed while the real defect was invisible
to them — none ran lint or rendered the app:
1. `IntersectionDiagram` read `d.png` but the endpoint returns `png_base64` → the
   fetch succeeded, the value was `undefined`, the anchor rendered **blank** with
   no error and no failing test. HTTP-200 curls, Vite-transform greps, and
   node-ESM unit tests all passed. Only rendering the app and asserting the
   `<img>` has pixels catches this — that's the `--render` gate.
2. A synchronous `setState` in an effect body was an `eslint` **error**
   (`react-hooks/set-state-in-effect`) that reached CI red because nothing ran
   `eslint .` locally in the task loop. The lint gate is that exact command, run
   before commit instead of after push.
