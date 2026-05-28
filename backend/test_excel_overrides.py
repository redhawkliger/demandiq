"""Stage 5 — Excel export honors engineer overrides.
Verifies that project_state.balancing.overrides is reflected in:
  1. The 'AM Balanced' / 'PM Balanced' sheets — cell value carries "*" suffix
  2. The new 'Engineer Overrides' sheet is present + row matches the data
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import io
from openpyxl import load_workbook
from excel_export import build_workbook


def test_export_honors_overrides():
    # Minimal project state with one intersection + one override
    project_state = {
        'project': {'name': 'Test', 'client': '', 'projectNumber': '', 'analyst': '',
                    'checker': '', 'date': '', 'scenario': '', 'projectType': '',
                    'analysisPeriods': ['AM']},
        'intersections': [{
            'num': 5,
            'name': 'Main St & 1st Ave',
            'approaches': {
                'EB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
                'WB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
                'NB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
                'SB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
            },
            'volumes': {'AM': {
                'EBL': {'value': 90, '_source': 'agent'},
                'EBT': {'value': 950, '_source': 'agent'},
                'EBR': {'value': 80, '_source': 'agent'},
            }},
            'balanced': {'AM': {
                'EBL': 95, 'EBT': 1050, 'EBR': 85,
            }},
        }],
        'balancing': {
            'overrides': {
                'AM': {'5': {'EBT': 950}},   # engineer clamped EBT back to raw
                'PM': {},
            },
        },
        'analysis': {'lastRun': {'qcFlags': []}},
    }

    xlsx_bytes = build_workbook(project_state)
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)

    # ── Assert "AM Balanced" sheet shows the override with "*" ─────────
    assert 'AM Balanced' in wb.sheetnames
    ws = wb['AM Balanced']
    # ALL_DIRS = (EB, WB, NB, SB), each contributing 4 columns (U, L, T, R).
    # EB group starts at col 3 → U=3, L=4, T=5, R=6.
    ebt_col = 5
    assert ws.cell(row=2, column=ebt_col).value == 'T', \
        f"row 2 col {ebt_col} should be 'T' subheader; got {ws.cell(row=2, column=ebt_col).value!r}"
    # Row 3 is the first data row (intersection 5 here)
    ebt_cell_value = ws.cell(row=3, column=ebt_col).value
    assert ebt_cell_value == '950*', \
        f"expected '950*' in EBT cell (override applied + marker); got {ebt_cell_value!r}"
    print(f"  AM Balanced EBT cell shows override marker: {ebt_cell_value!r}")

    # ── Assert 'Engineer Overrides' sheet present and correct row ──────
    assert 'Engineer Overrides' in wb.sheetnames
    ovr_ws = wb['Engineer Overrides']
    # Header row at 1, data starts row 2. Expect 1 override row.
    expected_headers = ['Int #', 'Name', 'Period', 'Movement', 'Raw', 'Balanced', 'Override']
    for col, label in enumerate(expected_headers, start=1):
        assert ovr_ws.cell(row=1, column=col).value == label, \
            f"header {col}: got {ovr_ws.cell(row=1, column=col).value!r}, expected {label!r}"
    # Data row
    row2 = [ovr_ws.cell(row=2, column=c).value for c in range(1, 8)]
    assert row2[0] == 5, f"Int #: {row2[0]}"
    assert row2[2] == 'AM', f"Period: {row2[2]}"
    assert row2[3] == 'EBT', f"Movement: {row2[3]}"
    assert row2[4] == 950, f"Raw EBT: {row2[4]}"
    assert row2[5] == 1050, f"Balanced (pre-override) EBT: {row2[5]}"
    assert row2[6] == 950, f"Override EBT: {row2[6]}"
    print(f"  Engineer Overrides sheet row: {row2}")
    print(f"  test_export_honors_overrides: PASS")


def test_export_omits_overrides_sheet_when_empty():
    """No overrides → no Engineer Overrides sheet (clean export)."""
    project_state = {
        'project': {'name': 'Test', 'analysisPeriods': []},
        'intersections': [{
            'num': 1, 'name': 'Foo',
            'approaches': {'EB': {'exists': True, 'lanes': []}},
            'volumes': {'AM': {'EBT': {'value': 100, '_source': 'agent'}}},
            'balanced': {'AM': {'EBT': 100}},
        }],
        'balancing': {'overrides': {'AM': {}, 'PM': {}}},
        'analysis': {'lastRun': {}},
    }
    xlsx_bytes = build_workbook(project_state)
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    assert 'Engineer Overrides' not in wb.sheetnames, \
        f"sheet should be omitted when no overrides; sheets: {wb.sheetnames}"
    print(f"  test_export_omits_overrides_sheet_when_empty: PASS")


def test_combined_view_sheet():
    """Stage 10.2 — Combined View sheet: 7 columns, Δ = Bal − Raw, and
    override balanced cells carry the "*" marker."""
    project_state = {
        'project': {'name': 'Test', 'analysisPeriods': ['AM', 'PM']},
        'intersections': [{
            'num': 3,
            'name': 'Main St & 1st Ave',
            'approaches': {
                'EB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
                'WB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
                'NB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
                'SB': {'exists': True, 'lanes': [{'movement': 'LTR'}]},
            },
            'volumes': {
                'AM': {'EBT': {'value': 1000}, 'EBL': {'value': 80}},
                'PM': {'EBT': {'value': 1200}},
            },
            'balanced': {
                'AM': {'EBT': 1050, 'EBL': 60},   # EBL dropped 80→60
                'PM': {'EBT': 1200},
            },
        }],
        'balancing': {'overrides': {'AM': {'3': {'EBT': 1000}}, 'PM': {}}},
        'analysis': {'lastRun': {'qcFlags': []}},
    }

    xlsx_bytes = build_workbook(project_state)
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)

    assert 'Combined View' in wb.sheetnames, wb.sheetnames
    ws = wb['Combined View']

    # 7-column header
    expected = ['Movement', 'AM Raw', 'AM Balanced', 'AM Δ', 'PM Raw', 'PM Balanced', 'PM Δ']
    actual = [ws.cell(row=1, column=c).value for c in range(1, 8)]
    assert actual == expected, f"header mismatch: {actual}"

    # Find the EBL data row (raw 80, balanced 60 → Δ -20)
    ebl_row = None
    ebt_row = None
    for r in range(2, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if v == 'EBL':
            ebl_row = r
        elif v == 'EBT':
            ebt_row = r
    assert ebl_row, "EBL row not found"
    am_raw = ws.cell(row=ebl_row, column=2).value
    am_bal = ws.cell(row=ebl_row, column=3).value
    am_delta = ws.cell(row=ebl_row, column=4).value
    assert am_raw == 80, am_raw
    assert am_bal == 60, am_bal
    assert am_delta == am_bal - am_raw == -20, am_delta
    print(f"  EBL row: raw={am_raw} bal={am_bal} Δ={am_delta}")

    # EBT AM is overridden (1050 balanced → 1000 override) → "*" marker on balanced
    ebt_am_bal = ws.cell(row=ebt_row, column=3).value
    assert ebt_am_bal == '1000*', f"expected '1000*' override marker; got {ebt_am_bal!r}"
    print(f"  EBT AM override marker: {ebt_am_bal!r}")

    # TOTAL subtotal row present for the section
    totals = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert 'TOTAL' in totals, "TOTAL subtotal row missing"
    print(f"  test_combined_view_sheet: PASS")


if __name__ == '__main__':
    tests = [
        test_export_honors_overrides,
        test_export_omits_overrides_sheet_when_empty,
        test_combined_view_sheet,
    ]
    passed = 0; failed = 0
    for t in tests:
        print(f"Running {t.__name__}...")
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*50}\n  {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
