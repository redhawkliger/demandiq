"""One full Examiner cycle for one seed. Shared by loop.py and run_one.py.

Flow: Puzzler → schema gate → Operator (primary orientation) → probes
(idempotency, telemetry, S8 export, orientation sweep) → Grader → narrator
(FAIL/MARGINAL only) → Scorekeeper. Deterministic except the narrator, which
runs strictly after the verdict is decided.
"""

import subprocess
import sys

from . import grader, narrator, operate, probes, puzzler, schema_gate, scorekeeper

HARNESS_VERSION = '1.0.0'

_git_sha_cache = None


def _git_sha():
    global _git_sha_cache
    if _git_sha_cache is None:
        try:
            _git_sha_cache = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True, text=True, cwd=scorekeeper.HARNESS_ROOT,
            ).stdout.strip() or 'unknown'
        except OSError:
            _git_sha_cache = 'unknown'
    return _git_sha_cache


def _synthetic_grade(category, check_name, details):
    """Grade dict for runs that never reached the Grader (crash / bad puzzle)."""
    checks = [{'check': check_name, 'category': category, 'ok': False,
               'details': details[:40]}]
    return {
        'verdict': 'FAIL',
        'failure_category': category,
        'checks': checks,
        'geh': {'worst': 0.0, 'worst_movement': '', 'n_over_marginal': 0,
                'n_marginal': 0, 'rows': []},
        'signature': grader.compute_signature(category, checks, []),
    }


def _raw_by_period(project):
    return {p: probes._raw_by_num(project, p) for p in ('AM', 'PM')}


def execute_run(seed, base_url=operate.DEFAULT_BASE_URL, tier='A'):
    """Run one seed end to end at a difficulty tier. Never raises for
    tool-side failures — those become recorded verdicts. Returns the
    results.csv row dict."""
    gen = puzzler.generate(seed, tier=tier)
    primary = gen['primary_orientation']
    secondary = 'NS' if primary == 'EW' else 'EW'
    project = gen['projects'][primary]

    meta = {
        'run_id': scorekeeper.make_run_id(seed),
        'seed': seed,
        'git_sha': _git_sha(),
        'n': gen['n'],
        'orientation': primary,
        'tier': gen['tier'],                 # perturbation magnitude
        'difficulty': gen['difficulty'],     # difficulty tier A|B|C|D
        'harness_version': HARNESS_VERSION,
        'base_url': base_url,
    }
    artifacts = {
        'puzzle': project,
        'answer_key': gen['keys_by_num'][primary],
        'perturbation_log': gen['perturbation_log'],
    }

    # ── Schema gate: a puzzle that isn't a valid demandiq:project is a LOUD
    # harness failure, never a silent skip.
    try:
        for orientation in ('EW', 'NS'):
            schema_gate.validate_project(gen['projects'][orientation])
    except schema_gate.SchemaGateError as e:
        grade = _synthetic_grade('input/schema', 'schema-gate', e.errors)
        narration = narrator.narrate(grade, {'seed': seed, 'stage': 'schema-gate'})
        return scorekeeper.record_run(meta, grade, narration, artifacts)

    # ── Operator: the real balance pipeline, via the UI's exact payload path.
    # Only the PRIMARY balance call is fatal (pipeline-crash). A crash in a
    # secondary call (idempotency re-POST, rotated corridor, S8 diagram) is
    # recorded as that probe failing, so accuracy grading of the primary
    # output is never masked by, say, a broken diagram endpoint.
    try:
        tool_output, raw1 = operate.run_balance(project, base_url)
        artifacts['tool_output'] = tool_output
    except operate.PipelineError as e:
        grade = _synthetic_grade('pipeline-crash', 'pipeline', [str(e)])
        artifacts['pipeline_error'] = {'stage': e.stage, 'detail': e.detail}
        narration = narrator.narrate(grade, {'seed': seed, 'stage': e.stage})
        return scorekeeper.record_run(meta, grade, narration, artifacts)

    probe_results = [
        probes.probe_telemetry_truthfulness(project, tool_output),
    ]

    def _crashed(probe_name, err):
        return {'probe': probe_name, 'ok': False,
                'details': [f'probe transport failed: {err}']}

    # Idempotency: same puzzle again — byte-identical response required.
    try:
        _out2, raw2 = operate.run_balance(project, base_url)
        probe_results.append(probes.probe_idempotency(raw1, raw2))
    except operate.PipelineError as e:
        probe_results.append(_crashed('idempotency', e))

    # Orientation sweep: same corridor rotated 90° must balance identically.
    try:
        out_rot, _ = operate.run_balance(gen['projects'][secondary], base_url)
        rotate = puzzler.rotate_movements if primary == 'EW' else _rotate_back
        probe_results.append(probes.probe_orientation_equivalence(
            tool_output.get('balanced'), out_rot.get('balanced'), rotate))
        artifacts['tool_output_rotated'] = out_rot
    except operate.PipelineError as e:
        probe_results.append(_crashed('orientation-sweep', e))

    # S8 export probe: the diagram endpoint must return real PNGs.
    try:
        diagram = operate.run_corridor_diagram(project, tool_output, base_url)
        probe_results.append(probes.probe_s8_export(
            diagram, n_links=len(project.get('links') or [])))
        artifacts['s8_probe'] = {
            'segment_counts': diagram.get('segment_counts'),
            'am_png_bytes': len(diagram.get('am', {}).get('png_base64') or ''),
            'pm_png_bytes': len(diagram.get('pm', {}).get('png_base64') or ''),
        }
    except operate.PipelineError as e:
        probe_results.append(_crashed('s8-export', e))

    # ── Grader: verdict decided entirely in code.
    expected_pairs = [(i, i + 1) for i in range(1, gen['n'])]
    grade = grader.grade(gen['keys_by_num'][primary], _raw_by_period(project),
                         tool_output, probe_results,
                         expected_pairs=expected_pairs)
    artifacts['grade'] = grade

    # ── Narrator: post-verdict, FAIL/MARGINAL only.
    narration = narrator.narrate(grade, {
        'seed': seed, 'n_intersections': gen['n'], 'orientation': primary,
        'perturb_tier': gen['tier'],
    })
    artifacts['narration'] = narration

    return scorekeeper.record_run(meta, grade, narration, artifacts)


_INVERSE_ROTATE = {v: k for k, v in puzzler._ROTATE_DIR.items()}


def _rotate_back(vols):
    """NS→EW movement rotation (derived inverse of puzzler's rotation)."""
    return {_INVERSE_ROTATE[mv[:2]] + mv[2:]: v for mv, v in vols.items()}


def print_row(row, file=sys.stdout):
    # Tier A keeps the exact pre-tier console line; other tiers name theirs.
    tier = row.get('tier', 'A')
    print(f"[{row['run_id']}] seed={row['seed']}"
          f"{' tier=' + tier if tier != 'A' else ''}"
          f" verdict={row['verdict']}"
          f"{' category=' + row['failure_category'] if row['failure_category'] else ''}"
          f" worstGEH={row['worst_geh']}", file=file)
