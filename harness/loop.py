"""Examiner orchestrator — infinite unattended loop.

    caffeinate -i python -m harness.loop            # run all night
    python -m harness.loop --start-seed 1000        # resume elsewhere
    python -m harness.loop --max-runs 20            # bounded (soak/testing)

Survives backend death: a dead/500ing backend records a `pipeline-crash`
verdict for that seed and the loop moves to the next one. An unexpected
harness-side exception is logged to harness/harness_errors.log and the loop
continues — the Examiner must outlive everything except Ctrl-C.
"""

import argparse
import sys
import time
import traceback
from datetime import datetime, timezone

from . import operate
from .notify import SessionNotifier
from .runner import execute_run, print_row
from .scorekeeper import HARNESS_ROOT

ERROR_LOG = HARNESS_ROOT / 'harness_errors.log'


def main(argv=None):
    p = argparse.ArgumentParser(description='Run the Examiner forever.')
    p.add_argument('--start-seed', type=int, default=1)
    p.add_argument('--max-runs', type=int, default=0,
                   help='stop after N runs (0 = forever)')
    p.add_argument('--base-url', default=operate.DEFAULT_BASE_URL)
    p.add_argument('--sleep', type=float, default=0.0,
                   help='seconds between runs (default 0)')
    args = p.parse_args(argv)

    # Observation only: the notifier reads results rows, never influences
    # them, and is a silent no-op without Telegram env vars.
    notifier = SessionNotifier()

    seed = args.start_seed
    done = 0
    try:
        while True:
            try:
                row = execute_run(seed, base_url=args.base_url)
                print_row(row)
                notifier.on_run(row)
            except KeyboardInterrupt:
                raise
            except Exception:
                stamp = datetime.now(timezone.utc).isoformat()
                with open(ERROR_LOG, 'a') as f:
                    f.write(f'--- seed {seed} at {stamp}\n')
                    f.write(traceback.format_exc())
                print(f'[harness-error] seed={seed} — logged to '
                      f'{ERROR_LOG.name}, continuing', file=sys.stderr)
            seed += 1
            done += 1
            if args.max_runs and done >= args.max_runs:
                break
            if args.sleep:
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        print(f'\nstopped at seed {seed} after {done} run(s)', file=sys.stderr)
    except BaseException as e:
        # The loop ITSELF is dying — per-seed failures are absorbed above, so
        # anything landing here means the loop cannot continue. Distinct
        # message type from pipeline-crash (which the loop survives silently).
        notifier.on_loop_death(f'{type(e).__name__}: {e}\n'
                               f'{traceback.format_exc()[-500:]}')
        raise
    finally:
        notifier.on_stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
