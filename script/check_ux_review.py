"""Fail fast if an unfinished user-experience review marker is present."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MARKER = ".ux-review-required.md"
HEX_SHA = re.compile(r"[0-9a-f]{40}\Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", default="HEAD", help="Exact head commit SHA or HEAD")
    args = parser.parse_args()
    head = args.head
    if head != "HEAD" and not HEX_SHA.fullmatch(head):
        parser.error("head must be HEAD or a 40-character Git SHA")
    committed = subprocess.check_output(["git", "ls-tree", "--name-only", head, "--", MARKER])
    if Path(MARKER).exists() or committed.strip():
        print(f"UX review marker {MARKER} remains in the checkout or commit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"UX review check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
