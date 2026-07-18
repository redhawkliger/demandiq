"""Bounded Forger batch: python -m harness.forger.batch --n 50 --style both

Every run costs API tokens — batches are tens to low hundreds per session,
hard-capped at MAX_BATCH, NEVER an unbounded loop. A run that crashes
(missing key, API error) records a CRASH verdict and the batch continues.

--repeat R runs each seed R times (variance measurement: the extractor is
an LLM; repeat outcomes are recorded per-run, never averaged).
"""

import argparse
import sys

from . import scorekeeper, sheets
from .run_one import execute_run, print_row

MAX_BATCH = 200


def main(argv=None):
    p = argparse.ArgumentParser(description='Bounded Forger batch.')
    p.add_argument('--n', type=int, required=True,
                   help=f'number of seeds (hard cap {MAX_BATCH} runs per invocation)')
    p.add_argument('--style', choices=('T', 'D', 'both'), default='both')
    p.add_argument('--start-seed', type=int, default=1)
    p.add_argument('--repeat', type=int, default=1,
                   help='runs per seed (variance measurement)')
    args = p.parse_args(argv)

    total_runs = args.n * args.repeat * (2 if args.style == 'both' else 1)
    if total_runs > MAX_BATCH:
        p.error(f'{total_runs} runs exceeds the {MAX_BATCH}-run cost cap — '
                f'split into smaller batches')

    counts = {}
    tok_in = tok_out = 0
    for i in range(args.n):
        seed = args.start_seed + i
        styles = ('T', 'D') if args.style == 'both' else (args.style,)
        for style in styles:
            for _ in range(args.repeat):
                try:
                    row = execute_run(seed, style)
                except KeyboardInterrupt:
                    raise
                except Exception as e:      # noqa: BLE001 — batch must survive
                    print(f'[forger-error] seed={seed} style={style}: {e}',
                          file=sys.stderr)
                    continue
                print_row(row)
                key = (style, row['verdict'])
                counts[key] = counts.get(key, 0) + 1
                tok_in += int(row['tokens_in'] or 0)
                tok_out += int(row['tokens_out'] or 0)

    print('\n── batch digest ──')
    for style in ('T', 'D'):
        style_counts = {v: n for (s, v), n in counts.items() if s == style}
        if style_counts:
            total = sum(style_counts.values())
            parts = ' · '.join(f'{v}×{n}' for v, n in
                               sorted(style_counts.items(), key=lambda kv: -kv[1]))
            print(f'style {style}: {total} runs — {parts}')
    print(f'tokens: {tok_in:,} in / {tok_out:,} out')
    print(f'summary: {scorekeeper.SUMMARY_MD}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
