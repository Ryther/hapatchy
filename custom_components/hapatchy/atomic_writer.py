"""Commit inspected bytes; report honestly when replacement has already happened."""

import os
import stat
from collections.abc import Callable
from uuid import uuid4

from .models import PatchError, Status
from .safe_io import GuardedFile, Snapshot


class CommitError(PatchError):
    def __init__(self, reason: str, *, replaced: bool = False):
        super().__init__(reason, Status.APPLY_ERROR)
        self.replaced = replaced


class AtomicFileWriter:
    def commit(
        self,
        target: GuardedFile,
        snapshot: Snapshot,
        output: bytes,
        *,
        before_replace: Callable[[], object] | None = None,
        before_commit: Callable[[], None] | None = None,
    ) -> None:
        """Caller serializes mutations and keeps the executor transaction tracked."""
        name = f".hapatchy-{uuid4().hex}.tmp"
        replaced = False
        created = False
        try:
            target.verify_snapshot(snapshot)
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=target.parent_fd,
            )
            created = True
            try:
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    stream.write(output)
                    stream.flush()
                current = os.fstat(fd)
                if (current.st_uid, current.st_gid) != (snapshot.info.st_uid, snapshot.info.st_gid):
                    os.fchown(fd, snapshot.info.st_uid, snapshot.info.st_gid)
                os.fchmod(fd, stat.S_IMODE(snapshot.info.st_mode))
                os.fsync(fd)
            finally:
                os.close(fd)
            if before_replace is not None:
                try:
                    before_replace()
                except (OSError, PatchError):
                    raise CommitError("backup_failed") from None
            target.verify_snapshot(snapshot)
            if before_commit is not None:
                before_commit()
            # This check and replace are not compare-and-swap. External updaters
            # must be quiescent during this final interval; see user documentation.
            os.replace(name, target.name, src_dir_fd=target.parent_fd, dst_dir_fd=target.parent_fd)
            replaced = True
            os.fsync(target.parent_fd)
        except OSError:
            raise CommitError(
                "durability_unconfirmed" if replaced else "commit_failed", replaced=replaced
            ) from None
        finally:
            if created and not replaced:
                try:
                    os.unlink(name, dir_fd=target.parent_fd)
                except FileNotFoundError:
                    pass

    def confirm_durability(self, target: GuardedFile, snapshot: Snapshot) -> None:
        target.verify_snapshot(snapshot)
        try:
            os.fsync(target.parent_fd)
        except OSError:
            raise CommitError("durability_unconfirmed", replaced=True) from None
