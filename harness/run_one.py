"""Single-run repro entrypoint: python -m harness.run_one --seed N [--tier B|C|D]

Regenerates the identical puzzle for the (seed, tier), runs the full Examiner
cycle against the live backend, and records the result exactly like the loop
does. No --tier reproduces the pre-tier behavior exactly (Tier A).
Exit code: 0 PASS, 1 MARGINAL, 2 FAIL.
"""

import argparse
import sys

from . import operate, puzzler
from .runner import execute_run, print_row


def main(argv=None):
    p = argparse.ArgumentParser(description='Reproduce one Examiner run from its seed.')
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--tier', choices=puzzler.TIERS, default='A',
                   help='difficulty tier (default A — the pre-tier config)')
    p.add_argument('--base-url', default=operate.DEFAULT_BASE_URL)
    args = p.parse_args(argv)

    row = execute_run(args.seed, base_url=args.base_url, tier=args.tier)
    print_row(row)
    return {'PASS': 0, 'MARGINAL': 1, 'FAIL': 2}.get(row['verdict'], 2)


if __name__ == '__main__':
    sys.exit(main())
