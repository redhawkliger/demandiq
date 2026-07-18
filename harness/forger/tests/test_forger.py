"""Acceptance tests for the Forger — all offline (no API, no LLM).

The system under test (count_agent) is an LLM; the Forger itself must not
be: sheet generation, PDF rendering, and grading are deterministic seeded
code. These tests pin that contract plus the grader's error taxonomy.

Run: python3.12 -m pytest harness/forger/tests -q
"""

import copy
import csv

import pytest

from harness.forger import grader, operate, scorekeeper, sheets

MOVEMENTS_12 = (
    'EBL', 'EBT', 'EBR', 'WBL', 'WBT', 'WBR',
    'NBL', 'NBT', 'NBR', 'SBL', 'SBT', 'SBR',
)


def _perfect_extraction(sheet):
    """What a flawless extractor would return (count_agent.extract shape)."""
    vols = {}
    for period in ('AM', 'PM'):
        v = {mv: 0 for mv in
             ('EBU', 'EBL', 'EBT', 'EBR', 'WBU', 'WBL', 'WBT', 'WBR',
              'NBU', 'NBL', 'NBT', 'NBR', 'SBU', 'SBL', 'SBT', 'SBR')}
        v.update(sheet['periods'][period])
        vols[period] = v
    return {
        'vendor_detected': 'Counts Unlimited',
        'intersections': [{'name': sheet['intersection_name'],
                           'volumes': vols}],
    }


# ── Forger determinism ───────────────────────────────────────────────────────

def test_sheet_data_deterministic_per_seed_style():
    for style in sheets.STYLES:
        assert sheets.generate_sheet(7, style) == sheets.generate_sheet(7, style)
    assert sheets.generate_sheet(7, 'T') != sheets.generate_sheet(7, 'D')
    assert sheets.generate_sheet(7, 'D') != sheets.generate_sheet(8, 'D')


def test_pdf_bytes_deterministic_per_seed_style():
    for style in sheets.STYLES:
        sheet = sheets.generate_sheet(11, style)
        a = sheets.render_pdf(sheet)
        b = sheets.render_pdf(sheet)
        assert a == b, f'style {style}: PDF bytes not deterministic'
        assert a.startswith(b'%PDF'), f'style {style}: not a PDF'
        assert len(a) > 1000


def test_pdf_marked_forger_synthetic():
    """Corpus firewall: every generated PDF carries forger-synthetic=true in
    its metadata so it can never silently enter a training corpus."""
    for style in sheets.STYLES:
        pdf = sheets.render_pdf(sheets.generate_sheet(3, style))
        assert b'forger-synthetic' in pdf, f'style {style}: marker missing'


def test_volumes_bounds_totals_and_collision_free():
    """12 movements in [5, 1500]; approach totals and grand total derivable;
    all values pairwise >10 apart so exact-match grading is unambiguous
    (a MAP-ERR can never be confused with a DIGIT-ERR)."""
    for seed in range(1, 21):
        sheet = sheets.generate_sheet(seed, 'D')
        for period in ('AM', 'PM'):
            vols = sheet['periods'][period]
            assert set(vols) == set(MOVEMENTS_12)
            assert all(5 <= v <= 1500 for v in vols.values())
            at = sheet['approach_totals'][period]
            for ap in ('NB', 'SB', 'EB', 'WB'):
                assert at[ap] == sum(vols[f'{ap}{t}'] for t in 'LTR')
            assert sheet['grand_total'][period] == sum(vols.values())
            distinct = list(vols.values()) + list(at.values()) \
                + [sheet['grand_total'][period]]
            for i, x in enumerate(distinct):
                for y in distinct[i + 1:]:
                    assert abs(x - y) > 10, \
                        f'seed {seed} {period}: values {x},{y} too close'


# ── Grader taxonomy ──────────────────────────────────────────────────────────

def test_grader_perfect_extraction_passes():
    sheet = sheets.generate_sheet(5, 'D')
    g = grader.grade(sheet, _perfect_extraction(sheet))
    assert g['verdict'] == 'PASS'
    for period in ('AM', 'PM'):
        assert all(r['class'] == 'CORRECT'
                   for r in g['per_movement'][period].values())
        assert g['total_ratio'][period] == pytest.approx(1.0)
    assert g['signature'] == ''


def test_grader_flags_corrupted_value():
    """Acceptance: corrupt one answer-key value in the extraction — the
    Grader must flag that movement (anything but CORRECT) and not PASS."""
    sheet = sheets.generate_sheet(5, 'D')
    ext = _perfect_extraction(sheet)
    ext['intersections'][0]['volumes']['AM']['NBT'] += 400
    g = grader.grade(sheet, ext)
    assert g['verdict'] != 'PASS'
    assert g['per_movement']['AM']['NBT']['class'] != 'CORRECT'


def test_grader_ns_flip_subpattern():
    """Acceptance: a deliberate N/S approach flip must classify as MAP-ERR
    with sub-pattern NS-FLIP on every flipped movement."""
    sheet = sheets.generate_sheet(9, 'D')
    ext = _perfect_extraction(sheet)
    am = ext['intersections'][0]['volumes']['AM']
    for t in 'LTR':
        am[f'NB{t}'], am[f'SB{t}'] = am[f'SB{t}'], am[f'NB{t}']
    g = grader.grade(sheet, ext)
    assert g['verdict'] == 'MAP-FAIL'
    for t in 'LTR':
        for mv in (f'NB{t}', f'SB{t}'):
            row = g['per_movement']['AM'][mv]
            assert row['class'] == 'MAP-ERR', (mv, row)
            assert row['sub'] == 'NS-FLIP', (mv, row)
    assert 'NS-FLIP' in g['map_subpatterns']


def test_grader_ltr_shift_subpattern():
    """L→T→R slot shift within one approach → MAP-ERR / LTR-SHIFT."""
    sheet = sheets.generate_sheet(13, 'D')
    ext = _perfect_extraction(sheet)
    am = ext['intersections'][0]['volumes']['AM']
    true = sheet['periods']['AM']
    am['EBL'], am['EBT'], am['EBR'] = true['EBT'], true['EBR'], true['EBL']
    g = grader.grade(sheet, ext)
    for mv in ('EBL', 'EBT', 'EBR'):
        row = g['per_movement']['AM'][mv]
        assert row['class'] == 'MAP-ERR', (mv, row)
        assert row['sub'] == 'LTR-SHIFT', (mv, row)


def test_grader_total_as_movement():
    """Acceptance: an approach-total (or grand-total) value sitting in a
    movement slot → TOTAL-AS-MOVEMENT."""
    sheet = sheets.generate_sheet(17, 'D')
    ext = _perfect_extraction(sheet)
    ext['intersections'][0]['volumes']['AM']['WBT'] = \
        sheet['approach_totals']['AM']['WB']
    ext['intersections'][0]['volumes']['PM']['EBL'] = \
        sheet['grand_total']['PM']
    g = grader.grade(sheet, ext)
    assert g['per_movement']['AM']['WBT']['class'] == 'TOTAL-AS-MOVEMENT'
    assert g['per_movement']['PM']['EBL']['class'] == 'TOTAL-AS-MOVEMENT'
    assert g['verdict'] == 'MAP-FAIL'


def test_grader_digit_err_and_verdict():
    """Small misread at the right code → DIGIT-ERR; digit errors alone →
    DIGIT-ONLY verdict. 458→456 (±2) and 458→1458 (edit distance 1)."""
    sheet = sheets.generate_sheet(21, 'D')
    ext = _perfect_extraction(sheet)
    am = ext['intersections'][0]['volumes']['AM']
    am['NBL'] = sheet['periods']['AM']['NBL'] + 2
    am['SBR'] = int('1' + str(sheet['periods']['AM']['SBR']))
    g = grader.grade(sheet, ext)
    assert g['per_movement']['AM']['NBL']['class'] == 'DIGIT-ERR'
    assert g['per_movement']['AM']['SBR']['class'] == 'DIGIT-ERR'
    assert g['verdict'] == 'DIGIT-ONLY'


def test_grader_omission_and_hallucination():
    sheet = sheets.generate_sheet(25, 'D')
    ext = _perfect_extraction(sheet)
    am = ext['intersections'][0]['volumes']['AM']
    am['WBL'] = 0                                  # true value > 0 → OMISSION
    am['NBR'] = 4444                               # matches nothing → HALLUCINATION
    g = grader.grade(sheet, ext)
    assert g['per_movement']['AM']['WBL']['class'] == 'OMISSION'
    assert g['per_movement']['AM']['NBR']['class'] == 'HALLUCINATION'
    assert g['verdict'] == 'MIXED'


def test_grader_crash_verdict():
    sheet = sheets.generate_sheet(29, 'D')
    g = grader.grade(sheet, None, error='boom')
    assert g['verdict'] == 'CRASH'
    assert g['signature'] != ''


def test_grader_total_ratio_captures_inflation():
    """The 2.2x symptom: sheet-level extracted/true intersection total."""
    sheet = sheets.generate_sheet(33, 'D')
    ext = _perfect_extraction(sheet)
    am = ext['intersections'][0]['volumes']['AM']
    for mv in MOVEMENTS_12:
        am[mv] = am[mv] * 2
    g = grader.grade(sheet, ext)
    assert g['total_ratio']['AM'] == pytest.approx(2.0)


def test_signatures_dedup_by_style_and_pattern():
    sheet_d = sheets.generate_sheet(9, 'D')
    def flipped(sheet):
        ext = _perfect_extraction(sheet)
        am = ext['intersections'][0]['volumes']['AM']
        for t in 'LTR':
            am[f'NB{t}'], am[f'SB{t}'] = am[f'SB{t}'], am[f'NB{t}']
        return ext
    g1 = grader.grade(sheet_d, flipped(sheet_d))
    sheet_d2 = sheets.generate_sheet(37, 'D')
    g2 = grader.grade(sheet_d2, flipped(sheet_d2))
    assert g1['signature'] == g2['signature'], \
        'same style + same error pattern must dedup to one signature'
    sheet_t = sheets.generate_sheet(9, 'T')
    g3 = grader.grade(sheet_t, flipped(sheet_t))
    assert g3['signature'] != g1['signature'], \
        'same pattern in a different style is a different signature'


# ── Operator: CRASH without an API key ───────────────────────────────────────

def test_operate_records_crash_without_api_key(tmp_path):
    """Acceptance: no ANTHROPIC_API_KEY → the run records a CRASH result and
    returns (never raises), so a batch continues."""
    pdf = tmp_path / 'sheet.pdf'
    pdf.write_bytes(sheets.render_pdf(sheets.generate_sheet(1, 'T')))
    res = operate.run_extraction(str(pdf), api_key=None)
    assert res['ok'] is False
    assert 'ANTHROPIC_API_KEY' in res['error']
    assert res['parsed'] is None


# ── Scorekeeper: variance is data ────────────────────────────────────────────

def _fake_row_inputs(seed, verdict, run_id):
    sheet = sheets.generate_sheet(seed, 'D')
    grade = {'verdict': verdict, 'signature': 'cafe01234567' if verdict != 'PASS' else '',
             'classes': {'MAP-ERR': 2} if verdict == 'MAP-FAIL' else {},
             'map_subpatterns': ['NS-FLIP'] if verdict == 'MAP-FAIL' else [],
             'total_ratio': {'AM': 1.0, 'PM': 1.0},
             'per_movement': {'AM': {}, 'PM': {}}}
    meta = {'run_id': run_id, 'seed': seed, 'style': 'D', 'git_sha': 'test',
            'usage': {'input_tokens': 100, 'output_tokens': 50}}
    return meta, sheet, grade


def test_repeated_seed_rows_recorded_not_averaged(tmp_path, monkeypatch):
    """Acceptance: repeat one seed → one row PER RUN in results.csv, and the
    summary reports the per-seed variance rather than a single average."""
    monkeypatch.setattr(scorekeeper, 'FORGER_ROOT', tmp_path)
    monkeypatch.setattr(scorekeeper, 'RESULTS_CSV', tmp_path / 'results.csv')
    monkeypatch.setattr(scorekeeper, 'RUNS_DIR', tmp_path / 'runs')
    monkeypatch.setattr(scorekeeper, 'FAILURES_DIR', tmp_path / 'failures')
    monkeypatch.setattr(scorekeeper, 'LEDGER_CSV', tmp_path / 'failures' / 'index.csv')
    monkeypatch.setattr(scorekeeper, 'SUMMARY_MD', tmp_path / 'summary.md')

    for i, verdict in enumerate(['PASS', 'MAP-FAIL', 'PASS']):
        meta, sheet, grade = _fake_row_inputs(42, verdict, f'r{i}')
        scorekeeper.record_run(meta, sheet, grade,
                               extraction={'ok': verdict != 'CRASH'},
                               pdf_bytes=b'%PDF-fake')
    rows = list(csv.DictReader(open(tmp_path / 'results.csv')))
    assert len(rows) == 3, 'every repeat run must be its own row'
    assert [r['verdict'] for r in rows] == ['PASS', 'MAP-FAIL', 'PASS']
    summary = (tmp_path / 'summary.md').read_text()
    assert 'variance' in summary.lower()
    assert '42' in summary, 'the repeated seed must appear in the variance section'


def test_case_file_written_on_map_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(scorekeeper, 'FORGER_ROOT', tmp_path)
    monkeypatch.setattr(scorekeeper, 'RESULTS_CSV', tmp_path / 'results.csv')
    monkeypatch.setattr(scorekeeper, 'RUNS_DIR', tmp_path / 'runs')
    monkeypatch.setattr(scorekeeper, 'FAILURES_DIR', tmp_path / 'failures')
    monkeypatch.setattr(scorekeeper, 'LEDGER_CSV', tmp_path / 'failures' / 'index.csv')
    monkeypatch.setattr(scorekeeper, 'SUMMARY_MD', tmp_path / 'summary.md')

    meta, sheet, grade = _fake_row_inputs(7, 'MAP-FAIL', 'rfail')
    scorekeeper.record_run(meta, sheet, grade,
                           extraction={'ok': True, 'raw_text': 'raw'},
                           pdf_bytes=b'%PDF-fake')
    case = tmp_path / 'failures' / 'rfail'
    assert (case / 'sheet.pdf').read_bytes() == b'%PDF-fake'
    assert (case / 'answer_key.json').exists()
    assert (case / 'report.md').exists()
    report = (case / 'report.md').read_text()
    assert '--seed 7 --style D' in report, 'repro command must name seed and style'
    ledger = list(csv.DictReader(open(tmp_path / 'failures' / 'index.csv')))
    assert ledger and ledger[0]['signature'] == 'cafe01234567'
