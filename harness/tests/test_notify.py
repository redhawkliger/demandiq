"""Fail-then-pass acceptance tests for the Telegram notifier.

Each of the four message types is simulated and proven to FIRE against a
local capture server (no real Telegram, no network); dedup is proven by
showing the second occurrence does NOT fire; and the no-env path is proven
silent and non-fatal — including a full loop run with a dead backend.

Run: python3.12 -m pytest harness/tests/test_notify.py -q
"""

import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harness import notify
from harness.notify import SessionNotifier


# ── local Telegram capture server ────────────────────────────────────────────

class _Capture(BaseHTTPRequestHandler):
    messages = []   # class-level: [(path, parsed_body)]

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        _Capture.messages.append((self.path, json.loads(body)))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):   # keep pytest output clean
        pass


@pytest.fixture()
def capture(monkeypatch, tmp_path):
    """Start a capture server, point the notifier at it, and isolate every
    file the notifier reads/writes into tmp_path."""
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Capture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Capture.messages = []

    monkeypatch.setenv(notify.TOKEN_ENV, 'test-token')
    monkeypatch.setenv(notify.CHAT_ENV, '4242')
    monkeypatch.setenv(notify.API_BASE_ENV,
                       f'http://127.0.0.1:{server.server_address[1]}')
    monkeypatch.setattr(notify, 'LAST_SESSION_PATH', tmp_path / 'last_session.json')
    monkeypatch.setattr(notify, 'ERROR_LOG', tmp_path / 'errors.log')
    monkeypatch.setattr(notify, 'LEDGER_CSV', tmp_path / 'index.csv')

    yield _Capture.messages
    server.shutdown()
    server.server_close()


def _texts(messages):
    return [body['text'] for _path, body in messages]


def _row(seed=1, verdict='PASS', category='', signature='', run_id=None):
    return {
        'run_id': run_id or f'20260711-000000-seed{seed}',
        'seed': seed, 'verdict': verdict, 'failure_category': category,
        'signature': signature, 'worst_geh': '3.100',
        'worst_movement': 'AM int 1 EBT',
    }


# ── 1. checkpoint every 50 runs ──────────────────────────────────────────────

def test_checkpoint_fires_at_50_runs(capture):
    n = SessionNotifier()
    for i in range(49):
        n.on_run(_row(seed=i))
    assert _texts(capture) == []                     # not yet — 49 runs
    n.on_run(_row(seed=49))
    texts = _texts(capture)
    assert len(texts) == 1                           # fires exactly at 50
    assert 'checkpoint' in texts[0]
    assert '50 runs tonight' in texts[0]
    assert '100% pass' in texts[0]


def test_checkpoint_includes_categories_and_top_signature(capture):
    n = SessionNotifier()
    for i in range(47):
        n.on_run(_row(seed=i))
    for i in range(3):
        n.on_run(_row(seed=100 + i, verdict='FAIL', category='conservation',
                      signature='cafe00000001'))
    texts = _texts(capture)
    checkpoint = texts[-1]
    assert '94% pass' in checkpoint                  # 47/50
    assert 'conservation×3' in checkpoint
    assert 'cafe00000001×3' in checkpoint


# ── 2. new failure signature — first occurrence only ─────────────────────────

def test_new_signature_fires_once_and_dedups(capture):
    n = SessionNotifier()
    n.on_run(_row(seed=7, verdict='FAIL', category='phantom-movement',
                  signature='beef00000001'))
    assert len(capture) == 1                         # fires on first sight
    assert 'New failure signature beef00000001' in _texts(capture)[0]
    assert 'python -m harness.run_one --seed 7' in _texts(capture)[0]

    n.on_run(_row(seed=8, verdict='FAIL', category='phantom-movement',
                  signature='beef00000001'))
    assert len(capture) == 1                         # NEVER per-instance

    n.on_run(_row(seed=9, verdict='FAIL', category='conservation',
                  signature='beef00000002'))
    assert len(capture) == 2                         # distinct signature fires


def test_signatures_already_in_ledger_never_renotify(capture, tmp_path):
    (tmp_path / 'index.csv').write_text(
        'signature,category,count,first_seen,last_seen,example_run_id,status,fixed_by_commit\n'
        'feed00000003,unknown,12,x,x,run-x,open,\n')
    n = SessionNotifier()                            # seeds dedup from ledger
    n.on_run(_row(seed=3, verdict='FAIL', category='unknown',
                  signature='feed00000003'))
    assert capture == []                             # known across restarts


# ── 3. loop death ────────────────────────────────────────────────────────────

def test_loop_death_fires(capture):
    n = SessionNotifier()
    n.on_run(_row(seed=1))
    n.on_loop_death('MemoryError: out of memory')
    texts = _texts(capture)
    assert len(texts) == 1
    assert 'LOOP DIED' in texts[0]
    assert 'MemoryError' in texts[0]
    assert '1 runs before death' in texts[0]


# ── 4. morning summary — loop stop or 7:00 AM, whichever first ───────────────

def test_summary_on_stop_and_trend_next_session(capture):
    n = SessionNotifier()
    for i in range(4):
        n.on_run(_row(seed=i))
    n.on_run(_row(seed=5, verdict='FAIL', category='conservation',
                  signature='dead00000001'))
    n.on_stop()
    texts = _texts(capture)
    summary = texts[-1]
    assert 'morning summary (loop stop)' in summary
    assert '80% pass' in summary                     # 4/5
    assert 'no previous session' in summary
    assert 'Fix first:' in summary and 'conservation × 1' in summary

    # Next session: trend vs the persisted previous session.
    capture.clear()
    n2 = SessionNotifier()
    for i in range(10):
        n2.on_run(_row(seed=i))                      # 100% pass this time
    n2.on_stop()
    summary2 = _texts(capture)[-1]
    assert 'Trend vs previous session: +20.0 pts' in summary2
    assert '5 runs at 80% pass' in summary2


def test_summary_at_7am_fires_first_and_only_once(capture):
    n = SessionNotifier()
    n.on_run(_row(seed=1))
    assert capture == []                             # 7 AM not reached yet
    n._next_morning = datetime.now().astimezone() - timedelta(seconds=1)
    n.on_run(_row(seed=2))                           # crosses the boundary
    texts = _texts(capture)
    assert len(texts) == 1
    assert 'morning summary (7:00 AM)' in texts[0]
    n.on_stop()
    assert len(_texts(capture)) == 1                 # once per session, ever


# ── silent no-op without env vars; loop never fails because notify failed ────

def test_no_env_is_silent_noop(capture, monkeypatch):
    monkeypatch.delenv(notify.TOKEN_ENV)
    monkeypatch.delenv(notify.CHAT_ENV)
    assert not notify.enabled()
    n = SessionNotifier()
    for i in range(50):
        n.on_run(_row(seed=i))                       # checkpoint would fire
    n.on_run(_row(seed=99, verdict='FAIL', signature='aaaa00000001'))
    n.on_loop_death('boom')
    n.on_stop()
    assert capture == []                             # nothing ever sent


def test_loop_runs_clean_without_env_and_with_dead_backend(tmp_path, monkeypatch, capsys):
    from harness import loop, scorekeeper
    monkeypatch.delenv(notify.TOKEN_ENV, raising=False)
    monkeypatch.delenv(notify.CHAT_ENV, raising=False)
    monkeypatch.setenv('ANTHROPIC_API_KEY', '')      # fallback narration
    monkeypatch.setattr(scorekeeper, 'RESULTS_CSV', tmp_path / 'results.csv')
    monkeypatch.setattr(scorekeeper, 'RUNS_DIR', tmp_path / 'runs')
    monkeypatch.setattr(scorekeeper, 'FAILURES_DIR', tmp_path / 'failures')
    monkeypatch.setattr(scorekeeper, 'LEDGER_CSV', tmp_path / 'failures' / 'index.csv')
    monkeypatch.setattr(scorekeeper, 'SUMMARY_MD', tmp_path / 'summary.md')
    monkeypatch.setattr(notify, 'LEDGER_CSV', tmp_path / 'failures' / 'index.csv')
    monkeypatch.setattr(notify, 'LAST_SESSION_PATH', tmp_path / 'last_session.json')

    rc = loop.main(['--start-seed', '1', '--max-runs', '2',
                    '--base-url', 'http://localhost:59999'])
    assert rc == 0                                   # loop green, no notify errors
    assert 'pipeline-crash' in (tmp_path / 'results.csv').read_text()


def test_send_failure_is_logged_never_raised(monkeypatch, tmp_path):
    monkeypatch.setenv(notify.TOKEN_ENV, 'test-token')
    monkeypatch.setenv(notify.CHAT_ENV, '4242')
    monkeypatch.setenv(notify.API_BASE_ENV, 'http://127.0.0.1:59998')  # dead
    monkeypatch.setattr(notify, 'ERROR_LOG', tmp_path / 'errors.log')
    assert notify.send('hello') is False             # no exception
    assert 'notify send' in (tmp_path / 'errors.log').read_text()
