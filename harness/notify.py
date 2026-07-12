"""Telegram notifier for the Examiner loop — observation only, never control.

Exactly four message types:
  1. checkpoint      — every CHECKPOINT_EVERY runs this session
  2. new signature   — first occurrence of a failure signature, deduped
  3. loop death      — the loop itself crashed (distinct from pipeline-crash,
                       which the loop survives silently)
  4. morning summary — on loop stop or at 7:00 AM local, whichever first

FIREWALLS:
  - Reads results/ledger; never touches the Grader, Puzzler, or any verdict.
  - Silent no-op when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are unset.
  - Every send is wrapped: a notify failure is appended to
    harness_errors.log and swallowed — the loop must never die because a
    message didn't.
  - Stdlib only (urllib), matching the repo's no-new-deps constraint.
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, time as dtime, timedelta, timezone

from .grader import CATEGORY_ORDER
from .scorekeeper import HARNESS_ROOT, LEDGER_CSV, _read_csv

CHECKPOINT_EVERY = 50
MORNING_HOUR = 7                       # 7:00 AM local time
LAST_SESSION_PATH = HARNESS_ROOT / 'last_session.json'
ERROR_LOG = HARNESS_ROOT / 'harness_errors.log'

# Same-named env vars as the standard Telegram Bot API convention. NOTE: the
# repo has no prior Telegram integration to inherit from (the fuzz bot only
# reports through the Actions tab) — these names are this module's contract.
TOKEN_ENV = 'TELEGRAM_BOT_TOKEN'
CHAT_ENV = 'TELEGRAM_CHAT_ID'
# Overridable so tests can point at a local capture server.
API_BASE_ENV = 'TELEGRAM_API_BASE'
DEFAULT_API_BASE = 'https://api.telegram.org'


def enabled():
    return bool(os.environ.get(TOKEN_ENV)) and bool(os.environ.get(CHAT_ENV))


def _log_error(context, err):
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        with open(ERROR_LOG, 'a') as f:
            f.write(f'--- notify {context} at {stamp}: {err}\n')
    except OSError:
        pass   # even the error log must never kill the loop


def send(text):
    """POST one plain-text message. Returns True on success; never raises."""
    if not enabled():
        return False
    try:
        base = os.environ.get(API_BASE_ENV, DEFAULT_API_BASE).rstrip('/')
        token = os.environ[TOKEN_ENV]
        url = f'{base}/bot{token}/sendMessage'
        body = json.dumps({
            'chat_id': os.environ[CHAT_ENV],
            'text': text,
            'disable_web_page_preview': True,
        }).encode()
        req = urllib.request.Request(
            url, data=body, headers={'Content-Type': 'application/json'},
            method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except Exception as e:   # noqa: BLE001 — any notify failure is non-fatal
        _log_error('send', e)
        return False


class SessionNotifier:
    """Per-loop-session observer. Feed it each results row via on_run();
    call on_loop_death() / on_stop() from the loop's exit paths. Every
    public method is a silent no-op when Telegram env vars are absent."""

    def __init__(self, now=None):
        now = now or datetime.now().astimezone()
        self.session_start = now
        self.session_runs = 0
        self.verdicts = {'PASS': 0, 'MARGINAL': 0, 'FAIL': 0}
        self.tier_stats = {}          # tier → {'runs': n, 'pass': n}
        self.category_counts = {}
        self.signature_counts = {}
        self.summary_sent = False
        self._next_morning = self._next_morning_after(now)
        # Dedup seed: signatures already in the ledger never re-notify,
        # even across loop restarts.
        self.seen_signatures = {
            r['signature'] for r in _read_csv(LEDGER_CSV) if r.get('signature')
        }

    @staticmethod
    def _next_morning_after(now):
        morning = datetime.combine(now.date(), dtime(MORNING_HOUR),
                                   tzinfo=now.tzinfo)
        return morning if now < morning else morning + timedelta(days=1)

    # ── event intake ─────────────────────────────────────────────────────

    def observe_tier(self, row):
        """Track per-difficulty-tier pass rates for checkpoint/summary lines."""
        tier = row.get('tier') or 'A'
        s = self.tier_stats.setdefault(tier, {'runs': 0, 'pass': 0})
        s['runs'] += 1
        if row['verdict'] == 'PASS':
            s['pass'] += 1

    def on_run(self, row):
        """Observe one completed run's results row."""
        try:
            self.session_runs += 1
            self.verdicts[row['verdict']] = self.verdicts.get(row['verdict'], 0) + 1
            self.observe_tier(row)
            if row['verdict'] == 'FAIL':
                cat = row.get('failure_category') or ''
                if cat:
                    self.category_counts[cat] = self.category_counts.get(cat, 0) + 1
                # New-signature alert: FAIL signatures only (matches the
                # ledger's dedup scope), first occurrence ever — never
                # per-instance, and never re-sent across loop restarts.
                sig = row.get('signature') or ''
                if sig:
                    self.signature_counts[sig] = self.signature_counts.get(sig, 0) + 1
                    if sig not in self.seen_signatures:
                        self.seen_signatures.add(sig)
                        send(self._new_signature_text(row))

            if self.session_runs % CHECKPOINT_EVERY == 0:
                send(self._checkpoint_text())

            if not self.summary_sent and datetime.now().astimezone() >= self._next_morning:
                self._send_summary('7:00 AM')
        except Exception as e:   # noqa: BLE001
            _log_error('on_run', e)

    def on_loop_death(self, detail):
        try:
            send('☠️ Examiner LOOP DIED — not a pipeline-crash, the loop '
                 f'itself stopped and cannot continue.\n{str(detail)[:600]}\n'
                 f'Session: {self.session_runs} runs before death.')
        except Exception as e:   # noqa: BLE001
            _log_error('on_loop_death', e)

    def on_stop(self):
        """Loop exited (Ctrl-C, --max-runs, or after death notification)."""
        try:
            if not self.summary_sent:
                self._send_summary('loop stop')
        except Exception as e:   # noqa: BLE001
            _log_error('on_stop', e)

    # ── message builders ─────────────────────────────────────────────────

    def _pass_rate(self):
        total = max(1, self.session_runs)
        return 100.0 * self.verdicts.get('PASS', 0) / total

    def _top_signature(self):
        if not self.signature_counts:
            return None
        sig, n = max(self.signature_counts.items(), key=lambda kv: kv[1])
        return f'{sig}×{n}'

    def _per_tier_line(self):
        if not self.tier_stats:
            return None
        parts = []
        for tier in sorted(self.tier_stats):
            s = self.tier_stats[tier]
            parts.append(f"{tier} {100.0 * s['pass'] / s['runs']:.0f}% ({s['runs']})")
        return 'Per tier: ' + ' · '.join(parts)

    def _checkpoint_text(self):
        v = self.verdicts
        cats = ' · '.join(f'{c}×{n}' for c, n in
                          sorted(self.category_counts.items(), key=lambda kv: -kv[1]))
        top = self._top_signature()
        tiers = self._per_tier_line()
        return (f'🧪 Examiner checkpoint — {self.session_runs} runs tonight, '
                f'{self._pass_rate():.0f}% pass '
                f"({v.get('PASS', 0)}P/{v.get('MARGINAL', 0)}M/{v.get('FAIL', 0)}F)"
                + (f'\n{tiers}' if tiers else '')
                + (f'\nFails: {cats}' if cats else '')
                + (f'\nTop signature: {top}' if top else ''))

    def _new_signature_text(self, row):
        return ('🆕 New failure signature '
                f"{row['signature']} — {row.get('failure_category') or 'unknown'}\n"
                f"First seen: run {row['run_id']} (seed {row['seed']}, "
                f"worst GEH {row['worst_geh']})\n"
                f"Repro: python -m harness.run_one --seed {row['seed']}")

    def _summary_text(self, reason, previous):
        v = self.verdicts
        lines = [
            f'🌅 Examiner morning summary ({reason}) — '
            f'{self.session_runs} runs, {self._pass_rate():.0f}% pass '
            f"({v.get('PASS', 0)}P/{v.get('MARGINAL', 0)}M/{v.get('FAIL', 0)}F)",
        ]
        if previous:
            delta = self._pass_rate() - previous.get('pass_rate', 0.0)
            lines.append(
                f"Trend vs previous session: {delta:+.1f} pts "
                f"({previous.get('runs', 0)} runs at "
                f"{previous.get('pass_rate', 0.0):.0f}% pass)")
        else:
            lines.append('Trend: no previous session recorded.')
        tiers = self._per_tier_line()
        if tiers:
            lines.append(tiers)
        ranked = sorted(
            self.category_counts.items(),
            key=lambda kv: (CATEGORY_ORDER.index(kv[0])
                            if kv[0] in CATEGORY_ORDER else 99, -kv[1]))
        if ranked:
            lines.append('Fix first:')
            lines += [f'  {i}. {cat} × {n}' for i, (cat, n) in enumerate(ranked, 1)]
        else:
            lines.append('Fix first: nothing — no failures this session.')
        return '\n'.join(lines)

    # ── summary persistence (for next session's trend) ───────────────────

    def _send_summary(self, reason):
        previous = self._load_last_session()
        send(self._summary_text(reason, previous))
        self.summary_sent = True
        self._save_last_session()

    @staticmethod
    def _load_last_session():
        try:
            with open(LAST_SESSION_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _save_last_session(self):
        try:
            with open(LAST_SESSION_PATH, 'w') as f:
                json.dump({
                    'runs': self.session_runs,
                    'pass_rate': self._pass_rate(),
                    'ended': datetime.now(timezone.utc).isoformat(),
                }, f, indent=2)
        except OSError as e:
            _log_error('save_last_session', e)
