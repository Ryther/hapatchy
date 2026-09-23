"""Durable preimages and explicit per-patch retention after successful commits."""

import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import PatchError, Status
from .safe_io import GuardedDirectory, Snapshot

_BACKUP_NAME = re.compile(r"\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{32}")


def _write(fd: int, name: str, data: bytes) -> None:
    file_fd = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd
    )
    with os.fdopen(file_fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


class BackupManager:
    def __init__(self, root: Path, patch_id: str, retention: int):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", patch_id):
            raise PatchError("invalid_patch_id", Status.SECURITY_ERROR)
        if type(retention) is not int or not 1 <= retention <= 100:
            raise PatchError("invalid_retention")
        self.root, self.patch_id, self.retention = root, patch_id, retention
        self.parts = (".hapatchy", "backups", patch_id)

    def create(
        self,
        snapshot: Snapshot,
        target_path: str,
        output: bytes,
        source_sha256: str,
        operation: str,
    ) -> str:
        now = datetime.now(UTC)
        name = now.strftime("%Y%m%dT%H%M%S.%fZ-") + uuid4().hex
        metadata = {
            "version": 1,
            "patch_id": self.patch_id,
            "target_path": target_path,
            "operation": operation,
            "timestamp": now.isoformat(),
            "source_sha256": source_sha256,
            "original_sha256": snapshot.sha256,
            "output_sha256": hashlib.sha256(output).hexdigest(),
            "mode": stat.S_IMODE(snapshot.info.st_mode),
        }
        try:
            with GuardedDirectory(self.root, self.parts, create=True) as parent:
                os.mkdir(name, mode=0o700, dir_fd=parent.fd)
                with GuardedDirectory(self.root, (*self.parts, name)) as directory:
                    _write(directory.fd, "target", snapshot.data)
                    _write(
                        directory.fd, "metadata.json", json.dumps(metadata, sort_keys=True).encode()
                    )
                    directory.verify()
                    os.fsync(directory.fd)
                parent.verify()
                os.fsync(parent.fd)
        except OSError:
            raise PatchError("backup_failed", Status.APPLY_ERROR) from None
        return name

    def prune(self) -> None:
        """Never follow links or recursively remove unknown files/directories."""
        try:
            with GuardedDirectory(self.root, self.parts) as parent:
                candidates = []
                for name in sorted(os.listdir(parent.fd)):
                    if not _BACKUP_NAME.fullmatch(name):
                        continue
                    try:
                        with GuardedDirectory(self.root, (*self.parts, name)) as directory:
                            if self._complete(directory):
                                candidates.append(name)
                    except (OSError, PatchError):
                        continue
                for name in candidates[: -self.retention]:
                    with GuardedDirectory(self.root, (*self.parts, name)) as directory:
                        names = set(os.listdir(directory.fd))
                        if names != {"target", "metadata.json"}:
                            continue
                        if any(
                            not stat.S_ISREG(
                                os.stat(item, dir_fd=directory.fd, follow_symlinks=False).st_mode
                            )
                            for item in names
                        ):
                            continue
                        directory.verify()
                        for item in names:
                            os.unlink(item, dir_fd=directory.fd)
                    parent.verify()
                    os.rmdir(name, dir_fd=parent.fd)
                os.fsync(parent.fd)
        except FileNotFoundError:
            return
        except OSError:
            raise PatchError("backup_prune_failed", Status.APPLY_ERROR) from None

    def _complete(self, directory: GuardedDirectory) -> bool:
        """Incomplete attempts must not count toward retention of recovery copies."""
        if set(os.listdir(directory.fd)) != {"target", "metadata.json"}:
            return False
        for name in ("target", "metadata.json"):
            info = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return False
        fd = os.open(
            "metadata.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory.fd
        )
        try:
            raw = os.read(fd, 65537)
        finally:
            os.close(fd)
        if len(raw) > 65536:
            return False
        try:
            metadata = json.loads(raw)
            return (
                isinstance(metadata, dict)
                and metadata.get("version") == 1
                and metadata.get("patch_id") == self.patch_id
                and isinstance(metadata.get("original_sha256"), str)
            )
        except (ValueError, UnicodeError):
            return False
