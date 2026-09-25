"""Build an exact managed patch from a bounded edit of one text file."""

from difflib import unified_diff

from .const import MAX_PATCH_BYTES
from .models import PatchError, Status, relative_parts
from .patch_engine import UnifiedDiffEngine

MAX_EDITOR_BYTES = 256 * 1024


def validate_editor_text(data: bytes) -> str:
    """Accept only text that the native editor and strict diff can round-trip."""
    if len(data) > MAX_EDITOR_BYTES:
        raise PatchError("size_limit")
    if not data:
        raise PatchError("editor_empty")
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PatchError("unsupported_encoding") from None
    if "\x00" in value:
        raise PatchError("unsupported_encoding")
    if "\r" in value or not value.endswith("\n"):
        raise PatchError("editor_text_format")
    return value


def build_patch(original: bytes, edited: bytes, target_path: str) -> bytes:
    """Generate and prove one exact, uniquely applicable unified diff."""
    relative_parts(target_path)
    before = validate_editor_text(original)
    after = validate_editor_text(edited)
    if before == after:
        raise PatchError("editor_unchanged")

    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    engine = UnifiedDiffEngine()
    context = 3
    maximum = max(len(before_lines), len(after_lines))
    while True:
        candidate = "".join(
            unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{target_path}",
                tofile=f"b/{target_path}",
                n=context,
            )
        ).encode("utf-8")
        if len(candidate) > MAX_PATCH_BYTES:
            raise PatchError("size_limit")
        try:
            result = engine.inspect(engine.parse(candidate, target_path), original)
        except PatchError:
            result = None
        if result is not None and result.status == Status.APPLICABLE:
            if result.forward_output == edited:
                return candidate
        if context >= maximum:
            raise PatchError("editor_context_not_unique")
        context = min(maximum, context * 2)
