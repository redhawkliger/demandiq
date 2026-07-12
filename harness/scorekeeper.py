"""Scorekeeper — deterministic results recording + failure documentation.

Everything here is plain files a human can read with no tooling:
  harness/results.csv          one row per run
  harness/runs/<run_id>/       per-run artifacts (PASS artifacts prunable)
  harness/failures/<run_id>/   full case file per FAIL — kept forever
  harness/failures/index.csv   the failure ledger, deduped by signature
  harness/summary.md           pass rate, histogram, trends, 10-second digest
"""

import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .grader import CATEGORY_ORDER

HARNESS_ROOT = Path(__file__).parent
RESULTS_CSV = HARNESS_ROOT / 'results.csv'
RUNS_DIR = HARNESS_ROOT / 'runs'
FAILURES_DIR = HARNESS_ROOT / 'failures'
LEDGER_CSV = FAILURES_DIR / 'index.csv'
SUMMARY_MD = HARNESS_ROOT / 'summary.md'

RESULTS_FIELDS = [
    'run_id', 'timestamp', 'seed', 'git_sha', 'n_intersections',
    'orientation', 'perturb_tier', 'tier', 'verdict', 'failure_category',
    'signature', 'worst_geh', 'worst_movement',
]
LEDGER_FIELDS = [
    'signature', 'category', 'count', 'first_seen', 'last_seen',
    'example_run_id', 'status', 'fixed_by_commit',
]

KEEP_PASSED_RUNS = 50
DIGEST_EVERY = 50


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def make_run_id(seed):
    ts = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    run_id = f'{ts}-seed{seed}'
    # Same seed twice within one second (e.g. instant-crash + retry) must not
    # overwrite a forever-kept case file — uniquify with a suffix.
    n = 2
    while (RUNS_DIR / run_id).exists() or (FAILURES_DIR / run_id).exists():
        run_id = f'{ts}-seed{seed}-{n}'
        n += 1
    return run_id


def migrate_results_csv():
    """One-time in-place migration: a results.csv written before difficulty
    tiers existed lacks the 'tier' column. Backfill those rows as Tier A —
    that is literally the configuration they ran. Idempotent; no-op when the
    file is absent or already migrated."""
    if not RESULTS_CSV.exists():
        return
    with open(RESULTS_CSV, newline='') as f:
        header = f.readline().strip().split(',')
    if 'tier' in header:
        return
    rows = _read_csv(RESULTS_CSV)
    for r in rows:
        r['tier'] = 'A'
    with open(RESULTS_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=RESULTS_FIELDS)
        w.writeheader()
        w.writerows(rows)


def _append_csv(path, fields, row):
    new = not path.exists()
    with open(path, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write('\n')


def write_run_artifacts(run_id, artifacts):
    """Persist per-run artifacts to harness/runs/<run_id>/."""
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, obj in artifacts.items():
        _write_json(run_dir / f'{name}.json', obj)
    return run_dir


def record_run(meta, grade, narration, artifacts):
    """Record one completed run: results row, artifacts, and (on FAIL) the
    full case file + ledger update. Regenerates summary.md every run."""
    run_id = meta['run_id']
    run_dir = write_run_artifacts(run_id, artifacts)
    migrate_results_csv()

    worst = grade.get('geh', {})
    row = {
        'run_id': run_id,
        'timestamp': _now_iso(),
        'seed': meta['seed'],
        'git_sha': meta['git_sha'],
        'n_intersections': meta['n'],
        'orientation': meta['orientation'],
        'perturb_tier': meta['tier'],
        'tier': meta.get('difficulty', 'A'),
        'verdict': grade['verdict'],
        # Deterministic category only — the narrator's refinement lives in the
        # case report. Keeps results.csv/ledger rows consistent per signature.
        'failure_category': grade.get('failure_category') or '',
        'signature': grade.get('signature', ''),
        'worst_geh': f"{worst.get('worst', 0.0):.3f}",
        'worst_movement': worst.get('worst_movement', ''),
    }
    _append_csv(RESULTS_CSV, RESULTS_FIELDS, row)

    if grade['verdict'] == 'FAIL':
        _write_case_file(meta, grade, narration, run_dir)
        _update_ledger(row)
    if grade['verdict'] == 'PASS':
        _prune_passed_runs()

    write_summary()
    return row


def _write_case_file(meta, grade, narration, run_dir):
    case_dir = FAILURES_DIR / meta['run_id']
    case_dir.mkdir(parents=True, exist_ok=True)

    for f in run_dir.glob('*.json'):
        shutil.copy2(f, case_dir / f.name)

    failed = [c for c in grade['checks'] if not c['ok']]
    category = grade['failure_category']
    refined = narration.get('category')

    # The difficulty tier is recorded in the case file for repro, but NEVER
    # feeds the signature — the same bug hit in two tiers must stay one
    # ledger row (grader.compute_signature has no tier input).
    difficulty = meta.get('difficulty', 'A')
    repro = f"python -m harness.run_one --seed {meta['seed']}" \
        + (f' --tier {difficulty}' if difficulty != 'A' else '')
    report = [
        f"# Examiner failure — run `{meta['run_id']}`",
        '',
        f"- **Verdict:** {grade['verdict']}",
        f"- **Category:** {category}"
        + (f' (narrator refinement: {refined})' if refined and refined != category else ''),
        f"- **Signature:** `{grade['signature']}`",
        f"- **Seed:** {meta['seed']} · tier {difficulty} · corridor of "
        f"{meta['n']} intersections, {meta['orientation']} orientation, "
        f"±{int(meta['tier'] * 100)}% perturbation",
        f"- **Tool git SHA:** `{meta['git_sha']}`",
        f"- **Worst GEH:** {grade['geh']['worst']:.2f} at {grade['geh']['worst_movement']}",
        '',
        '## Reproduce',
        '```bash',
        repro,
        '```',
        'Deterministic: the (seed, tier) regenerates the identical puzzle and answer key.',
        '',
        '## Narration',
        narration.get('explanation') or '(none)',
        '',
        '## Failed checks',
    ]
    for c in failed:
        report.append(f"- **{c['check']}** ({c['category']}) — "
                      f"{len(c['details'])} finding(s), see evidence.md")
    report += [
        '',
        '## Artifacts',
        '- `puzzle.json` — the exact demandiq:project snapshot fed to the tool',
        '- `answer_key.json` — the perfectly balanced ground truth',
        '- `perturbation_log.json` — every delta applied to build the puzzle',
        '- `tool_output.json` — full /balance-nchrp response (incl. telemetry)',
        '- `grade.json` — every check result + GEH per movement, ranked',
        '- `evidence.md` — expected vs got at the failure point',
        '- `env.txt` — tool git SHA, harness version, timestamp',
        '',
    ]
    (case_dir / 'report.md').write_text('\n'.join(report))

    ev = ['# Evidence — expected vs got', '']
    for c in failed:
        ev.append(f"## {c['check']} ({c['category']})")
        ev.append('')
        for d in c['details']:
            ev.append(f'- {d}')
        ev.append('')
    geh_bad = [r for r in grade['geh']['rows'] if r['geh'] > 5.0]
    if geh_bad:
        ev += ['## GEH per movement (all rows over 5, worst first)', '',
               '| Period | Int | Movement | Key (expected) | Tool (got) | GEH |',
               '|---|---|---|---|---|---|']
        for r in geh_bad:
            ev.append(f"| {r['period']} | {r['int_num']} | {r['movement']} | "
                      f"{r['key']} | {r['tool']} | {r['geh']:.2f} |")
        ev.append('')
    (case_dir / 'evidence.md').write_text('\n'.join(ev))

    (case_dir / 'env.txt').write_text(
        f"tool_git_sha={meta['git_sha']}\n"
        f"harness_version={meta['harness_version']}\n"
        f"timestamp={_now_iso()}\n"
        f"backend_url={meta['base_url']}\n"
    )


def _read_csv(path):
    if not path.exists():
        return []
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def _update_ledger(row):
    FAILURES_DIR.mkdir(parents=True, exist_ok=True)
    rows = _read_csv(LEDGER_CSV)
    now = _now_iso()
    for r in rows:
        if r['signature'] == row['signature']:
            r['count'] = str(int(r['count']) + 1)
            r['last_seen'] = now
            break
    else:
        rows.append({
            'signature': row['signature'],
            'category': row['failure_category'],
            'count': '1',
            'first_seen': now,
            'last_seen': now,
            'example_run_id': row['run_id'],
            'status': 'open',
            'fixed_by_commit': '',
        })
    with open(LEDGER_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        w.writerows(rows)


def _prune_passed_runs():
    """PASS artifacts are prunable — keep only the most recent N. FAIL and
    MARGINAL run dirs are never touched (FAILs also live in failures/)."""
    results = _read_csv(RESULTS_CSV)
    passed = [r['run_id'] for r in results if r['verdict'] == 'PASS']
    for run_id in passed[:-KEEP_PASSED_RUNS]:
        d = RUNS_DIR / run_id
        if d.exists():
            shutil.rmtree(d)


def write_summary():
    results = _read_csv(RESULTS_CSV)
    total = len(results)
    if total == 0:
        return
    ledger = _read_csv(LEDGER_CSV)

    verdicts = {'PASS': 0, 'MARGINAL': 0, 'FAIL': 0}
    tier_stats = {}
    for r in results:
        verdicts[r['verdict']] = verdicts.get(r['verdict'], 0) + 1
        # Rows written before the tier column existed ran the Tier A config.
        t = r.get('tier') or 'A'
        s = tier_stats.setdefault(t, {'PASS': 0, 'MARGINAL': 0, 'FAIL': 0, 'total': 0})
        s[r['verdict']] = s.get(r['verdict'], 0) + 1
        s['total'] += 1
    pass_rate = 100.0 * verdicts['PASS'] / total

    # Severity-ranked failure-category histogram (worst first)
    hist = {}
    for r in results:
        if r['verdict'] == 'FAIL' and r['failure_category']:
            hist[r['failure_category']] = hist.get(r['failure_category'], 0) + 1
    ranked = sorted(hist.items(), key=lambda kv: (
        CATEGORY_ORDER.index(kv[0]) if kv[0] in CATEGORY_ORDER else 99))

    last50 = results[-50:]
    last50_pass = sum(1 for r in last50 if r['verdict'] == 'PASS')

    # MARGINAL-repeat tracker: same movement code recurring as the worst
    # MARGINAL movement — a soft accuracy pattern worth an engineer's eye.
    marg = {}
    for r in results:
        if r['verdict'] == 'MARGINAL' and r['worst_movement']:
            mv = r['worst_movement'].split()[-1]
            marg[mv] = marg.get(mv, 0) + 1
    marg_repeats = {mv: n for mv, n in sorted(marg.items(), key=lambda kv: -kv[1]) if n > 1}

    open_sigs = [r for r in ledger if r['status'] == 'open']
    open_sigs.sort(key=lambda r: (
        CATEGORY_ORDER.index(r['category']) if r['category'] in CATEGORY_ORDER else 99,
        -int(r['count'])))

    lines = [
        '# Examiner summary',
        '',
        '## Digest (10-second read)',
        '',
        f'**Pass rate: {pass_rate:.1f}%** ({verdicts["PASS"]}/{total} runs · '
        f'{verdicts["MARGINAL"]} marginal · {verdicts["FAIL"]} fail · '
        f'last 50: {last50_pass}/{len(last50)} pass)',
        '',
    ]
    lines += ['## Pass rate per tier', '',
              '| Tier | Runs | Pass | Marginal | Fail | Pass rate |',
              '|---|---|---|---|---|---|']
    for t in sorted(tier_stats):
        s = tier_stats[t]
        rate = 100.0 * s['PASS'] / s['total']
        lines.append(f"| {t} | {s['total']} | {s['PASS']} | {s['MARGINAL']} | "
                     f"{s['FAIL']} | {rate:.1f}% |")
    lines.append('')
    if ranked:
        lines.append('| Failure category (worst first) | Runs |')
        lines.append('|---|---|')
        for cat, n in ranked:
            lines.append(f'| {cat} | {n} |')
    else:
        lines.append('_No FAIL runs yet._')
    lines.append('')
    if open_sigs:
        lines.append('**Fix first (open signatures, severity- then count-ranked):**')
        lines.append('')
        for r in open_sigs[:5]:
            lines.append(f"1. `{r['signature']}` — {r['category']} · "
                         f"{r['count']} hit(s) · example `{r['example_run_id']}`")
        lines.append('')

    lines += ['## MARGINAL repeat tracker', '']
    if marg_repeats:
        lines.append('| Movement code | MARGINAL runs where it was worst |')
        lines.append('|---|---|')
        for mv, n in marg_repeats.items():
            lines.append(f'| {mv} | {n} |')
    else:
        lines.append('_No repeating MARGINAL movement pattern._')
    lines += ['', '## Recent runs (last 20)', '',
              '| Run | Seed | Verdict | Category | Worst GEH |', '|---|---|---|---|---|']
    for r in results[-20:]:
        lines.append(f"| {r['run_id']} | {r['seed']} | {r['verdict']} | "
                     f"{r['failure_category'] or '—'} | {r['worst_geh']} |")

    if total % DIGEST_EVERY == 0:
        digest = (f'{pass_rate:.1f}% pass over {total} runs. '
                  f'Open signatures: {len(open_sigs)}. '
                  f'Worst open category: '
                  f"{open_sigs[0]['category'] if open_sigs else 'none'}.")
        lines += ['', f'## Checkpoint digest — run {total}', '', digest, '']
        # summary.md is rewritten every run, so checkpoints also append to a
        # persistent log an engineer can scan the morning after.
        with open(HARNESS_ROOT / 'checkpoints.log', 'a') as f:
            f.write(f'{_now_iso()} run {total}: {digest}\n')

    lines.append('')
    SUMMARY_MD.write_text('\n'.join(lines))
