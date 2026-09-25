"""The generated patch must be an exact, unambiguous round trip."""

import pytest

from custom_components.hapatchy.models import PatchError, Status
from custom_components.hapatchy.patch_builder import build_patch
from custom_components.hapatchy.patch_engine import UnifiedDiffEngine


@pytest.mark.parametrize(
    ("original", "edited"),
    [
        (b"first\nold\nlast\n", b"first\nnew\nlast\n"),
        (b"a\nb\nc\nd\ne\nf\ng\nh\n", b"a\nB\nc\nd\ne\nf\nG\nh\n"),
        (b"same\nsame\nold\nsame\nsame\n", b"same\nsame\nnew\nsame\nsame\n"),
        (b"caf\xc3\xa9\nold\n", b"caf\xc3\xa9\nnew\n"),
    ],
)
def test_round_trip(original: bytes, edited: bytes) -> None:
    raw = build_patch(original, edited, "scripts/example.txt")
    engine = UnifiedDiffEngine()
    parsed = engine.parse(raw, "scripts/example.txt")
    result = engine.inspect(parsed, original)
    assert result.status == Status.APPLICABLE
    assert result.forward_output == edited
    reverse = engine.inspect(parsed, edited)
    assert reverse.status == Status.APPLIED
    assert reverse.reverse_output == original


@pytest.mark.parametrize(
    ("original", "edited"),
    [
        (b"old\n", b"old\n"),
        (b"old\n", b""),
        (b"", b"new\n"),
        (b"old\n", b"new"),
        (b"old\r\n", b"new\n"),
        (b"old\n", b"new\x00\n"),
        (b"old\n", b"\xff\n"),
    ],
)
def test_refuses_unsupported_or_unchanged_text(original: bytes, edited: bytes) -> None:
    with pytest.raises(PatchError):
        build_patch(original, edited, "scripts/example.txt")


def test_refuses_unsafe_target() -> None:
    with pytest.raises(PatchError):
        build_patch(b"old\n", b"new\n", "../outside")


def test_refuses_oversize_editor_input() -> None:
    with pytest.raises(PatchError, match="size_limit"):
        build_patch(b"a" * (256 * 1024) + b"\n", b"new\n", "scripts/example.txt")


def test_refuses_diff_that_becomes_ambiguous_after_apply() -> None:
    with pytest.raises(PatchError, match="editor_context_not_unique"):
        build_patch(b"before\n", b"before\nafter\n", "scripts/example.txt")
