"""Pure destination decisions over operator grants and Home Assistant permission."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .models import PatchDefinition, PatchError, Status, relative_parts


class SourceGraph(Protocol):
    def protects(self, path: str) -> bool: ...


class LoadedGrants(Protocol):
    hapatchy_directories: tuple[str, ...]
    ha_explicit_directories: tuple[str, ...]
    graph: SourceGraph

    def check_current(self) -> None: ...


class PathPolicy:
    """Apply the frozen YAML grants, source protection and live HA path check."""

    def __init__(
        self,
        root: Path,
        ha_allowed: Callable[[str], bool],
        grants: LoadedGrants,
    ) -> None:
        self.root = root
        self.ha_allowed = ha_allowed
        self.grants = grants

    @staticmethod
    def _contained(parts: tuple[str, ...], directory: tuple[str, ...], *, equal: bool) -> bool:
        return parts[: len(directory)] == directory and (equal or len(parts) > len(directory))

    def _check_path(self, path: str, *, directory: bool) -> None:
        parts = relative_parts(path)
        if self.grants.graph.protects(path):
            raise PatchError("protected_path", Status.SECURITY_ERROR)
        if not any(
            self._contained(parts, tuple(grant.split("/")), equal=directory)
            for grant in self.grants.hapatchy_directories
        ):
            raise PatchError("hapatchy_path_not_allowed", Status.SECURITY_ERROR)

        absolute = self.root.joinpath(*parts)
        if not any(
            self._contained(absolute.parts, Path(grant).parts, equal=directory)
            for grant in self.grants.ha_explicit_directories
        ):
            raise PatchError("ha_path_not_allowed", Status.SECURITY_ERROR)
        try:
            allowed_by_ha = self.ha_allowed(str(absolute))
        except (OSError, ValueError, RuntimeError):
            allowed_by_ha = False
        if not allowed_by_ha:
            raise PatchError("ha_path_not_allowed", Status.SECURITY_ERROR)

    def check_path(self, path: str, *, directory: bool = False) -> None:
        self.grants.check_current()
        self._check_path(path, directory=directory)

    def check_definition(self, definition: PatchDefinition) -> None:
        self.grants.check_current()
        self._check_path(definition.target_path, directory=False)
        self._check_path(definition.watch_root, directory=True)

    def load_directories(self) -> tuple[str, ...]:
        """Return frozen roots for bounded target suggestions after source verification."""
        self.grants.check_current()
        return self.grants.hapatchy_directories
