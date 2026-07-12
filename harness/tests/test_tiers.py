"""Acceptance tests for Examiner v2 difficulty tiers (A/B/C/D).

All offline — no backend, no LLM. The contract under test:

  A (default)  3-6 ints, all 4-leg — byte-identical to pre-tier behavior
  B            5-20 ints, all 4-leg
  C            3-6 ints, seeded ~50/50 mix of 4-leg and 3-leg (T)
  D            5-20 ints, mixed per Tier C rules

Tier A byte-identity is pinned by harness/goldens/tier_a_hashes.json,
captured from the generator BEFORE tiers existed. 3-leg serialization must
match the real frontend: the absent approach key stays present as
{exists: false, lanes: [], stopControlled: false} and the absent leg's
movement keys are OMITTED from volumes (never null, never 0).
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from harness import grader, nchrp_math as nm, puzzler, schema_gate, scorekeeper
from harness.notify import SessionNotifier

GOLDENS_PATH = Path(__file__).parent.parent / 'goldens' / 'tier_a_hashes.json'

# approach travel-direction → the physical leg it enters from
_IN_DIR_TO_LEG = {v: k for k, v in nm.LEG_IN_DIR.items()}

# Directed corridor links per orientation: intersection i+1 is always east
# (EW) / north (NS) of intersection i in the Puzzler's coordinate layout.
_AXIS_DIRECTIONS = {'EW': ('EB', 'WB'), 'NS': ('NB', 'SB')}


def _gen_hash(gen, fields):
    subset = {f: gen[f] for f in fields}
    return hashlib.sha256(
        json.dumps(subset, sort_keys=True).encode()).hexdigest()


def _absent_dirs(intersection):
    """Approach travel-directions with exists=False on a puzzle intersection."""
    return {d for d, ap in intersection['approaches'].items()
            if ap.get('exists') is False}


def _directed_links(n, orientation):
    fwd, bwd = _AXIS_DIRECTIONS[orientation]
    for i in range(1, n):
        yield (i, i + 1, fwd)
        yield (i + 1, i, bwd)


# ── Tier A regression: byte-identical to the pre-tier generator ────────────

def test_tier_a_default_matches_pre_tier_goldens():
    goldens = json.loads(GOLDENS_PATH.read_text())
    fields = tuple(goldens['fields'])
    for seed_str, expected in goldens['hashes'].items():
        seed = int(seed_str)
        assert _gen_hash(puzzler.generate(seed), fields) == expected, \
            f'generate({seed}) diverged from pre-tier golden'
        assert _gen_hash(puzzler.generate(seed, tier='A'), fields) == expected, \
            f"generate({seed}, tier='A') diverged from pre-tier golden"


def test_generate_deterministic_per_seed_and_tier():
    fields = ('n', 'primary_orientation', 'key', 'puzzle_vols', 'projects',
              'keys_by_num', 'perturbation_log')
    for tier in ('A', 'B', 'C', 'D'):
        a = _gen_hash(puzzler.generate(7, tier=tier), fields)
        b = _gen_hash(puzzler.generate(7, tier=tier), fields)
        assert a == b, f'tier {tier} not deterministic for a fixed seed'


def test_tiers_produce_distinct_puzzles():
    hashes = {t: _gen_hash(puzzler.generate(11, tier=t), ('key', 'n'))
              for t in ('A', 'B', 'C', 'D')}
    assert len(set(hashes.values())) == 4, \
        f'expected 4 distinct puzzles across tiers, got {hashes}'


# ── Tier B: long chains, all 4-leg ──────────────────────────────────────────

def test_tier_b_dimensions_and_four_legs():
    sizes = []
    for seed in range(1, 31):
        gen = puzzler.generate(seed, tier='B')
        sizes.append(gen['n'])
        assert 5 <= gen['n'] <= 20
        assert gen['difficulty'] == 'B'
        assert gen['tier'] in puzzler.PERTURB_TIERS      # perturb rules unchanged
        for it in gen['projects']['EW']['intersections']:
            assert not _absent_dirs(it), 'Tier B must be all 4-leg'
        for period in ('AM', 'PM'):
            for mv_dict in gen['key'][period]:
                assert set(mv_dict) == set(nm.STANDARD_MOVEMENTS)
                assert all(v % 5 == 0 and v >= 50 for v in mv_dict.values())
    assert max(sizes) > 6, 'Tier B never generated a corridor longer than Tier A'


# ── Tier C: T-intersections ─────────────────────────────────────────────────

def test_tier_c_dimensions_and_t_mix():
    t_count = total = 0
    for seed in range(1, 101):
        gen = puzzler.generate(seed, tier='C')
        assert 3 <= gen['n'] <= 6
        assert gen['difficulty'] == 'C'
        for it in gen['projects']['EW']['intersections']:
            absent = _absent_dirs(it)
            total += 1
            assert len(absent) <= 1, 'at most one absent leg per intersection'
            if absent:
                t_count += 1
                # corridor through-legs always present: in the EW frame the
                # corridor sits on the W/E legs (approaches EB/WB), so only a
                # cross-street leg (approach NB or SB) may be absent.
                assert absent <= {'NB', 'SB'}, \
                    f'absent approach {absent} is a corridor leg'
    frac = t_count / total
    assert 0.35 <= frac <= 0.65, f'T-intersection mix {frac:.2f} not ~50/50'


def test_tier_c_serialization_matches_frontend_representation():
    """Absent approach: key present with exists=False and lanes=[]; absent
    leg's movement keys OMITTED from volumes (both periods, both orientations)."""
    checked_t = 0
    for seed in range(1, 41):
        gen = puzzler.generate(seed, tier='C')
        for orientation in ('EW', 'NS'):
            for it in gen['projects'][orientation]['intersections']:
                assert set(it['approaches']) == {'EB', 'WB', 'NB', 'SB'}, \
                    'all four approach keys must stay present'
                absent = _absent_dirs(it)
                for d in absent:
                    ap = it['approaches'][d]
                    assert ap == {'exists': False, 'lanes': [],
                                  'stopControlled': False}
                absent_legs = {_IN_DIR_TO_LEG[d] for d in absent}
                for period in ('AM', 'PM'):
                    for mv in it['volumes'][period]:
                        a_leg, e_leg = nm.MOVEMENT_LEGS[mv]
                        assert a_leg not in absent_legs, \
                            f'{mv} present but its approach leg is absent'
                        assert e_leg not in absent_legs, \
                            f'{mv} present but its exit leg is absent'
                        cell = it['volumes'][period][mv]
                        assert cell.get('value') is not None
                if absent:
                    checked_t += 1
    assert checked_t > 0, 'no T-intersections generated in 40 Tier C seeds'


def test_tier_c_answer_key_exact_conservation_100_seeds():
    """Acceptance #2: for 100 seeded Tier C puzzles the answer key conserves
    EXACTLY on every directed corridor link, in both orientations, and no key
    movement references an absent leg."""
    for seed in range(1, 101):
        gen = puzzler.generate(seed, tier='C')
        for orientation in ('EW', 'NS'):
            ints = gen['projects'][orientation]['intersections']
            absent_by_num = {
                it['num']: {_IN_DIR_TO_LEG[d] for d in _absent_dirs(it)}
                for it in ints
            }
            for period in ('AM', 'PM'):
                key = {int(n): dict(v) for n, v in
                       gen['keys_by_num'][orientation][period].items()}
                for num, vols in key.items():
                    for mv in vols:
                        a_leg, e_leg = nm.MOVEMENT_LEGS[mv]
                        assert not ({a_leg, e_leg} & absent_by_num[num]), (
                            f'seed {seed} {orientation} {period} int {num}: key '
                            f'movement {mv} references an absent leg')
                for (u, d, direction) in _directed_links(gen['n'], orientation):
                    entry = nm.link_conservation_entry(key, u, d, direction)
                    assert entry['delta'] == 0.0, (
                        f'seed {seed} {orientation} {period} link {u}→{d} '
                        f'{direction}: key delta {entry["delta"]:+.1f}')


def test_tier_d_mixed_long_chains():
    saw_t = False
    for seed in range(1, 31):
        gen = puzzler.generate(seed, tier='D')
        assert 5 <= gen['n'] <= 20
        assert gen['difficulty'] == 'D'
        for it in gen['projects']['EW']['intersections']:
            absent = _absent_dirs(it)
            assert absent <= {'NB', 'SB'}
            saw_t = saw_t or bool(absent)
    assert saw_t, 'Tier D never generated a T-intersection in 30 seeds'


# ── Phantom detector on Tier C (acceptance #3) ──────────────────────────────

def _tier_c_gen_with_t():
    for seed in range(1, 50):
        gen = puzzler.generate(seed, tier='C')
        prim = gen['primary_orientation']
        for it in gen['projects'][prim]['intersections']:
            if _absent_dirs(it):
                return gen, prim, it
    raise AssertionError('no T-intersection found in 49 Tier C seeds')


def test_phantom_check_fires_on_absent_leg_volume():
    """Hand-corrupt a Tier C tool output to put volume on an absent leg —
    the T1-phantom check must go red; the pristine output stays green."""
    gen, prim, t_int = _tier_c_gen_with_t()
    key = gen['keys_by_num'][prim]

    clean = {'balanced': {p: {n: dict(v) for n, v in key[p].items()}
                          for p in ('AM', 'PM')}}
    raw_by_period = {p: {n: dict(v) for n, v in key[p].items()}
                     for p in ('AM', 'PM')}

    assert grader.check_phantom(raw_by_period, clean)['ok'], \
        'pristine Tier C output must not trip the phantom check'

    absent_dir = next(iter(_absent_dirs(t_int)))          # e.g. 'SB'
    phantom_mv = f'{absent_dir}T'                          # approaches from the absent leg
    corrupted = copy.deepcopy(clean)
    corrupted['balanced']['AM'][str(t_int['num'])][phantom_mv] = 50

    result = grader.check_phantom(raw_by_period, corrupted)
    assert not result['ok'], 'phantom volume on an absent leg went undetected'
    assert any(phantom_mv in d for d in result['details'])


# ── Schema gate on Tier C/D (acceptance #4) ─────────────────────────────────

def test_schema_gate_passes_tier_c_and_d():
    for tier in ('C', 'D'):
        for seed in range(1, 26):
            gen = puzzler.generate(seed, tier=tier)
            for orientation in ('EW', 'NS'):
                schema_gate.validate_project(gen['projects'][orientation])


# ── Loop tier rotation ──────────────────────────────────────────────────────

def test_tier_rotation_deterministic_and_mixed():
    picks = [puzzler.tier_for_seed(s) for s in range(1, 2001)]
    again = [puzzler.tier_for_seed(s) for s in range(1, 2001)]
    assert picks == again, 'tier rotation must be deterministic per seed'
    counts = {t: picks.count(t) for t in 'ABCD'}
    for t, weight in puzzler.DEFAULT_TIER_MIX.items():
        frac = counts[t] / len(picks)
        assert abs(frac - weight / 100.0) < 0.05, \
            f'tier {t}: {frac:.2%} observed vs {weight}% configured'


def test_tier_rotation_respects_custom_mix():
    picks = {puzzler.tier_for_seed(s, mix={'B': 100}) for s in range(1, 101)}
    assert picks == {'B'}


# ── results.csv tier column + migration ─────────────────────────────────────

def test_results_fields_include_tier():
    assert 'tier' in scorekeeper.RESULTS_FIELDS


def test_results_csv_migration_backfills_tier_a(tmp_path, monkeypatch):
    old = tmp_path / 'results.csv'
    old_fields = [f for f in scorekeeper.RESULTS_FIELDS if f != 'tier']
    old.write_text(
        ','.join(old_fields) + '\n'
        + ','.join(['r1', '2026-07-11T00:00:00Z', '1', 'abc', '4', 'EW',
                    '0.15', 'PASS', '', '', '1.000', 'AM int 1 EBT']) + '\n')
    monkeypatch.setattr(scorekeeper, 'RESULTS_CSV', old)
    scorekeeper.migrate_results_csv()
    rows = scorekeeper._read_csv(old)
    assert rows and rows[0]['tier'] == 'A', \
        'pre-tier rows must be backfilled as Tier A'
    assert rows[0]['verdict'] == 'PASS'
    # idempotent
    scorekeeper.migrate_results_csv()
    assert scorekeeper._read_csv(old) == rows


# ── Reporting: per-tier pass rates ──────────────────────────────────────────

def _row(seed, tier, verdict, category=''):
    return {
        'run_id': f'r{seed}', 'timestamp': '2026-07-11T00:00:00Z',
        'seed': str(seed), 'git_sha': 'abc', 'n_intersections': '4',
        'orientation': 'EW', 'perturb_tier': '0.15', 'tier': tier,
        'verdict': verdict, 'failure_category': category,
        'signature': 'sig1' if verdict == 'FAIL' else '',
        'worst_geh': '1.000', 'worst_movement': 'AM int 1 EBT',
    }


def test_summary_reports_pass_rate_per_tier(tmp_path, monkeypatch):
    results = tmp_path / 'results.csv'
    with open(results, 'w', newline='') as f:
        import csv
        w = csv.DictWriter(f, fieldnames=scorekeeper.RESULTS_FIELDS)
        w.writeheader()
        for i, (tier, verdict) in enumerate(
                [('A', 'PASS'), ('A', 'PASS'), ('B', 'FAIL'),
                 ('B', 'PASS'), ('C', 'MARGINAL'), ('D', 'PASS')]):
            w.writerow(_row(i, tier, verdict,
                            'unknown' if verdict == 'FAIL' else ''))
    monkeypatch.setattr(scorekeeper, 'RESULTS_CSV', results)
    monkeypatch.setattr(scorekeeper, 'LEDGER_CSV', tmp_path / 'index.csv')
    monkeypatch.setattr(scorekeeper, 'SUMMARY_MD', tmp_path / 'summary.md')
    scorekeeper.write_summary()
    text = (tmp_path / 'summary.md').read_text()
    assert 'per tier' in text.lower()
    assert '| A | 2 |' in text and '| B | 2 |' in text
    assert '100.0%' in text     # tier A
    assert '50.0%' in text      # tier B


def test_notifier_checkpoint_reports_per_tier():
    n = SessionNotifier()
    for i, (tier, verdict) in enumerate(
            [('A', 'PASS'), ('B', 'PASS'), ('B', 'FAIL'), ('C', 'PASS')]):
        n.session_runs += 1
        n.verdicts[verdict] = n.verdicts.get(verdict, 0) + 1
        n.observe_tier(_row(i, tier, verdict))
    text = n._checkpoint_text()
    assert 'A 100%' in text and 'B 50%' in text and 'C 100%' in text


# ── Case file: tier recorded, signature tier-independent ────────────────────

def test_case_file_records_tier_and_repro(tmp_path, monkeypatch):
    monkeypatch.setattr(scorekeeper, 'FAILURES_DIR', tmp_path / 'failures')
    run_dir = tmp_path / 'runs' / 'r1'
    run_dir.mkdir(parents=True)
    meta = {'run_id': 'r1', 'seed': 9, 'git_sha': 'abc', 'n': 4,
            'orientation': 'NS', 'tier': 0.15, 'difficulty': 'C',
            'harness_version': 'test', 'base_url': 'http://x'}
    grade = {'verdict': 'FAIL', 'failure_category': 'unknown',
             'signature': 'deadbeef1234',
             'checks': [{'check': 'T1-phantom', 'category': 'phantom-movement',
                         'ok': False, 'details': ['x']}],
             'geh': {'worst': 1.0, 'worst_movement': 'AM int 1 EBT',
                     'n_over_marginal': 0, 'n_marginal': 0, 'rows': []}}
    scorekeeper._write_case_file(meta, grade, {}, run_dir)
    report = (tmp_path / 'failures' / 'r1' / 'report.md').read_text()
    assert 'tier C' in report
    assert '--tier C' in report


def test_signature_has_no_tier_input():
    """Same failure shape in two tiers must hash to one signature."""
    failed = [{'check': 'T1-phantom', 'category': 'phantom-movement',
               'ok': False, 'details': []}]
    sig = grader.compute_signature('phantom-movement', failed, [])
    assert sig == grader.compute_signature('phantom-movement', failed, [])
    import inspect
    src = inspect.getsource(grader.compute_signature)
    assert 'tier' not in src, 'signature must stay tier-independent'
