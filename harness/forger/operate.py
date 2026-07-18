"""Forger Operator — runs the REAL S1 extraction path on a generated PDF.

Calls backend/count_agent.extract(path, api_key) directly — the exact
function the webapp's /extract endpoint invokes (app.py:119-120), with no
vendor_hint, mirroring the endpoint. The system under test is an LLM; this
module never interprets its output, it only captures it.

Raw-output capture: count_agent.extract() parses Claude's JSON and discards
the raw text and token usage. To record both WITHOUT modifying
count_agent.py, the Anthropic client constructor is wrapped in-process with
a recording proxy that delegates to the real client and copies out
msg.content[0].text and msg.usage. Observation only — the request itself is
untouched. The patch is restored in a finally block.

Never raises: every failure (missing key, API error, JSON parse failure,
max-tokens truncation) returns ok=False with the error string — the Grader
turns that into a CRASH verdict and a batch continues.
"""

import os
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2] / 'backend'
for p in (str(_BACKEND), str(_BACKEND / 'tools')):
    if p not in sys.path:
        sys.path.insert(0, p)

_UNSET = object()


class _Recording:
    def __init__(self):
        self.raw_text = None
        self.usage = None


def _install_recorder(count_agent, rec):
    """Wrap count_agent's Anthropic constructor with a recording proxy.
    Returns the original for restoration; on any failure returns None and
    the run proceeds unrecorded (capture is best-effort, the verdict never
    depends on it)."""
    try:
        real_cls = count_agent.anthropic.Anthropic

        def recording_ctor(*args, **kwargs):
            client = real_cls(*args, **kwargs)
            real_create = client.messages.create

            def create(**kw):
                msg = real_create(**kw)
                try:
                    rec.raw_text = msg.content[0].text
                    rec.usage = {
                        'input_tokens': msg.usage.input_tokens,
                        'output_tokens': msg.usage.output_tokens,
                    }
                except Exception:      # noqa: BLE001 — capture is best-effort
                    pass
                return msg

            try:
                client.messages.create = create
            except Exception:          # noqa: BLE001
                pass
            return client

        count_agent.anthropic.Anthropic = recording_ctor
        return real_cls
    except Exception:                  # noqa: BLE001
        return None


def run_extraction(pdf_path, api_key=_UNSET):
    """Run the real extractor on one PDF. Returns a dict, never raises:
        ok:        bool
        parsed:    count_agent.extract() result dict | None
        raw_text:  Claude's raw response text | None (best-effort capture)
        usage:     {'input_tokens', 'output_tokens'} | None
        verifier:  count_verifier.verify() result (SKIPPED for PDFs) | None
        error:     str | None
        duration_s: float
    """
    t0 = time.monotonic()
    if api_key is _UNSET:
        api_key = os.environ.get('ANTHROPIC_API_KEY')
    base = {'parsed': None, 'raw_text': None, 'usage': None,
            'verifier': None, 'error': None}
    if not api_key:
        return {**base, 'ok': False,
                'error': 'ANTHROPIC_API_KEY not set — extraction cannot run',
                'duration_s': round(time.monotonic() - t0, 2)}

    import count_agent

    rec = _Recording()
    original = _install_recorder(count_agent, rec)
    try:
        parsed = count_agent.extract(str(pdf_path), api_key)
        ok, error = True, None
    except Exception as e:             # noqa: BLE001 — recorded, not raised
        parsed, ok = None, False
        error = f'{type(e).__name__}: {e}'
    finally:
        if original is not None:
            count_agent.anthropic.Anthropic = original

    verifier = None
    if ok:
        try:
            from count_verifier import verify
            verifier = verify(str(pdf_path), parsed)
        except Exception as e:         # noqa: BLE001
            verifier = {'status': 'ERROR', 'reason': str(e)}

    return {'ok': ok, 'parsed': parsed, 'raw_text': rec.raw_text,
            'usage': rec.usage, 'verifier': verifier, 'error': error,
            'duration_s': round(time.monotonic() - t0, 2)}
