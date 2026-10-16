#!/usr/bin/env bash
# Run the full backend test suite. Each file is a standalone runner that
# exits non-zero on failure; we aggregate so one red test fails the suite.
#   cd backend && ./run_tests.sh
# Override the interpreter for environments where it isn't named python3.12
# (e.g. CI runners expose it as `python`):  PYTHON=python ./run_tests.sh
set -u
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3.12}"

TESTS=(
  test_balancer_nchrp
  test_excel_overrides
  test_line_diagram_annotation
  test_line_diagram
  test_e2e_bodger
  test_capture
)

fails=0
for t in "${TESTS[@]}"; do
  echo "──────────────────────────────────────────────────────────"
  echo "▶ $t"
  if ! "$PYTHON" "$t.py"; then
    fails=$((fails + 1))
    echo "✗ $t FAILED"
  fi
done

echo "──────────────────────────────────────────────────────────"
if [ "$fails" -eq 0 ]; then
  echo "ALL SUITES PASSED (${#TESTS[@]} files)"
else
  echo "$fails of ${#TESTS[@]} suite(s) FAILED"
fi
exit "$fails"
