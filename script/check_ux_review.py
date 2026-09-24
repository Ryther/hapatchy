"""Fail fast when user-visible product changes lack revision evidence."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MARKER = ".ux-review-required.md"
EVIDENCE = "docs/verification.md"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
HEX_SHA = re.compile(r"[0-9a-f]{40}\Z")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def revision(value: str) -> str:
    if value == "HEAD" or HEX_SHA.fullmatch(value):
        return value
    raise ValueError("revision must be HEAD or a 40-character Git SHA")


def changed_paths(base: str, head: str) -> list[tuple[str, tuple[str, ...]]]:
    raw = git("diff", "--name-status", "-z", "--find-renames", base, head, "--")
    parts = raw.split(b"\0")
    changes = []
    index = 0
    while index < len(parts) - 1:
        status = parts[index].decode("ascii")
        index += 1
        count = 2 if status.startswith(("R", "C")) else 1
        paths = tuple(parts[index + offset].decode("utf-8", "surrogateescape") for offset in range(count))
        index += count
        changes.append((status, paths))
    return changes


def product_path(path: str) -> bool:
    if path == "hacs.json":
        return True
    prefix = "custom_components/hapatchy/"
    if not path.startswith(prefix):
        return False
    relative = path[len(prefix) :]
    return (
        relative.endswith(".py")
        or relative in ("strings.json", "services.yaml", "manifest.json")
        or relative.startswith("brand/")
        or (relative.startswith("translations/") and relative.endswith(".json"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Base commit SHA; omit for marker-only check")
    parser.add_argument("--head", default="HEAD", help="Exact head commit SHA or HEAD")
    args = parser.parse_args()
    head = revision(args.head)
    if Path(MARKER).exists() or git("ls-tree", "--name-only", head, "--", MARKER).strip():
        print(f"UX review marker {MARKER} remains in the checkout or commit", file=sys.stderr)
        return 1
    if args.base is None:
        return 0
    base = args.base.lower()
    if base == "0" * 40:
        base = EMPTY_TREE
    else:
        base = revision(base)
    changes = changed_paths(base, head)
    product_changed = any(product_path(path) for _, paths in changes for path in paths)
    evidence_changed = any(
        status[0] in ("A", "M", "R", "C") and paths[-1] == EVIDENCE
        for status, paths in changes
    )
    evidence_at_head = subprocess.run(
        ["git", "cat-file", "-e", f"{head}:{EVIDENCE}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if product_changed and not (evidence_changed and evidence_at_head):
        print("Product changes require an updated docs/verification.md in this change", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"UX review check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None
