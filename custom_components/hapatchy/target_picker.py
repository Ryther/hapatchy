"""Bounded suggestions of real targets; manual paths still receive full validation."""

import os
import stat
from collections.abc import Callable
from pathlib import Path

from .models import PatchError, relative_parts
from .path_policy import PathPolicy
from .safe_io import GuardedDirectory

MAX_SUGGESTIONS = 1000
MAX_ENTRIES = 10000
MAX_DEPTH = 16


def list_targets(root: Path, policy: PathPolicy) -> list[str]:
    grants = policy.load_directories()
    results: list[str] = []
    remaining = MAX_ENTRIES

    def visit(parts: tuple[str, ...], check_path: Callable[[str], None]) -> None:
        nonlocal remaining
        if not remaining or len(results) >= MAX_SUGGESTIONS or len(parts) > MAX_DEPTH:
            return
        try:
            with GuardedDirectory(root, parts) as directory:
                with os.scandir(directory.fd) as entries:
                    for entry in entries:
                        if not remaining or len(results) >= MAX_SUGGESTIONS:
                            break
                        remaining -= 1
                        if entry.name.startswith("."):
                            continue
                        path = (*parts, entry.name)
                        try:
                            relative_parts("/".join(path))
                            info = entry.stat(follow_symlinks=False)
                        except (OSError, PatchError):
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            visit(path, check_path)
                        elif parts and stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                            candidate = "/".join(path)
                            try:
                                check_path(candidate)
                            except PatchError:
                                continue
                            results.append(candidate)
                directory.verify()
        except (OSError, PatchError):
            # A disappearing/inaccessible directory is not a reason to block manual input.
            return

    with policy.checked_read_only_paths() as check_path:
        for grant in grants:
            visit(tuple(grant.split("/")), check_path)
    return sorted(set(results))
