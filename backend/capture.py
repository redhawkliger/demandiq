"""Capture layer — records what the model read and what the engineer corrected.

Every engineer override is a hand-labeled correction produced as a byproduct of
real work: the model said 426, the engineer said 1087, and here is the sheet it
came from. Today that judgment lives in browser state and dies with the tab.
This module writes it down so it can become an evaluation set.

Two recording points, both server-side (no frontend change):

  record_extraction()  at /extract      — what the model read off each file
  record_export()      at /export-excel — raw -> balanced -> engineer final

Join them on source_file to recover (model prediction, human ground truth).

DESIGN RULES
------------
1. Capture must NEVER break a request. Every entry point swallows its own
   exceptions and logs. A failed insert costs a data point; a raised exception
   would cost the engineer their export.
2. Values only — no uploaded file bytes. A sha256 of the content is stored so a
   row can still be matched to a sheet held locally. Flip CAPTURE_STORE_FILES
   if that policy changes; nothing here writes file contents today.
3. Only `_source == 'agent'` cells are model predictions. Hand-typed and pasted
   values are recorded too (with their source) but must be filtered out before
   any accuracy claim — correcting a value you typed yourself says nothing
   about the model.

STORAGE
-------
DATABASE_URL set  -> PostgreSQL (Neon/Supabase). Durable; required in
                     production, because Render's free tier has an EPHEMERAL
                     filesystem — anything on disk is wiped on redeploy and on
                     every cold start, so a SQLite file there collects nothing.
DATABASE_URL unset-> SQLite at CAPTURE_DB_PATH (default backend/captures.db).
                     Fine for local development and tests.
CAPTURE_ENABLED=0 -> disabled entirely (no connection attempted).
"""
import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger('demandiq.capture')

DATABASE_URL = os.getenv('DATABASE_URL') or ''
CAPTURE_ENABLED = os.getenv('CAPTURE_ENABLED', '1') != '0'
CAPTURE_DB_PATH = os.getenv(
    'CAPTURE_DB_PATH', str(Path(__file__).parent / 'captures.db'))

_IS_PG = DATABASE_URL.startswith(('postgres://', 'postgresql://'))
_lock = threading.Lock()
_init_done = False

# The 12 L/T/R movements the app reports on (U-turns excluded, matching the
# Excel Combined View).
MOVEMENTS = (
    'EBL', 'EBT', 'EBR', 'WBL', 'WBT', 'WBR',
    'NBL', 'NBT', 'NBR', 'SBL', 'SBT', 'SBR',
)

_SCHEMA_SQLITE = [
    """CREATE TABLE IF NOT EXISTS extractions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT NOT NULL,
        source_file   TEXT,
        file_sha256   TEXT,
        file_bytes    INTEGER,
        vendor        TEXT,
        model         TEXT,
        ok            INTEGER NOT NULL,
        error         TEXT,
        volumes_json  TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS corrections (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT NOT NULL,
        export_id     TEXT NOT NULL,
        project       TEXT,
        int_num       INTEGER,
        int_name      TEXT,
        source_file   TEXT,
        vendor        TEXT,
        period        TEXT NOT NULL,
        movement      TEXT NOT NULL,
        value_source  TEXT,
        raw_value     REAL,
        balanced_value REAL,
        override_value REAL,
        is_override   INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_corr_override ON corrections (is_override)",
    "CREATE INDEX IF NOT EXISTS ix_corr_source ON corrections (source_file)",
    "CREATE INDEX IF NOT EXISTS ix_extr_source ON extractions (source_file)",
]

# Same shape, Postgres types. SERIAL rather than AUTOINCREMENT.
_SCHEMA_PG = [
    s.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
     .replace('REAL', 'DOUBLE PRECISION')
    for s in _SCHEMA_SQLITE
]


def _connect():
    """Open a connection to whichever store is configured."""
    if _IS_PG:
        import psycopg  # imported lazily: unused (and absent) in local dev
        return psycopg.connect(DATABASE_URL)
    # check_same_thread=False: uvicorn serves requests on a threadpool.
    return sqlite3.connect(CAPTURE_DB_PATH, check_same_thread=False)


def _placeholder():
    return '%s' if _IS_PG else '?'


def _ensure_schema(conn):
    global _init_done
    if _init_done:
        return
    stmts = _SCHEMA_PG if _IS_PG else _SCHEMA_SQLITE
    cur = conn.cursor()
    for stmt in stmts:
        cur.execute(stmt)
    conn.commit()
    _init_done = True


def _insert(table, rows):
    """Insert rows (list of dicts, uniform keys). Returns count written.

    Never raises — capture failing must not fail the request that triggered it.
    """
    if not CAPTURE_ENABLED or not rows:
        return 0
    try:
        with _lock:
            conn = _connect()
            try:
                _ensure_schema(conn)
                cols = list(rows[0].keys())
                ph = ', '.join(_placeholder() for _ in cols)
                sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
                       f"VALUES ({ph})")
                cur = conn.cursor()
                cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
                conn.commit()
                return len(rows)
            finally:
                conn.close()
    except Exception as e:                                   # noqa: BLE001
        log.warning('capture: %s insert failed (%s rows): %s',
                    table, len(rows), e)
        return 0


def _now():
    return datetime.now(timezone.utc).isoformat()


def _num(v):
    """Coerce to float for storage, or None when not numeric."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) \
        else None


# ── Recording points ─────────────────────────────────────────────────────────

def record_extraction(source_file, content, result=None, error=None,
                      model=None):
    """One row per uploaded file: what the model read, and from what.

    `content` is the raw file bytes — hashed, never stored (see DESIGN RULES).
    """
    try:
        sha = hashlib.sha256(content).hexdigest() if content else None
        nbytes = len(content) if content else None
        volumes = None
        vendor = None
        if isinstance(result, dict):
            vendor = result.get('vendor_detected')
            # Store the movement volumes only — not the whole payload, which
            # can carry bulky per-bin detail we do not need to grade a value.
            volumes = json.dumps(result.get('volumes') or {})
        return _insert('extractions', [{
            'ts': _now(),
            'source_file': source_file,
            'file_sha256': sha,
            'file_bytes': nbytes,
            'vendor': vendor,
            'model': model,
            'ok': 0 if error else 1,
            'error': str(error) if error else None,
            'volumes_json': volumes,
        }])
    except Exception as e:                                   # noqa: BLE001
        log.warning('capture: record_extraction failed: %s', e)
        return 0


def record_export(payload):
    """One row per (intersection, period, movement) at export time.

    Reads the snapshot exactly the way the workbook does — same raw-value
    unwrapping, same override lookup — so a captured row can never disagree
    with the number the engineer was looking at when they approved it.
    """
    try:
        # Imported here rather than at module load to keep this module free of
        # a hard dependency on the Excel writer (and its openpyxl import).
        from excel_export import _movement_present, _override_for, _raw_value

        project = (payload.get('project') or {}).get('name')
        intersections = payload.get('intersections') or []
        overrides = ((payload.get('balancing') or {})
                     .get('overrides')) or {'AM': {}, 'PM': {}}
        export_id = uuid.uuid4().hex
        ts = _now()

        rows = []
        for it in intersections:
            balanced = it.get('balanced') or {}
            for period in ('AM', 'PM'):
                period_ovr = overrides.get(period) or {}
                for mv in MOVEMENTS:
                    if not _movement_present(it, mv):
                        continue
                    raw_cell = ((it.get('volumes') or {}).get(period)
                                or {}).get(mv)
                    value_source = (raw_cell.get('_source')
                                    if isinstance(raw_cell, dict) else None)
                    ovr = _override_for(it, period, mv, period_ovr)
                    rows.append({
                        'ts': ts,
                        'export_id': export_id,
                        'project': project,
                        'int_num': it.get('num'),
                        'int_name': it.get('name'),
                        'source_file': it.get('sourceFile'),
                        'vendor': it.get('vendorDetected'),
                        'period': period,
                        'movement': mv,
                        'value_source': value_source,
                        'raw_value': _num(_raw_value(it, period, mv)),
                        'balanced_value': _num((balanced.get(period)
                                                or {}).get(mv)),
                        'override_value': _num(ovr),
                        'is_override': 1 if ovr is not None else 0,
                    })
        return _insert('corrections', rows)
    except Exception as e:                                   # noqa: BLE001
        log.warning('capture: record_export failed: %s', e)
        return 0


def stats():
    """Counts for a quick health check — used by /capture-stats."""
    if not CAPTURE_ENABLED:
        return {'enabled': False}
    out = {'enabled': True, 'backend': 'postgres' if _IS_PG else 'sqlite'}
    try:
        with _lock:
            conn = _connect()
            try:
                _ensure_schema(conn)
                cur = conn.cursor()
                for label, sql in (
                    ('extractions', 'SELECT COUNT(*) FROM extractions'),
                    ('corrections', 'SELECT COUNT(*) FROM corrections'),
                    ('overrides',
                     'SELECT COUNT(*) FROM corrections WHERE is_override = 1'),
                    ('agent_overrides',
                     "SELECT COUNT(*) FROM corrections "
                     "WHERE is_override = 1 AND value_source = 'agent'"),
                ):
                    cur.execute(sql)
                    out[label] = cur.fetchone()[0]
                return out
            finally:
                conn.close()
    except Exception as e:                                   # noqa: BLE001
        return {'enabled': True, 'error': str(e)}
