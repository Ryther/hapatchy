"""Strict unified-diff parser adapter and pure, unique full-context matching."""

import re
from dataclasses import dataclass

import patch_ng

from .const import MAX_PATCH_BYTES, MAX_TARGET_BYTES
from .models import PatchError, PatchInspection, Status

_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?")
_NO_NEWLINE = "\\ No newline at end of file"


@dataclass(frozen=True)
class Hunk:
    before: bytes
    after: bytes


@dataclass(frozen=True)
class ParsedPatch:
    target: str
    hunks: tuple[Hunk, ...]


def _text(data: bytes, limit: int) -> tuple[str, bool]:
    if len(data) > limit:
        raise PatchError("size_limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchError("unsupported_encoding") from None
    if "\x00" in text:
        raise PatchError("unsupported_encoding")
    crlf = "\r\n" in text
    if "\r" in text.replace("\r\n", "") or (crlf and "\n" in text.replace("\r\n", "")):
        raise PatchError("mixed_endings")
    return text.replace("\r\n", "\n"), crlf


def _path(path: str) -> str:
    if not path or any(part in ("", ".", "..") for part in path.split("/")):
        raise PatchError("unsafe_path", Status.SECURITY_ERROR)
    if any(char in path for char in ("\\", "\x00", "\t", "\n", "\r")):
        raise PatchError("unsafe_path", Status.SECURITY_ERROR)
    return path


def _headers(lines: list[str], target: str) -> int:
    start = 0
    if lines and lines[0].startswith("diff --git "):
        if lines[0] != f"diff --git a/{target} b/{target}":
            raise PatchError("header_target_mismatch")
        start = 1
        if len(lines) > start and re.fullmatch(
            r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100(?:644|755))?", lines[start]
        ):
            start += 1
    if (
        len(lines) < start + 3
        or not lines[start].startswith("--- ")
        or not lines[start + 1].startswith("+++ ")
    ):
        raise PatchError("invalid_headers")
    old, new = (line[4:].split("\t", 1)[0] for line in lines[start : start + 2])
    if old.startswith("a/") and new.startswith("b/"):
        old, new = old[2:], new[2:]
    if _path(old) != target or _path(new) != target:
        raise PatchError("header_target_mismatch")
    return start + 2


def _hunk_header(line: str) -> tuple[int, int, int, int]:
    match = _HUNK.fullmatch(line)
    if not match:
        raise PatchError("invalid_hunk")
    old_start, old_count, new_start, new_count = (int(value or "1") for value in match.groups())
    if min(old_start, old_count, new_start, new_count) < 1:
        raise PatchError("unanchored_hunk")
    return old_start, old_count, new_start, new_count


def _append_line(lines: list[str], value: str) -> None:
    if lines and not lines[-1].endswith("\n"):
        raise PatchError("invalid_newline_marker")
    lines.append(value)


def _read_hunk(
    lines: list[str], index: int, old_count: int, new_count: int
) -> tuple[Hunk, list[bytes], int]:
    """Preserve newline markers in owned records and raw body bytes for parser checks."""
    old: list[str] = []
    new: list[str] = []
    body: list[bytes] = []
    while index < len(lines) and not lines[index].startswith("@@ "):
        line = lines[index]
        if not line or line[0] not in " +-":
            raise PatchError("invalid_hunk_body")
        prefix, value = line[0], line[1:] + "\n"
        body.append((line + "\n").encode("utf-8"))
        index += 1
        if index < len(lines) and lines[index] == _NO_NEWLINE:
            value = value[:-1]
            index += 1
        if prefix in " -":
            _append_line(old, value)
        if prefix in " +":
            _append_line(new, value)
    if len(old) != old_count or len(new) != new_count:
        raise PatchError("hunk_count_mismatch")
    if old == new:
        raise PatchError("no_change")
    return Hunk("".join(old).encode("utf-8"), "".join(new).encode("utf-8")), body, index


def _unique_location(original: bytes, before: bytes) -> int | None:
    """Require one whole-line context match in the unchanged original bytes."""
    location = None
    position = original.find(before)
    while position >= 0:
        end = position + len(before)
        if (position == 0 or original[position - 1 : position] == b"\n") and (
            before.endswith(b"\n") or end == len(original)
        ):
            if location is not None:
                return None
            location = position
        position = original.find(before, position + 1)
    return location


class UnifiedDiffEngine:
    """Never mutates files or calls the third-party applicator."""

    def parse(self, raw: bytes, target: str) -> ParsedPatch:
        target = _path(target)
        text, _ = _text(raw, MAX_PATCH_BYTES)
        if not text.endswith("\n"):
            raise PatchError("unterminated_diff")
        lines = text[:-1].split("\n")
        index = _headers(lines, target)
        records: list[Hunk] = []
        bodies: list[list[bytes]] = []
        previous_old = previous_new = 0
        while index < len(lines):
            old_start, old_count, new_start, new_count = _hunk_header(lines[index])
            if old_start < previous_old or new_start < previous_new:
                raise PatchError("overlapping_hunks")
            previous_old, previous_new = old_start + old_count, new_start + new_count
            record, body, index = _read_hunk(lines, index + 1, old_count, new_count)
            records.append(record)
            bodies.append(body)
        if not records:
            raise PatchError("no_hunks")
        # Envelope checks run first: patch-ng is permissive about ignored material.
        # Its parser validates hunk records; our owned records additionally preserve
        # no-final-newline information that patch-ng's applicator does not support.
        parsed = patch_ng.fromstring(text.encode("utf-8"))
        if not parsed or len(parsed.items) != 1 or len(parsed.items[0].hunks) != len(records):
            raise PatchError("parser_rejected")
        for hunk, body in zip(parsed.items[0].hunks, bodies, strict=True):
            actual = [line for line in hunk.text if not line.startswith(b"\\")]
            if hunk.invalid or actual != body:
                raise PatchError("parser_mismatch")
        return ParsedPatch(target, tuple(records))

    @staticmethod
    def _direction(hunks: tuple[Hunk, ...], original: bytes, reverse: bool) -> bytes | None:
        replacements: list[tuple[int, int, bytes]] = []
        previous_end = 0
        for hunk in hunks:
            before, after = (hunk.after, hunk.before) if reverse else (hunk.before, hunk.after)
            start = _unique_location(original, before)
            if start is None or start < previous_end:
                return None
            previous_end = start + len(before)
            replacements.append((start, previous_end, after))
        pieces: list[bytes] = []
        cursor = 0
        for start, end, replacement in replacements:
            pieces.extend((original[cursor:start], replacement))
            cursor = end
        pieces.append(original[cursor:])
        return b"".join(pieces)

    def inspect(self, patch: ParsedPatch, raw: bytes) -> PatchInspection:
        try:
            text, crlf = _text(raw, MAX_TARGET_BYTES)
        except PatchError as error:
            return PatchInspection(error.status, error.reason)
        original = text.encode("utf-8")
        forward = self._direction(patch.hunks, original, False)
        reverse = self._direction(patch.hunks, original, True)
        if forward is not None and reverse is not None:
            return PatchInspection(Status.INVALID_PATCH, "ambiguous_direction")
        if forward is None and reverse is None:
            return PatchInspection(Status.CONFLICT, "context_not_unique")
        output = forward if forward is not None else reverse
        assert output is not None
        if crlf:
            output = output.replace(b"\n", b"\r\n")
        if len(output) > MAX_TARGET_BYTES:
            return PatchInspection(Status.INVALID_PATCH, "size_limit")
        if forward is not None:
            return PatchInspection(Status.APPLICABLE, forward_output=output)
        return PatchInspection(Status.APPLIED, reverse_output=output)
