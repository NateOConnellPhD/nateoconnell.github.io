"""Run one CI numerical command with a bounded task directory and no parallel jobs."""
import os
import json
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2] / '.codex-tmp' / 'cfb-refit'
LIMIT = 1_500_000_000


def storage_report(root=ROOT):
    totals = {}
    for folder, _, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                info = os.lstat(Path(folder) / name)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                relative = (Path(folder) / name).relative_to(root)
                leaf = relative.parts[0] if len(relative.parts) > 1 else '(root files)'
                totals[leaf] = totals.get(leaf, 0) + info.st_size
    return {'total_bytes': sum(totals.values()), 'directory_bytes': totals,
            'stop_at_bytes': LIMIT - 100_000_000, 'ceiling_bytes': LIMIT}


def check_storage(stage):
    report = storage_report(ROOT)
    if stage != 'running' or report['total_bytes'] > report['stop_at_bytes']:
        print(json.dumps({'event': 'task_storage', 'stage': stage, **report}), flush=True)
    if report['total_bytes'] > report['stop_at_bytes']:
        raise RuntimeError('Stopped before the 1.5 GB task storage ceiling; see task_storage directory_bytes')


def main():
    if len(sys.argv) < 2:
        raise ValueError('Supply a command to run')
    for leaf in ('tmp', 'cache', 'matplotlib', 'jax-cache'):
        (ROOT / leaf).mkdir(parents=True, exist_ok=True)
    check_storage('before')
    process = subprocess.Popen(sys.argv[1:], start_new_session=True)
    started = time.monotonic()
    try:
        while process.poll() is None:
            check_storage('running')
            if time.monotonic() - started > 35 * 60:
                raise RuntimeError('Numerical step exceeded 35 minutes; published results are preserved')
            time.sleep(2)
        check_storage('after')
        return process.returncode
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == '__main__':
    raise SystemExit(main())
