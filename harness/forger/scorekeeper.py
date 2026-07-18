"""Forger Scorekeeper — plain-file results, case files, signature ledger.

Same discipline as the Examiner's scorekeeper, forger-scoped:
  harness/forger/results.csv     one row per run (EVERY run — repeats of a
                                 seed are separate rows; run-to-run variance
                                 of the LLM extractor is data, never averaged)
  harness/forger/runs/<id>/      per-run artifacts (sheet.pdf, answer key,
                                 extraction incl. raw model output, grade)
  harness/forger/failures/<id>/  full case file per non-PASS run
  harness/forger/failures/index.csv  signature ledger (dedup by shape)
  harness/forger/summary.md      verdict rates by style, error-class
                                 histogram, MAP sub-pattern tracker,
                                 repeat-seed variance, token spend
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

FORGER_ROOT = Path(__file__).parent
RESULTS_CSV = FORGER_ROOT / 'results.csv'
RUNS_DIR = FORGER_ROOT / 'runs'
FAILURES_DIR = FORGER_ROOT / 'failures'
LEDGER_CSV = FAILURES_DIR / 'index.csv'
SUMMARY_MD = FORGER_ROOT / 'summary.md'

RESULTS_FIELDS = [
    'run_id', 'timestamp', 'seed', 'style', 'git_sha', 'verdict', 'signature',
    'n_correct', 'n_digit_err', 'n_map_err', 'n_total_as_movement',
    'n_omission', 'n_hallucination', 'map_subpatterns',
    'total_ratio_am', 'total_ratio_pm', 'tokens_in', 'tokens_out',
]
LEDGER_FIELDS = ['signature', 'verdict', 'count', 'first_seen', 'last_seen',
                 'example_run_id', 'status', 'fixed_by_commit']

VERDICT_ORDER = ('PASS', 'DIGIT-ONLY', 'MAP-FAIL', 'MIXED', 'CRASH')
_CLASS_COLS = {
    'CORRECT': 'n_correct', 'DIGIT-ERR': 'n_digit_err', 'MAP-ERR': 'n_map_err',
    'TOTAL-AS-MOVEMENT': 'n_total_as_movement', 'OMISSION': 'n_omission',
    'HALLUCINATION': 'n_hallucination',
}


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def make_run_id(seed, style):
    ts = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    run_id = f'{ts}-seed{seed}{style}'
    n = 2
    while (RUNS_DIR / run_id).exists() or (FAILURES_DIR / run_id).exists():
        run_id = f'{ts}-seed{seed}{style}-{n}'
        n += 1
    return run_id


def _read_csv(path):
    if not path.exists():
        return []
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def _append_csv(path, fields, row):
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2, sort_keys=True, default=str)
        f.write('\n')


def _fmt_ratio(r):
    return f'{r:.3f}' if isinstance(r, (int, float)) else ''


def record_run(meta, sheet, grade, extraction, pdf_bytes):
    """Record one completed run. Returns the results row dict."""
    run_id = meta['run_id']
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'sheet.pdf').write_bytes(pdf_bytes)
    _write_json(run_dir / 'answer_key.json', sheet)
    _write_json(run_dir / 'grade.json', grade)
    ext_record = {k: v for k, v in (extraction or {}).items() if k != 'raw_text'}
    _write_json(run_dir / 'extraction.json', ext_record)
    if (extraction or {}).get('raw_text'):
        (run_dir / 'raw_model_output.txt').write_text(extraction['raw_text'])

    usage = meta.get('usage') or (extraction or {}).get('usage') or {}
    classes = grade.get('classes') or {}
    row = {
        'run_id': run_id,
        'timestamp': _now_iso(),
        'seed': meta['seed'],
        'style': meta['style'],
        'git_sha': meta.get('git_sha', ''),
        'verdict': grade['verdict'],
        'signature': grade.get('signature', ''),
        **{col: classes.get(cls, 0) for cls, col in _CLASS_COLS.items()},
        'map_subpatterns': ';'.join(grade.get('map_subpatterns') or []),
        'total_ratio_am': _fmt_ratio((grade.get('total_ratio') or {}).get('AM')),
        'total_ratio_pm': _fmt_ratio((grade.get('total_ratio') or {}).get('PM')),
        'tokens_in': usage.get('input_tokens', ''),
        'tokens_out': usage.get('output_tokens', ''),
    }
    _append_csv(RESULTS_CSV, RESULTS_FIELDS, row)

    if grade['verdict'] != 'PASS':
        _write_case_file(meta, sheet, grade, extraction, pdf_bytes, run_dir)
        _update_ledger(row)
    write_summary()
    return row


def _diff_table(grade):
    lines = ['| Period | Movement | True | Extracted | Class | Sub | Source |',
             '|---|---|---|---|---|---|---|']
    for period in ('AM', 'PM'):
        for mv, r in sorted((grade.get('per_movement') or {}).get(period, {}).items()):
            lines.append(
                f"| {period} | {mv} | {r.get('true')} | {r.get('got')} | "
                f"{r['class']} | {r.get('sub', '')} | {r.get('source', '')} |")
    return '\n'.join(lines)


def _write_case_file(meta, sheet, grade, extraction, pdf_bytes, run_dir):
    case_dir = FAILURES_DIR / meta['run_id']
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / 'sheet.pdf').write_bytes(pdf_bytes)
    _write_json(case_dir / 'answer_key.json', sheet)
    _write_json(case_dir / 'grade.json', grade)
    ext_record = {k: v for k, v in (extraction or {}).items() if k != 'raw_text'}
    _write_json(case_dir / 'extraction.json', ext_record)
    if (extraction or {}).get('raw_text'):
        (case_dir / 'raw_model_output.txt').write_text(extraction['raw_text'])
    (case_dir / 'diff_table.md').write_text(
        '# Classified diff — answer key vs extraction\n\n' + _diff_table(grade) + '\n')

    repro = (f"python -m harness.forger.run_one "
             f"--seed {meta['seed']} --style {meta['style']}")
    report = [
        f"# Forger failure — run `{meta['run_id']}`",
        '',
        f"- **Verdict:** {grade['verdict']}",
        f"- **Signature:** `{grade.get('signature', '')}`",
        f"- **Seed:** {meta['seed']} · style {meta['style']} · "
        f"sheet `{sheet['intersection_name']}` · orientation {sheet['orientation']}",
        f"- **Error classes:** "
        + (', '.join(f'{c}×{n}' for c, n in sorted((grade.get('classes') or {}).items())
                     if c != 'CORRECT') or '(crash)'),
        f"- **MAP sub-patterns:** "
        + (', '.join(grade.get('map_subpatterns') or []) or '—'),
        f"- **Total ratio (extracted/true):** "
        f"AM {_fmt_ratio((grade.get('total_ratio') or {}).get('AM')) or 'n/a'} · "
        f"PM {_fmt_ratio((grade.get('total_ratio') or {}).get('PM')) or 'n/a'}",
        '',
        '## Reproduce',
        '```bash',
        repro,
        '```',
        'The sheet regenerates byte-identically from (seed, style). The',
        'EXTRACTOR is an LLM — a re-run may classify differently; that',
        'run-to-run variance is data (recorded per run, never averaged).',
        '',
        '## Artifacts',
        '- `sheet.pdf` — the synthetic count sheet (metadata: forger-synthetic=true)',
        '- `answer_key.json` — the volumes actually placed on the sheet',
        '- `extraction.json` — parsed extractor output + verifier + usage + error',
        '- `raw_model_output.txt` — raw Claude response (when captured)',
        '- `grade.json` / `diff_table.md` — per-movement classification',
        '',
    ]
    (case_dir / 'report.md').write_text('\n'.join(report))


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
        rows.append({'signature': row['signature'], 'verdict': row['verdict'],
                     'count': '1', 'first_seen': now, 'last_seen': now,
                     'example_run_id': row['run_id'], 'status': 'open',
                     'fixed_by_commit': ''})
    with open(LEDGER_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        w.writerows(rows)


def write_summary():
    results = _read_csv(RESULTS_CSV)
    if not results:
        return
    lines = ['# Forger summary', '',
             f'{len(results)} runs total. The extractor under test is an LLM:',
             'repeat runs of one seed may differ — every run is its own row,',
             'and the variance section below reports the spread, never an average.',
             '']

    lines += ['## Verdict rates by style', '',
              '| Style | Runs | ' + ' | '.join(VERDICT_ORDER) + ' |',
              '|---|---|' + '---|' * len(VERDICT_ORDER)]
    for style in ('T', 'D'):
        rows = [r for r in results if r['style'] == style]
        if not rows:
            continue
        counts = {v: sum(1 for r in rows if r['verdict'] == v)
                  for v in VERDICT_ORDER}
        lines.append(f'| {style} | {len(rows)} | '
                     + ' | '.join(str(counts[v]) for v in VERDICT_ORDER) + ' |')

    lines += ['', '## Error-class histogram (movement-level)', '',
              '| Class | Count |', '|---|---|']
    for cls, col in _CLASS_COLS.items():
        if cls == 'CORRECT':
            continue
        total = sum(int(r[col] or 0) for r in results)
        lines.append(f'| {cls} | {total} |')

    lines += ['', '## MAP-ERR sub-pattern tracker', '',
              '| Sub-pattern | Runs exhibiting it |', '|---|---|']
    sub_counts = {}
    for r in results:
        for s in (r['map_subpatterns'] or '').split(';'):
            if s:
                sub_counts[s] = sub_counts.get(s, 0) + 1
    for s, n in sorted(sub_counts.items(), key=lambda kv: -kv[1]) or [('—', 0)]:
        lines.append(f'| {s} | {n} |')

    lines += ['', '## Run-to-run variance (repeated seeds)', '']
    by_key = {}
    for r in results:
        by_key.setdefault((r['seed'], r['style']), []).append(r['verdict'])
    repeated = {k: v for k, v in by_key.items() if len(v) > 1}
    if repeated:
        lines += ['| Seed | Style | Runs | Verdict sequence | Distinct |',
                  '|---|---|---|---|---|']
        for (seed, style), verdicts in sorted(repeated.items()):
            lines.append(f'| {seed} | {style} | {len(verdicts)} | '
                         f"{' → '.join(verdicts)} | {len(set(verdicts))} |")
    else:
        lines.append('_No repeated seeds yet._')

    tok_in = sum(int(r['tokens_in'] or 0) for r in results)
    tok_out = sum(int(r['tokens_out'] or 0) for r in results)
    lines += ['', '## Token spend', '',
              f'input {tok_in:,} · output {tok_out:,} across '
              f'{len(results)} runs', '']
    SUMMARY_MD.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD.write_text('\n'.join(lines))
