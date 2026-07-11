"""Acceptance tests: every Examiner detector proven fail-then-pass.

A verification that can't fail is worthless. Each test corrupts exactly one
thing, asserts the detector goes red, then asserts the pristine path is
green. Runs offline (no backend, no LLM) except the pipeline-crash test,
which uses a connection-refused URL — still no backend required.

Run: python3.12 -m pytest harness/tests -q
"""

import copy

import pytest

from harness import grader, operate, probes, puzzler, schema_gate

SEED = 424242


@pytest.fixture(scope='module')
def gen():
    return puzzler.generate(SEED)


@pytest.fixture()
def clean_run(gen):
    """A synthetic clean run: the tool 'returned' the answer key verbatim,
    with self-consistent telemetry. This is what a perfect tool looks like."""
    primary = gen['primary_orientation']
    project = gen['projects'][primary]
    key = gen['keys_by_num'][primary]
    axis = ('EB', 'WB') if primary == 'EW' else ('NB', 'SB')
    n = gen['n']

    balanced = {p: {num: dict(mvs) for num, mvs in key[p].items()}
                for p in ('AM', 'PM')}

    from harness import nchrp_math as nm
    link_conservation = {}
    movements_review = {}
    for period in ('AM', 'PM'):
        by_num = {int(k): v for k, v in balanced[period].items()}
        entries = []
        for i in range(1, n):
            e = nm.link_conservation_entry(by_num, i, i + 1, axis[0])
            e['mode'] = 'Full'
            entries.append(e)
            e = nm.link_conservation_entry(by_num, i + 1, i, axis[1])
            e['mode'] = 'Full'
            entries.append(e)
        link_conservation[period] = entries

        raw = probes._raw_by_num(project, period)
        rows = []
        for n_str in sorted(raw, key=int):
            for mv in probes._REVIEW_ORDER:
                r = int(raw[n_str].get(mv, 0) or 0)
                if r <= 0:
                    continue
                b = int(balanced[period][n_str].get(mv, 0) or 0)
                rows.append({'int_num': int(n_str), 'movement': mv,
                             'raw': r, 'balanced': b, 'delta': b - r})
        movements_review[period] = rows

    tool_output = {
        'balanced': balanced,
        'converged': {p: {str(i): True for i in range(1, n + 1)} for p in ('AM', 'PM')},
        'iterations': {p: {str(i): 3 for i in range(1, n + 1)} for p in ('AM', 'PM')},
        'link_conservation': link_conservation,
        'movements_review': movements_review,
    }
    raw_by_period = {p: probes._raw_by_num(project, p) for p in ('AM', 'PM')}
    return {'gen': gen, 'project': project, 'key': key,
            'tool_output': tool_output, 'raw_by_period': raw_by_period}


def _grade(run, tool_output=None, key=None):
    probe_results = [
        probes.probe_telemetry_truthfulness(run['project'],
                                            tool_output or run['tool_output']),
    ]
    return grader.grade(key or run['key'], run['raw_by_period'],
                        tool_output or run['tool_output'], probe_results)


# ── 6. Clean run goes green (the baseline every red test restores to) ────────

def test_clean_run_is_green(clean_run):
    grade = _grade(clean_run)
    assert grade['verdict'] == 'PASS', [c for c in grade['checks'] if not c['ok']]
    assert grade['failure_category'] is None
    assert grade['signature'] == ''


# ── 1. Corrupt an answer-key movement by 300 veh → GEH fires ─────────────────

def test_geh_detector_fires_on_corrupted_key(clean_run):
    bad_key = copy.deepcopy(clean_run['key'])
    bad_key['AM']['1']['EBT'] += 300
    grade = _grade(clean_run, key=bad_key)
    assert grade['verdict'] == 'FAIL'
    assert grade['failure_category'] == 'accuracy-drift'
    geh_check = next(c for c in grade['checks'] if c['check'] == 'T2-geh')
    assert not geh_check['ok']
    assert grade['geh']['worst'] > 10
    assert 'EBT' in grade['geh']['worst_movement']


# ── 2. Inject volume on an absent leg → phantom check fires ──────────────────

def test_phantom_detector_fires_on_absent_leg_volume(clean_run):
    # Erase all raw demand touching int 1's N leg (approach SB in, exits NB),
    # then leave a positive balanced value on a movement using that leg.
    raw = copy.deepcopy(clean_run['raw_by_period'])
    for period in ('AM', 'PM'):
        vols = raw[period]['1']
        for mv in ('SBL', 'SBT', 'SBR',    # approach via N leg
                   'NBT', 'EBL', 'WBR'):   # outflow via N leg
            vols.pop(mv, None)
    out = copy.deepcopy(clean_run['tool_output'])
    out['balanced']['AM']['1']['EBL'] = 50   # exits the now-absent N leg

    checks = grader.check_phantom(raw, out)
    assert not checks['ok']
    assert any('EBL' in d for d in checks['details'])

    # green path: the pristine run has every leg present
    assert grader.check_phantom(clean_run['raw_by_period'],
                                clean_run['tool_output'])['ok']


# ── 3. Fake telemetry → truthfulness probe fires ─────────────────────────────
# (finalResidual is not recomputable from the response — documented deviation;
#  the probe instead exactly recomputes link_conservation + movements_review.)

def test_telemetry_probe_fires_on_faked_conservation(clean_run):
    out = copy.deepcopy(clean_run['tool_output'])
    out['link_conservation']['AM'][0]['delta'] = 0.0
    out['link_conservation']['AM'][0]['upstream_outflow'] -= 300  # lie
    probe = probes.probe_telemetry_truthfulness(clean_run['project'], out)
    assert not probe['ok']
    assert any('upstream_outflow' in d for d in probe['details'])


def test_telemetry_probe_fires_on_faked_movements_review(clean_run):
    out = copy.deepcopy(clean_run['tool_output'])
    out['movements_review']['AM'][0]['balanced'] += 40  # lie about a value
    probe = probes.probe_telemetry_truthfulness(clean_run['project'], out)
    assert not probe['ok']

    # green path
    assert probes.probe_telemetry_truthfulness(
        clean_run['project'], clean_run['tool_output'])['ok']


# ── extra hard invariants: convergence, floor, idempotency, orientation ──────

def test_convergence_detector(clean_run):
    out = copy.deepcopy(clean_run['tool_output'])
    out['converged']['PM']['2'] = False
    grade = _grade(clean_run, tool_output=out)
    assert grade['verdict'] == 'FAIL'
    assert grade['failure_category'] == 'convergence'


def test_convergence_detector_fires_on_underreported_map(clean_run):
    # A response that silently drops intersections from `converged` must FAIL,
    # not pass vacuously.
    out = copy.deepcopy(clean_run['tool_output'])
    out['converged']['AM'] = {}
    check = grader.check_convergence(out, clean_run['key'])
    assert not check['ok']
    assert any('missing from' in d for d in check['details'])
    assert grader.check_convergence(clean_run['tool_output'],
                                    clean_run['key'])['ok']


def test_conservation_detector_fires_on_missing_entries(clean_run):
    # A response that stops emitting link_conservation entries must FAIL the
    # coverage check, not pass vacuously.
    out = copy.deepcopy(clean_run['tool_output'])
    out['link_conservation'] = {'AM': [], 'PM': []}
    pairs = [(i, i + 1) for i in range(1, clean_run['gen']['n'])]
    check = grader.check_conservation(out, expected_pairs=pairs)
    assert not check['ok']
    assert all('expected 2 directed' in d for d in check['details'])
    assert grader.check_conservation(clean_run['tool_output'],
                                     expected_pairs=pairs)['ok']


def test_floor_detector(clean_run):
    out = copy.deepcopy(clean_run['tool_output'])
    out['balanced']['AM']['1']['EBL'] = 3
    check = grader.check_floor(out)
    assert not check['ok']
    assert grader.check_floor(clean_run['tool_output'])['ok']


def test_conservation_detector(clean_run):
    out = copy.deepcopy(clean_run['tool_output'])
    # Bump the corridor-forward through movement — a cross-street movement
    # wouldn't touch any linked leg total.
    fwd_t = ('EBT' if clean_run['gen']['primary_orientation'] == 'EW' else 'NBT')
    out['balanced']['AM']['2'][fwd_t] += 40  # break a link for real
    check = grader.check_conservation(out)
    assert not check['ok']
    assert grader.check_conservation(clean_run['tool_output'])['ok']


def test_idempotency_probe():
    assert probes.probe_idempotency(b'{"a":1}', b'{"a":1}')['ok']
    assert not probes.probe_idempotency(b'{"a":1}', b'{"a":2}')['ok']


def test_orientation_probe(gen):
    key_ew = gen['keys_by_num']['EW']['AM']
    key_ns = gen['keys_by_num']['NS']['AM']
    ok = probes.probe_orientation_equivalence(
        {'AM': key_ew, 'PM': {}}, {'AM': key_ns, 'PM': {}},
        puzzler.rotate_movements)
    assert ok['ok']
    bad_ns = copy.deepcopy(key_ns)
    bad_ns['1']['NBT'] += 5
    bad = probes.probe_orientation_equivalence(
        {'AM': key_ew, 'PM': {}}, {'AM': bad_ns, 'PM': {}},
        puzzler.rotate_movements)
    assert not bad['ok']


# ── 5. Malformed puzzle → schema gate fires loudly ───────────────────────────

def test_schema_gate_fires_on_malformed_puzzle(gen):
    bad = copy.deepcopy(gen['projects']['EW'])
    del bad['intersections'][0]['lat']
    bad['links'][0]['direction'] = 'NB'                      # cardinal, not axis
    bad['intersections'][1]['volumes']['AM']['XXT'] = {'value': 1, '_source': 'manual'}
    with pytest.raises(schema_gate.SchemaGateError) as exc:
        schema_gate.validate_project(bad)
    assert len(exc.value.errors) == 3

    # green path: pristine puzzles validate in both orientations
    for orientation in ('EW', 'NS'):
        schema_gate.validate_project(gen['projects'][orientation])


# ── 4. Backend dead → pipeline-crash recorded, loop continues ────────────────

def test_backend_death_records_crash_and_loop_continues(tmp_path, monkeypatch):
    from harness import runner, scorekeeper

    monkeypatch.setattr(scorekeeper, 'RESULTS_CSV', tmp_path / 'results.csv')
    monkeypatch.setattr(scorekeeper, 'RUNS_DIR', tmp_path / 'runs')
    monkeypatch.setattr(scorekeeper, 'FAILURES_DIR', tmp_path / 'failures')
    monkeypatch.setattr(scorekeeper, 'LEDGER_CSV', tmp_path / 'failures' / 'index.csv')
    monkeypatch.setattr(scorekeeper, 'SUMMARY_MD', tmp_path / 'summary.md')
    monkeypatch.setenv('ANTHROPIC_API_KEY', '')   # force fallback narration

    dead = 'http://localhost:59999'   # nothing listens here
    rows = [runner.execute_run(seed, base_url=dead) for seed in (1, 2)]
    assert [r['verdict'] for r in rows] == ['FAIL', 'FAIL']
    assert all(r['failure_category'] == 'pipeline-crash' for r in rows)
    # both runs recorded — the loop moved on to the next seed
    assert (tmp_path / 'results.csv').read_text().count('pipeline-crash') == 2
    # crash signature dedups to one ledger row with count 2
    ledger = (tmp_path / 'failures' / 'index.csv').read_text()
    assert ledger.count('pipeline-crash') == 1
    assert ',2,' in ledger


# ── puzzler ground-truth invariants (the key must actually be a key) ─────────

def test_answer_key_is_perfectly_balanced():
    from harness import nchrp_math as nm
    for seed in (1, 7, 99):
        g = puzzler.generate(seed)
        for orientation, axis in (('EW', ('EB', 'WB')), ('NS', ('NB', 'SB'))):
            for period in ('AM', 'PM'):
                by_num = {int(k): v for k, v in
                          g['keys_by_num'][orientation][period].items()}
                for i in range(1, g['n']):
                    assert nm.link_conservation_entry(by_num, i, i + 1, axis[0])['delta'] == 0
                    assert nm.link_conservation_entry(by_num, i + 1, i, axis[1])['delta'] == 0


def test_generation_is_deterministic():
    assert puzzler.generate(31337) == puzzler.generate(31337)


def test_operator_payload_matches_ui_shape(gen):
    payload = operate.build_balance_payload(gen['projects']['EW'])
    assert set(payload) == {'intersections', 'unbalanced_volumes', 'links',
                            'link_resolution_method', 'max_iterations', 'tolerance'}
    assert payload['link_resolution_method'] == 'larger'
    assert payload['tolerance'] == 0.01
    assert payload['max_iterations'] == 500
    assert all(set(l) == {'fromNum', 'toNum', 'direction', 'mode'}
               for l in payload['links'])
    vols = payload['unbalanced_volumes']['AM']['1']
    assert all(isinstance(v, int) for v in vols.values())  # cells stripped to bare numbers
