"""Private, content-addressed patch revisions; configuration stores only their digest."""

import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from .const import MAX_PATCH_BYTES
from .models import PatchError, Status
from .safe_io import GuardedDirectory, GuardedFile

REVISION = re.compile(r"[0-9a-f]{64}")
PARTS = (".hapatchy", "patches")


def validate_content(data: bytes) -> None:
    if not data or len(data) > MAX_PATCH_BYTES:
        raise PatchError("source_too_large" if data else "empty_patch", Status.INVALID_PATCH)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchError("invalid_encoding", Status.INVALID_PATCH) from None


class ManagedPatchStore:
    """Publish complete revisions without overwriting prior content or following links."""

    def __init__(self, root: Path):
        self.root = root

    def _read(self, revision: str) -> bytes:
        if not REVISION.fullmatch(revision):
            raise PatchError("invalid_managed_source", Status.SECURITY_ERROR)
        with GuardedFile(self.root, f".hapatchy/patches/{revision}.patch", internal=True) as file:
            data = file.read(MAX_PATCH_BYTES).data
        if hashlib.sha256(data).hexdigest() != revision:
            raise PatchError("source_hash_mismatch", Status.SOURCE_ERROR)
        return data

    def load(self, revision: str) -> bytes:
        try:
            return self._read(revision)
        except PatchError as error:
            if error.status == Status.MISSING_TARGET:
                raise PatchError("managed_source_unavailable", Status.SOURCE_ERROR) from None
            raise

    def save(self, data: bytes) -> str:
        validate_content(data)
        revision = hashlib.sha256(data).hexdigest()
        temporary = f".pending-{uuid4().hex}"
        try:
            with GuardedDirectory(self.root, PARTS, create=True) as directory:
                try:
                    self._read(revision)
                except PatchError as error:
                    if error.status != Status.MISSING_TARGET:
                        raise
                else:
                    directory.verify()
                    os.fsync(directory.fd)
                    return revision
                fd = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory.fd,
                )
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    directory.verify()
                    try:
                        os.link(
                            temporary,
                            f"{revision}.patch",
                            src_dir_fd=directory.fd,
                            dst_dir_fd=directory.fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        # Concurrent publication may already own this digest. Never replace it.
                        self._read(revision)
                finally:
                    os.unlink(temporary, dir_fd=directory.fd)
                directory.verify()
                os.fsync(directory.fd)
                self._read(revision)
        except OSError:
            raise PatchError("managed_source_write_failed", Status.SOURCE_ERROR) from None
        return revision
