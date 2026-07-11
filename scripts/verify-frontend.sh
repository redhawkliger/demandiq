#!/usr/bin/env bash
# scripts/verify-frontend.sh
#
# Frontend verification gate. Run this before committing any frontend change.
#
#   scripts/verify-frontend.sh            # lint only (the exact command CI runs)
#   scripts/verify-frontend.sh --render   # lint + headless-Chrome render check
#
# WHY: two bugs shipped this repo's S6 work because every build-time gate
# (HTTP-200 curl, Vite-transform grep, node-ESM unit tests) passed while the
# actual defect was invisible to them:
#   1. A component read the wrong response field (d.png vs png_base64) and the
#      anchor rendered BLANK — no error, no failing test. Only rendering the app
#      and asserting the <img> has pixels catches that: run with --render.
#   2. A synchronous setState in an effect body was an ESLint error that reached
#      CI red — nothing ran `eslint .` locally in the task loop. The lint gate
#      below is the exact CI command, so it fails here first.
#
# No new dependency: the render check drives system Chrome over the DevTools
# Protocol using Node built-ins (scripts/render-check.mjs).

set -uo pipefail

# Best-effort: clear the Claude Code stdout-capture tmpfs so verbose subcommands
# don't hit ENOSPC (see CLAUDE.md). Harmless / no-op outside that harness.
find /private/tmp/claude-* -name '*.output' -type f -delete 2>/dev/null || true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

RENDER=0
for a in "$@"; do
  case "$a" in
    --render) RENDER=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "verify-frontend: unknown argument '$a'" >&2; exit 2 ;;
  esac
done

# ---- Gate 1: lint (always) — the exact command CI runs (frontend/ npm run lint = eslint .) ----
echo "verify-frontend: running lint (npm run lint) ..."
( cd "$FRONTEND_DIR" && npm run lint )
lint_status=$?
if [ "$lint_status" -ne 0 ]; then
  echo "verify-frontend: LINT FAILED (exit $lint_status)" >&2
  exit "$lint_status"
fi
echo "verify-frontend: lint PASS"

# ---- Gate 2: render (on --render) — proves the app actually renders, not just builds ----
if [ "$RENDER" -eq 1 ]; then
  echo "verify-frontend: running render check (headless Chrome) ..."
  node "$REPO_ROOT/scripts/render-check.mjs"
  render_status=$?
  if [ "$render_status" -ne 0 ]; then
    echo "verify-frontend: RENDER FAILED (exit $render_status)" >&2
    exit "$render_status"
  fi
  echo "verify-frontend: render PASS"
fi

echo "verify-frontend: PASS"
