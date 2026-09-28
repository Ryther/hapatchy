"""Install a fixed CI requirements lock with bounded retries for index failures."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


def install(lock: str) -> None:
    """Retry the same pinned lock; keep the final pip failure visible to CI."""
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--retries",
        "5",
        "--timeout",
        "25",
        "-r",
        lock,
    ]
    for attempt in range(1, 4):
        print(f"Installing {lock} (attempt {attempt}/3)", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode == 0:
            return
        if attempt == 3:
            raise SystemExit(result.returncode)
        delay = attempt * 10
        print(f"pip failed; retrying in {delay} seconds", file=sys.stderr, flush=True)
        time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", help="Fully pinned requirements file for this CI lane")
    install(parser.parse_args().lock)


if __name__ == "__main__":
    main()
