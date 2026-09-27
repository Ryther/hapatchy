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


class _TargetInventory:
    """Own one discovery budget shared by every authorized directory traversal."""

    def __init__(self, root: Path, check_path: Callable[[str], None]):
        self.root = root
        self.check_path = check_path
        self.results: list[str] = []
        self.remaining = MAX_ENTRIES

    @property
    def full(self) -> bool:
        return not self.remaining or len(self.results) >= MAX_SUGGESTIONS

    def visit(self, parts: tuple[str, ...]) -> None:
        if self.full or len(parts) > MAX_DEPTH:
            return
        try:
            with GuardedDirectory(self.root, parts) as directory:
                with os.scandir(directory.fd) as entries:
                    for entry in entries:
                        if self.full:
                            break
                        self.remaining -= 1
                        self._entry(parts, entry)
                directory.verify()
        except (OSError, PatchError):
            # A disappearing/inaccessible directory must not block manual input.
            return

    def _entry(self, parts: tuple[str, ...], entry: os.DirEntry) -> None:
        if entry.name.startswith("."):
            return
        path = (*parts, entry.name)
        try:
            relative_parts("/".join(path))
            info = entry.stat(follow_symlinks=False)
        except (OSError, PatchError):
            return
        if stat.S_ISDIR(info.st_mode):
            self.visit(path)
        elif parts and stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            candidate = "/".join(path)
            try:
                self.check_path(candidate)
            except PatchError:
                return
            self.results.append(candidate)


def list_targets(root: Path, policy: PathPolicy) -> list[str]:
    grants = policy.load_directories()
    with policy.checked_read_only_paths() as check_path:
        inventory = _TargetInventory(root, check_path)
        for grant in grants:
            inventory.visit(tuple(grant.split("/")))
    return sorted(set(inventory.results))
