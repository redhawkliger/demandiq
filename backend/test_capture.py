"""Acceptance suite for the capture layer.

Fail-then-pass proof for each test is noted inline. Runs fully offline against
a throwaway SQLite file — no network, no Postgres, no API calls.

    cd backend && python3.12 test_capture.py
"""
import os
import sqlite3
import sys
import tempfile

# capture.py reads its storage config at import time, so point it at a scratch
# database BEFORE importing it.
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix='dq_capture_test_'), 'test.db')
os.environ['CAPTURE_DB_PATH'] = _TMP_DB
os.environ.pop('DATABASE_URL', None)      # force the SQLite path
os.environ['CAPTURE_ENABLED'] = '1'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture                                                   # noqa: E402


def _rows(sql, args=()):
    conn = sqlite3.connect(_TMP_DB)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _project_state():
    """A two-intersection snapshot in the shape the frontend persists.

    Int 5 has a full LTR config on every approach; int 6's EB approach does
    not exist, which must keep its EB movements out of the capture entirely.
    """
    full = {d: {'exists': True, 'lanes': [{'movement': 'LTR'}]}
            for d in ('EB', 'WB', 'NB', 'SB')}
    no_eb = dict(full, EB={'exists': False, 'lanes': []})
    return {
        'project': {'name': 'Union City Blvd'},
        'intersections': [
            {
                'num': 5,
                'name': 'UC Blvd & Dyer St',
                'sourceFile': 'CountsUnlimited_Dyer.pdf',
                'vendorDetected': 'Counts Unlimited',
                'approaches': full,
                'volumes': {'AM': {
                    'EBL': {'value': 90, '_source': 'agent'},
                    'EBT': {'value': 950, '_source': 'agent'},
                    # Hand-typed: a correction here says nothing about the model.
                    'EBR': {'value': 80, '_source': 'manual'},
                }},
                'balanced': {'AM': {'EBL': 95, 'EBT': 1050, 'EBR': 85}},
            },
            {
                'num': 6,
                'name': 'UC Blvd & Jean Dr',
                'sourceFile': 'NDS_Jean.pdf',
                'vendorDetected': 'NDS',
                'approaches': no_eb,
                'volumes': {'AM': {'NBT': {'value': 1200, '_source': 'agent'}}},
                'balanced': {'AM': {'NBT': 1210}},
            },
        ],
        'balancing': {'overrides': {'AM': {'5': {'EBT': 950}}, 'PM': {}}},
    }


# ── 1. Export capture writes a row per present movement ─────────────────────
def test_export_rows_written():
    """Fail-then-pass: dropping the _movement_present guard writes EB rows for
    int 6, whose EB approach does not exist, and the count assertion fails."""
    n = capture.record_export(_project_state())
    # Int 5: 12 movements x 2 periods. Int 6: 9 (no EB) x 2.
    assert n == (12 + 9) * 2, f'expected 42 rows, wrote {n}'

    eb6 = _rows("SELECT COUNT(*) FROM corrections "
                "WHERE int_num = 6 AND movement LIKE 'EB%'")[0][0]
    assert eb6 == 0, f'int 6 has no EB approach; captured {eb6} EB rows'
    print('  1. EXPORT ROWS: PASS (42 rows; absent EB approach excluded)')


# ── 2. The override is recorded as raw -> balanced -> engineer value ────────
def test_override_recorded():
    """Fail-then-pass: reading `balanced` into override_value makes this 1050."""
    row = _rows(
        "SELECT raw_value, balanced_value, override_value, is_override "
        "FROM corrections WHERE int_num = 5 AND period = 'AM' "
        "AND movement = 'EBT'")
    assert len(row) == 1, f'expected one EBT row, got {len(row)}'
    raw, bal, ovr, is_ovr = row[0]
    assert (raw, bal, ovr, is_ovr) == (950.0, 1050.0, 950.0, 1), row[0]

    # A movement the engineer left alone carries no override.
    ebl = _rows("SELECT override_value, is_override FROM corrections "
                "WHERE int_num = 5 AND period = 'AM' AND movement = 'EBL'")[0]
    assert ebl == (None, 0), f'EBL was not overridden, got {ebl}'
    print('  2. OVERRIDE RECORDED: PASS (950 raw -> 1050 balanced -> 950 final)')


# ── 3. Model predictions are distinguishable from hand-entered values ───────
def test_value_source_preserved():
    """Without this, a correction to a value the engineer typed themselves
    would be counted as a model error and poison the evaluation set."""
    got = dict(_rows(
        "SELECT movement, value_source FROM corrections "
        "WHERE int_num = 5 AND period = 'AM' AND movement IN "
        "('EBL','EBR','WBL')"))
    assert got['EBL'] == 'agent', got
    assert got['EBR'] == 'manual', got
    # A movement with no volume cell at all has no source.
    assert got['WBL'] is None, got
    print('  3. VALUE SOURCE: PASS (agent / manual / absent all distinct)')


# ── 4. Provenance survives, so a correction maps back to its sheet ──────────
def test_provenance_captured():
    row = _rows("SELECT DISTINCT source_file, vendor, project FROM corrections "
                "WHERE int_num = 5")
    assert row == [('CountsUnlimited_Dyer.pdf', 'Counts Unlimited',
                    'Union City Blvd')], row
    print('  4. PROVENANCE: PASS (file + vendor + project on every row)')


# ── 5. Extraction capture hashes content and never stores bytes ─────────────
def test_extraction_recorded():
    content = b'%PDF-1.4 fake sheet bytes'
    capture.record_extraction(
        'Quality_Dyer.pdf', content,
        result={'vendor_detected': 'Quality Counts',
                'volumes': {'AM': {'EBL': 90}}},
        model='claude-sonnet-4-5')
    row = _rows("SELECT source_file, file_sha256, file_bytes, vendor, model, "
                "ok, error FROM extractions WHERE source_file = ?",
                ('Quality_Dyer.pdf',))[0]
    import hashlib
    assert row[1] == hashlib.sha256(content).hexdigest(), 'sha256 mismatch'
    assert row[2] == len(content) and row[3] == 'Quality Counts'
    assert row[5] == 1 and row[6] is None, row

    # The file bytes themselves must appear nowhere in the database.
    blob = open(_TMP_DB, 'rb').read()
    assert b'fake sheet bytes' not in blob, 'file content was stored'
    print('  5. EXTRACTION + HASH: PASS (hash stored, bytes never persisted)')


# ── 6. A failed extraction is recorded too ──────────────────────────────────
def test_extraction_failure_recorded():
    """Failures are the most interesting rows — they mark files the pipeline
    cannot read at all."""
    capture.record_extraction('broken.xls', b'junk',
                              error=ValueError('unreadable'))
    ok, err = _rows("SELECT ok, error FROM extractions "
                    "WHERE source_file = 'broken.xls'")[0]
    assert ok == 0 and 'unreadable' in err, (ok, err)
    print('  6. FAILURE RECORDED: PASS')


# ── 7. Capture must never break the request that triggered it ───────────────
def test_capture_never_raises():
    """Fail-then-pass: removing the try/except in record_export turns each of
    these into an exception instead of a 0."""
    for bad in ({}, {'intersections': 'not-a-list'},
                {'intersections': [{'num': 1, 'volumes': None}]},
                {'intersections': [None]}):
        assert capture.record_export(bad) == 0, f'should no-op on {bad}'
    assert capture.record_extraction(None, None) >= 0
    print('  7. NEVER RAISES: PASS (malformed payloads no-op, never throw)')


# ── 8. Stats report what has accumulated ────────────────────────────────────
def test_stats():
    s = capture.stats()
    assert s['enabled'] is True and s['backend'] == 'sqlite', s
    assert s['corrections'] == 42, s
    assert s['overrides'] == 1, s
    # The single override was on an 'agent' value, so it counts as a model
    # correction; a 'manual' one would not.
    assert s['agent_overrides'] == 1, s
    print(f"  8. STATS: PASS ({s['corrections']} rows, "
          f"{s['agent_overrides']} model corrections)")


if __name__ == '__main__':
    print('\nCapture layer:\n')
    tests = [
        test_export_rows_written,
        test_override_recorded,
        test_value_source_preserved,
        test_provenance_captured,
        test_extraction_recorded,
        test_extraction_failure_recorded,
        test_capture_never_raises,
        test_stats,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f'  ✗ {t.__name__}: {e}')
        except Exception as e:                               # noqa: BLE001
            failed += 1
            print(f'  ✗ {t.__name__}: unexpected {type(e).__name__}: {e}')
    print(f'\n  {len(tests) - failed} passed, {failed} failed\n')
    sys.exit(1 if failed else 0)
