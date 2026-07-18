"""Single Forger run: python -m harness.forger.run_one --seed N --style D

Regenerates the byte-identical sheet for (seed, style), runs the REAL
extractor on it (requires ANTHROPIC_API_KEY; a missing key records a CRASH
verdict rather than raising), grades, and records.

Exit code: 0 PASS · 1 DIGIT-ONLY · 2 anything else. Note the extractor is
an LLM — the sheet reproduces exactly, the extraction may not; every run is
recorded as its own row.
"""

import argparse
import subprocess
import sys

from . import grader, operate, scorekeeper, sheets


def _git_sha():
    try:
        return subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, cwd=scorekeeper.FORGER_ROOT,
        ).stdout.strip() or 'unknown'
    except OSError:
        return 'unknown'


def execute_run(seed, style):
    """One full Forge → Extract → Grade → Record cycle. Never raises for
    extractor-side failures. Returns the results row."""
    sheet = sheets.generate_sheet(seed, style)
    pdf = sheets.render_pdf(sheet)

    run_id = scorekeeper.make_run_id(seed, style)
    run_dir = scorekeeper.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = run_dir / 'sheet.pdf'
    pdf_path.write_bytes(pdf)

    extraction = operate.run_extraction(pdf_path)
    g = grader.grade(sheet, extraction.get('parsed'),
                     error=extraction.get('error'))

    meta = {'run_id': run_id, 'seed': seed, 'style': style,
            'git_sha': _git_sha(), 'usage': extraction.get('usage')}
    return scorekeeper.record_run(meta, sheet, g, extraction, pdf)


def print_row(row, file=sys.stdout):
    print(f"[{row['run_id']}] seed={row['seed']} style={row['style']} "
          f"verdict={row['verdict']}"
          f"{' sig=' + row['signature'] if row['signature'] else ''}"
          f" map={row['n_map_err']} totalErr={row['n_total_as_movement']}"
          f" digit={row['n_digit_err']}"
          f" ratioAM={row['total_ratio_am'] or 'n/a'}", file=file)


def main(argv=None):
    p = argparse.ArgumentParser(description='One Forger run against the real extractor.')
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--style', choices=sheets.STYLES, default='D')
    args = p.parse_args(argv)
    row = execute_run(args.seed, args.style)
    print_row(row)
    return {'PASS': 0, 'DIGIT-ONLY': 1}.get(row['verdict'], 2)


if __name__ == '__main__':
    sys.exit(main())
