"""Descriptor-relative, bounded access to non-aliased configuration files."""

import hashlib
import os
import stat
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from .const import MAX_TARGET_BYTES
from .models import PatchError, Status, relative_parts

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
    )


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    sha256: str
    info: os.stat_result


class GuardedDirectory(AbstractContextManager):
    """Retain and revalidate every directory in the trusted-root traversal."""

    def __init__(self, root: Path, parts: tuple[str, ...] = (), *, create: bool = False):
        self.root = root
        self.parts = parts
        self.create = create
        self.handles: list[int] = []

    @property
    def fd(self) -> int:
        return self.handles[-1]

    def __enter__(self):
        try:
            self.handles.append(os.open(self.root, _DIRECTORY))
            for part in self.parts:
                if self.create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=self.fd)
                        os.fsync(self.fd)
                    except FileExistsError:
                        pass
                self.handles.append(os.open(part, _DIRECTORY, dir_fd=self.fd))
            self.verify()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def verify(self) -> None:
        root_info = self.root.lstat()
        opened = os.fstat(self.handles[0])
        if not stat.S_ISDIR(root_info.st_mode) or (root_info.st_dev, root_info.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise PatchError("directory_changed", Status.SECURITY_ERROR)
        for parent, child, name in zip(self.handles, self.handles[1:], self.parts):
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            opened = os.fstat(child)
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise PatchError("directory_changed", Status.SECURITY_ERROR)

    def __exit__(self, *args):
        for fd in reversed(self.handles):
            os.close(fd)
        self.handles.clear()


class GuardedFile(AbstractContextManager):
    """A verified parent handle; each read captures the current named inode."""

    def __init__(self, root: Path, path: str):
        parts = relative_parts(path)
        self.name = parts[-1]
        self.directory = GuardedDirectory(root, parts[:-1])

    @property
    def parent_fd(self) -> int:
        return self.directory.fd

    def __enter__(self):
        try:
            self.directory.__enter__()
        except FileNotFoundError:
            raise PatchError("missing_target", Status.MISSING_TARGET) from None
        except OSError:
            raise PatchError("unsafe_directory", Status.SECURITY_ERROR) from None
        return self

    def __exit__(self, *args):
        self.directory.__exit__(*args)

    def read(self, limit: int = MAX_TARGET_BYTES) -> Snapshot:
        try:
            self.directory.verify()
            fd = os.open(self.name, _FILE, dir_fd=self.parent_fd)
            try:
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise PatchError("unsafe_file", Status.SECURITY_ERROR)
                if before.st_size > limit:
                    raise PatchError("size_limit")
                chunks = []
                size = 0
                while chunk := os.read(fd, min(65536, limit + 1 - size)):
                    size += len(chunk)
                    if size > limit:
                        raise PatchError("size_limit")
                    chunks.append(chunk)
                if identity(before) != identity(os.fstat(fd)):
                    raise PatchError("target_changed", Status.APPLY_ERROR)
                data = b"".join(chunks)
                return Snapshot(data, hashlib.sha256(data).hexdigest(), before)
            finally:
                os.close(fd)
        except FileNotFoundError:
            raise PatchError("missing_target", Status.MISSING_TARGET) from None
        except OSError:
            raise PatchError("unsafe_file", Status.SECURITY_ERROR) from None

    def verify_snapshot(self, snapshot: Snapshot) -> None:
        current = self.read()
        if identity(current.info) != identity(snapshot.info) or current.sha256 != snapshot.sha256:
            raise PatchError("target_changed", Status.APPLY_ERROR)
