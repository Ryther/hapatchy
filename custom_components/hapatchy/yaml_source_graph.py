"""Bounded, constructor-free discovery of Home Assistant YAML source files."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from .models import PatchError, Status

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_YAML_TAG = "tag:yaml.org,2002:"
_KNOWN_TAGS = {
    "!include",
    "!include_dir_named",
    "!include_dir_merge_named",
    "!include_dir_list",
    "!include_dir_merge_list",
    "!secret",
    "!env_var",
    "!input",
}
_DIRECTORY_TAGS = _KNOWN_TAGS - {"!include", "!secret", "!env_var", "!input"}
_MAX_FILES = 256
_MAX_INCLUDES = 512
_MAX_LOADS = 512
_MAX_DEPTH = 16
_MAX_DIRECTORIES = 256
_MAX_ENTRIES = 4096
_MAX_FILE_BYTES = 512 * 1024
_MAX_BYTES = 8 * 1024 * 1024
_MAX_EVENTS = 65_536
_MAX_NODES = 65_536
_MAX_NODE_DEPTH = 64
_MAX_OPERAND = 1024


@dataclass(frozen=True)
class SourceFile:
    """Immutable identity and content snapshot of one existing YAML file."""

    path: tuple[str, ...]
    kind: str
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str


@dataclass(frozen=True)
class DirectoryScope:
    """A recursively protected include-directory subtree."""

    path: tuple[str, ...]
    device: int
    inode: int
    mode: int
    inventory: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class SourceGraph:
    """The complete protected source graph, suitable for exact comparison."""

    sources: tuple[SourceFile, ...]
    directories: tuple[DirectoryScope, ...]
    secret_candidates: tuple[tuple[str, ...], ...]

    def protects(self, relative_path: str) -> bool:
        """Return whether a normalized relative path is part of the snapshot."""
        try:
            parts = _parts(relative_path)
        except ValueError:
            return False
        if parts in {source.path for source in self.sources}:
            return True
        if parts in self.secret_candidates:
            return True
        return any(parts[: len(scope.path)] == scope.path for scope in self.directories)


class _Scanner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sources: dict[tuple[str, ...], SourceFile] = {}
        self.directories: dict[tuple[str, ...], DirectoryScope] = {}
        self.secrets: set[tuple[str, ...]] = set()
        self.stack: set[tuple[str, ...]] = set()
        self.includes = self.loads = self.directories_seen = self.entries = 0
        self.total_bytes = self.events = self.nodes = 0

    def scan(self) -> SourceGraph:
        self._load(("configuration.yaml",), 0, "source")
        return SourceGraph(
            tuple(sorted(self.sources.values(), key=lambda source: source.path)),
            tuple(sorted(self.directories.values(), key=lambda scope: scope.path)),
            tuple(sorted(self.secrets)),
        )

    def _load(self, parts: tuple[str, ...], depth: int, kind: str) -> None:
        if depth > _MAX_DEPTH:
            self._deny()
        if parts in self.stack:
            self._deny()
        self.loads += 1
        if self.loads > _MAX_LOADS:
            self._deny()
        data, info = self._read_file(parts)
        self.total_bytes += len(data)
        if self.total_bytes > _MAX_BYTES:
            self._deny()
        digest = hashlib.sha256(data).hexdigest()
        source = SourceFile(
            parts, "yaml", info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, digest,
        )
        previous = self.sources.setdefault(parts, source)
        if previous != source or len(self.sources) > _MAX_FILES:
            self._deny()
        self.stack.add(parts)
        try:
            self._compose_and_visit(data, parts, depth)
        finally:
            self.stack.remove(parts)

    def _compose_and_visit(self, data: bytes, current: tuple[str, ...], depth: int) -> None:
        try:
            for _ in yaml.parse(data, Loader=yaml.Loader):
                self.events += 1
                if self.events > _MAX_EVENTS:
                    self._deny()
            node = yaml.compose(data, Loader=yaml.Loader)
        except PatchError:
            raise
        except yaml.YAMLError:
            self._deny()
        if node is not None:
            self._visit(node, current, depth, 1, set())

    def _visit(
        self,
        node: Node,
        current: tuple[str, ...],
        include_depth: int,
        node_depth: int,
        active: set[int],
    ) -> None:
        if node_depth > _MAX_NODE_DEPTH or id(node) in active:
            self._deny()
        self.nodes += 1
        if self.nodes > _MAX_NODES:
            self._deny()
        if not (node.tag.startswith(_YAML_TAG) or node.tag in _KNOWN_TAGS):
            self._deny()
        if node.tag in _KNOWN_TAGS:
            if not isinstance(node, ScalarNode):
                self._deny()
            if node.tag == "!include":
                operand = self._path_operand(node)
                self.includes += 1
                if self.includes > _MAX_INCLUDES:
                    self._deny()
                self._load(current[:-1] + _parts(operand), include_depth + 1, "include")
            elif node.tag in _DIRECTORY_TAGS:
                operand = self._path_operand(node)
                self.includes += 1
                if self.includes > _MAX_INCLUDES:
                    self._deny()
                self._include_directory(current[:-1] + _parts(operand), include_depth + 1)
            elif node.tag == "!secret":
                self._literal_operand(node)
                self._secret_candidates(current[:-1])
            return
        active.add(id(node))
        try:
            if isinstance(node, SequenceNode):
                for child in node.value:
                    self._visit(child, current, include_depth, node_depth + 1, active)
            elif isinstance(node, MappingNode):
                keys: set[tuple[str, str]] = set()
                for key, value in node.value:
                    if isinstance(key, ScalarNode):
                        marker = (key.tag, key.value)
                        if marker in keys:
                            self._deny()
                        keys.add(marker)
                    self._visit(key, current, include_depth, node_depth + 1, active)
                    self._visit(value, current, include_depth, node_depth + 1, active)
            elif not isinstance(node, ScalarNode):
                self._deny()
        finally:
            active.remove(id(node))

    def _include_directory(self, parts: tuple[str, ...], depth: int) -> None:
        fd, info = self._open_directory(parts)
        try:
            inventory: list[tuple[str, ...]] = []
            files: list[tuple[str, ...]] = []
            self._walk_directory(fd, parts, (), inventory, files)
            scope = DirectoryScope(parts, info.st_dev, info.st_ino, info.st_mode, tuple(sorted(inventory)))
            if self.directories.setdefault(parts, scope) != scope:
                self._deny()
        finally:
            os.close(fd)
        for path in files:
            self._load(path, depth, "include_directory")

    def _walk_directory(
        self, fd: int, scope: tuple[str, ...], relative: tuple[str, ...],
        inventory: list[tuple[str, ...]], files: list[tuple[str, ...]],
    ) -> None:
        self.directories_seen += 1
        if self.directories_seen > _MAX_DIRECTORIES:
            self._deny()
        try:
            iterator = os.scandir(os.dup(fd))
        except OSError:
            self._deny()
        with iterator:
            for entry in iterator:
                name = entry.name
                if name.startswith("."):
                    continue
                self.entries += 1
                if self.entries > _MAX_ENTRIES:
                    self._deny()
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except OSError:
                    self._deny()
                path = scope + relative + (name,)
                if stat.S_ISDIR(info.st_mode):
                    child = self._open_child_directory(fd, name, info)
                    try:
                        self._walk_directory(child, scope, relative + (name,), inventory, files)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1:
                        self._deny()
                    if name != "secrets.yaml" and name.endswith(".yaml"):
                        inventory.append(relative + (name,))
                        files.append(path)
                else:
                    self._deny()

    def _secret_candidates(self, parent: tuple[str, ...]) -> None:
        for index in range(len(parent), -1, -1):
            candidate = parent[:index] + ("secrets.yaml",)
            self.secrets.add(candidate)
            try:
                self._load(candidate, 0, "secret")
            except FileNotFoundError:
                continue

    def _read_file(self, parts: tuple[str, ...]) -> tuple[bytes, os.stat_result]:
        parent, name = self._parent_fd(parts)
        try:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > _MAX_FILE_BYTES:
                self._deny()
            try:
                fd = os.open(name, _FILE, dir_fd=parent)
            except OSError:
                self._deny()
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    self._deny()
                data = bytearray()
                while chunk := os.read(fd, 65536):
                    data.extend(chunk)
                    if len(data) > _MAX_FILE_BYTES:
                        self._deny()
                if _stat_identity(before) != _stat_identity(os.fstat(fd)):
                    self._deny()
                return bytes(data), before
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def _parent_fd(self, parts: tuple[str, ...]) -> tuple[int, str]:
        fd: int | None = None
        try:
            fd = os.open(self.root, _DIRECTORY)
            root_info = self.root.lstat()
            if not stat.S_ISDIR(root_info.st_mode) or (root_info.st_dev, root_info.st_ino) != (os.fstat(fd).st_dev, os.fstat(fd).st_ino):
                self._deny()
            for part in parts[:-1]:
                info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                fd = self._replace_directory(fd, part, info)
            return fd, parts[-1]
        except PatchError:
            if fd is not None:
                os.close(fd)
            raise
        except OSError:
            if fd is not None:
                os.close(fd)
            self._deny()

    def _open_directory(self, parts: tuple[str, ...]) -> tuple[int, os.stat_result]:
        parent, name = self._parent_fd(parts)
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            fd = self._open_child_directory(parent, name, info)
            return fd, info
        finally:
            os.close(parent)

    def _open_child_directory(self, parent: int, name: str, info: os.stat_result) -> int:
        if not stat.S_ISDIR(info.st_mode):
            self._deny()
        try:
            fd = os.open(name, _DIRECTORY, dir_fd=parent)
        except OSError:
            self._deny()
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            os.close(fd)
            self._deny()
        return fd

    def _replace_directory(self, parent: int, name: str, info: os.stat_result) -> int:
        child = self._open_child_directory(parent, name, info)
        os.close(parent)
        return child

    @staticmethod
    def _literal_operand(node: ScalarNode) -> str:
        if not node.value or len(node.value) > _MAX_OPERAND:
            _Scanner._deny()

        if any(ord(char) < 32 for char in node.value):
            _Scanner._deny()
        return node.value

    @staticmethod
    def _path_operand(node: ScalarNode) -> str:
        operand = _Scanner._literal_operand(node)
        try:
            _parts(operand)
        except ValueError:
            _Scanner._deny()
        return operand

    @staticmethod
    def _deny() -> NoReturn:
        raise PatchError("configuration_source_unavailable", Status.SECURITY_ERROR)


def _parts(path: str) -> tuple[str, ...]:
    if not path or path.startswith("/") or "\\" in path or any(ord(char) < 32 for char in path):
        raise ValueError
    parts = tuple(path.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError
    return parts


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def scan_source_graph(root: Path) -> SourceGraph:
    """Return a complete immutable snapshot or deny all source-derived grants."""
    try:
        return _Scanner(root).scan()
    except PatchError:
        raise
    except (OSError, ValueError):
        raise PatchError("configuration_source_unavailable", Status.SECURITY_ERROR) from None
