"""Owned data shared by the pure engine and Home Assistant adapters."""

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from watchdog.utils.patterns import match_any_paths


class Status(StrEnum):
    UNKNOWN = "unknown"
    DISABLED = "disabled"
    APPLICABLE = "applicable"
    APPLIED = "applied"
    CONFLICT = "conflict"
    MISSING_TARGET = "missing_target"
    SOURCE_ERROR = "source_error"
    INVALID_PATCH = "invalid_patch"
    SECURITY_ERROR = "security_error"
    APPLY_ERROR = "apply_error"


class PatchError(ValueError):
    """Controlled reason codes, never file contents or underlying exceptions."""

    def __init__(self, reason: str, status: Status = Status.INVALID_PATCH) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class PatchInspection:
    status: Status
    reason: str | None = None
    forward_output: bytes | None = None
    reverse_output: bytes | None = None


def relative_parts(path: str, *, internal: bool = False) -> tuple[str, ...]:
    """Validate lexical paths before any filesystem operation."""
    parts = tuple(path.split("/"))
    if any(part in ("", ".", "..") for part in parts) or any(
        char in path for char in ("\\", "\x00", "\n", "\r", "\t")
    ):
        raise PatchError("unsafe_path", Status.SECURITY_ERROR)
    if not internal and (
        parts[0] in (".storage", ".hapatchy") or parts[:2] == ("custom_components", "hapatchy")
    ):
        raise PatchError("protected_path", Status.SECURITY_ERROR)
    return parts


@dataclass(frozen=True)
class PatchDefinition:
    patch_id: str
    name: str
    target_path: str
    watch_root: str
    watch_pattern: str
    source_type: str
    source: str
    enabled: bool = True
    auto_apply: bool = True
    reconcile_on_startup: bool = True
    backup_before_apply: bool = True
    debounce_seconds: float = 1.5
    source_sha256: str | None = None

    @classmethod
    def from_mapping(cls, patch_id: str, data: dict[str, Any]) -> "PatchDefinition":
        for field in ("name", "target_path", "watch_root", "source_type", "source"):
            if not isinstance(data.get(field), str) or not data[field].strip():
                raise PatchError("required_field")
        target = relative_parts(data["target_path"])
        root = relative_parts(data["watch_root"])
        if target[: len(root)] != root or len(target) <= len(root):
            raise PatchError("target_outside_watch_root", Status.SECURITY_ERROR)
        relative = "/".join(target[len(root) :])
        pattern = data.get("watch_pattern") or relative
        if not isinstance(pattern, str) or not match_any_paths(
            [relative], included_patterns=[pattern], case_sensitive=True
        ):
            raise PatchError("pattern_misses_target")
        source_type, source = data["source_type"], data["source"]
        if source_type == "local":
            if relative_parts(source) == target:
                raise PatchError("source_is_target", Status.SECURITY_ERROR)
        elif source_type == "managed":
            if not re.fullmatch(r"[0-9a-f]{64}", source):
                raise PatchError("invalid_managed_source", Status.SECURITY_ERROR)
        elif source_type == "url":
            try:
                url = urlsplit(source)
                port = url.port
                valid = (
                    url.scheme == "https"
                    and url.hostname
                    and url.username is None
                    and url.password is None
                    and "#" not in source
                    and not any(char.isspace() or ord(char) < 32 for char in source)
                    and (port is None or 1 <= port <= 65535)
                )
            except ValueError:
                valid = False
            if not valid:
                raise PatchError("invalid_source_url", Status.SECURITY_ERROR)
        else:
            raise PatchError("invalid_source_type")
        flags = {}
        for key in ("enabled", "auto_apply", "reconcile_on_startup", "backup_before_apply"):
            value = data.get(key, True)
            if type(value) is not bool:
                raise PatchError("invalid_boolean")
            flags[key] = value
        debounce = data.get("debounce_seconds", 1.5)
        if (
            type(debounce) not in (float, int)
            or not math.isfinite(debounce)
            or not 0.1 <= debounce <= 60
        ):
            raise PatchError("invalid_debounce")
        digest = data.get("source_sha256") or None
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
        ):
            raise PatchError("invalid_source_hash")
        return cls(
            patch_id,
            data["name"],
            data["target_path"],
            data["watch_root"],
            pattern,
            source_type,
            source,
            debounce_seconds=float(debounce),
            source_sha256=digest.lower() if digest else None,
            **flags,
        )


@dataclass
class PatchRuntimeState:
    status: Status = Status.UNKNOWN
    watcher_available: bool = False
    last_checked_at: str | None = None
    last_applied_at: str | None = None
    target_sha256: str | None = None
    patch_sha256: str | None = None
    last_error: str | None = None
    restart_may_be_required: bool = False
