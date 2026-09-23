"""Bounded local and HTTPS sources with exact parser-input hash validation."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path

import aiohttp

from .const import MAX_PATCH_BYTES
from .models import PatchDefinition, PatchError, Status
from .safe_io import GuardedFile


def _local(root: Path, definition: PatchDefinition) -> bytes:
    with GuardedFile(root, definition.source) as source:
        snapshot = source.read(MAX_PATCH_BYTES)
        # Same-inode aliases are also rejected by the single-hardlink requirement.
        try:
            with GuardedFile(root, definition.target_path) as target:
                current = target.read()
        except PatchError as error:
            if error.status != Status.MISSING_TARGET:
                raise
        else:
            if (snapshot.info.st_dev, snapshot.info.st_ino) == (
                current.info.st_dev,
                current.info.st_ino,
            ):
                raise PatchError("source_is_target", Status.SECURITY_ERROR)
        return snapshot.data


def _verify(data: bytes, expected: str | None) -> bytes:
    if expected is not None and hashlib.sha256(data).hexdigest() != expected:
        raise PatchError("source_hash_mismatch", Status.SOURCE_ERROR)
    return data


class PatchSourceClient:
    def __init__(
        self,
        root: Path,
        session: aiohttp.ClientSession | None,
        run_io: Callable[[Callable], Awaitable],
    ):
        self.root, self.session, self.run_io = root, session, run_io

    async def load(self, definition: PatchDefinition) -> bytes:
        try:
            if definition.source_type == "local":
                data = await self.run_io(partial(_local, self.root, definition))
            else:
                assert self.session is not None
                async with self.session.get(
                    definition.source,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        raise PatchError("source_http_error", Status.SOURCE_ERROR)
                    parts = []
                    size = 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > MAX_PATCH_BYTES:
                            raise PatchError("source_too_large", Status.SOURCE_ERROR)
                        parts.append(chunk)
                    data = b"".join(parts)
            return await self.run_io(partial(_verify, data, definition.source_sha256))
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise PatchError("source_unavailable", Status.SOURCE_ERROR) from None
        except PatchError as error:
            if error.status not in (Status.SOURCE_ERROR, Status.SECURITY_ERROR):
                raise PatchError("invalid_local_source", Status.SOURCE_ERROR) from None
            raise
