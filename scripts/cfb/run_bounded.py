"""Run one CI numerical command with a bounded task directory and no parallel jobs."""
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2] / '.codex-tmp' / 'cfb-refit'
LIMIT = 1_500_000_000


def size():
    total = 0
    for folder, _, files in os.walk(ROOT):
        for name in files:
            try:
                info = os.lstat(Path(folder) / name)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def main():
    if len(sys.argv) < 2:
        raise ValueError('Supply a command to run')
    for leaf in ('tmp', 'cache', 'matplotlib', 'jax-cache'):
        (ROOT / leaf).mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(sys.argv[1:], start_new_session=True)
    started = time.monotonic()
    try:
        while process.poll() is None:
            if size() > LIMIT - 100_000_000:
                raise RuntimeError('Stopped before the 1.5 GB task storage ceiling')
            if time.monotonic() - started > 35 * 60:
                raise RuntimeError('Numerical step exceeded 35 minutes; published results are preserved')
            time.sleep(2)
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
