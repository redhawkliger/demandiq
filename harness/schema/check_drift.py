"""CI drift check: the frozen puzzle schema vs the live frontend source.

`harness/schema/project.schema.json` was hand-derived from the frontend's
store + balance-payload code at a known git SHA. A frontend refactor that
renames or reshapes any of those fields would silently invalidate every
puzzle the Examiner produces — so this script re-checks that each source
marker the schema was derived from still exists, and fails the build loudly
when one disappears.

Markers are exact substrings of specific frontend files. This intentionally
checks the SOURCE (what the schema was derived FROM), not the schema file:
schema edits are reviewed in PRs; silent frontend drift is what slips through.

Run from anywhere: python harness/schema/check_drift.py
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# file (repo-relative) → markers that must all be present verbatim
MARKERS = {
    'frontend/src/store/projectStore.js': [
        # the persistence key the puzzle is written under
        "const STORAGE_KEY = 'demandiq:project'",
        # link shape (fromId/toId reference intersection.id, not num)
        "{ id: 'lnk_<uuid>', fromId, toId, direction: 'EB/WB'|'NB/SB',",
        # canonical approach shape
        "export const defaultApproach = () => ({ exists: true, lanes: [{ movement: 'T' }], stopControlled: false })",
        # balancing defaults consumed by buildPayload
        "linkResolution: cur.linkResolution ?? 'larger'",
        "convergenceThreshold: cur.convergenceThreshold ?? 0.01",
        "maxIterations: cur.maxIterations ?? 500",
        "linkBalanceModes: { ...defaultLinkModes, ...(cur.linkBalanceModes ?? {}) }",
        # per-cell volume shape
        "periodVols[movement] = { value, _source: source }",
    ],
    'frontend/src/sessions/S6_RunAnalysis.jsx': [
        # the exact payload fields the UI sends to /balance-nchrp
        "unbalanced_volumes: { AM: stripVols('AM'), PM: stripVols('PM') }",
        "link_resolution_method: balancing.linkResolution ?? 'larger'",
        "tolerance: balancing.convergenceThreshold ?? 0.5",
        "const res = await fetch('/api/balance-nchrp', {",
        # buildPayload strips {value,_source} cells down to bare numbers
        "if (cell?.value !== null && cell?.value !== undefined && cell?.value !== '') {",
    ],
}


def main():
    failures = []
    for rel, markers in MARKERS.items():
        path = REPO / rel
        if not path.exists():
            failures.append(f'{rel}: FILE MISSING')
            continue
        src = path.read_text()
        for m in markers:
            if m not in src:
                failures.append(f'{rel}: marker not found: {m!r}')
    if failures:
        print('SCHEMA DRIFT — the frontend no longer matches the shape')
        print('harness/schema/project.schema.json was derived from:')
        for f in failures:
            print(f'  ✗ {f}')
        print('\nRe-derive the schema against the current frontend, update')
        print('project.schema.json + these markers, and bump the recorded SHA.')
        return 1
    print(f'schema drift check OK — {sum(len(m) for m in MARKERS.values())} markers present')
    return 0


if __name__ == '__main__':
    sys.exit(main())
