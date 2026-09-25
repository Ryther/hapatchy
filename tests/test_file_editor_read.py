"""Editor reads obey both directory grants and descriptor safety."""

import os

import pytest

from custom_components.hapatchy.models import PatchDefinition, PatchError
from custom_components.hapatchy.validation import read_editable_target
from tests.policy_helpers import grant_directories


def definition(path: str = "scripts/example.txt") -> PatchDefinition:
    return PatchDefinition.from_mapping(
        "pending",
        {
            "name": "Example",
            "target_path": path,
            "watch_root": "scripts",
            "source_type": "managed",
            "source": "0" * 64,
        },
    )


def test_reads_authorized_target(tmp_path) -> None:
    (tmp_path / "scripts").mkdir()
    target = tmp_path / "scripts/example.txt"
    target.write_bytes(b"before\n")
    policy = grant_directories(tmp_path)
    snapshot = read_editable_target(tmp_path, definition(), policy)
    assert snapshot.data == b"before\n"
    assert target.read_bytes() == b"before\n"


@pytest.mark.parametrize("content", [b"", b"no newline", b"crlf\r\n", b"nul\x00\n", b"\xff\n", b"a" * (256 * 1024) + b"\n"])
def test_refuses_unsupported_text(tmp_path, content: bytes) -> None:
    (tmp_path / "scripts").mkdir()
    target = tmp_path / "scripts/example.txt"
    target.write_bytes(content)
    policy = grant_directories(tmp_path)
    with pytest.raises(PatchError) as error:
        read_editable_target(tmp_path, definition(), policy)
    if content:
        assert content not in str(error.value).encode()
    assert target.read_bytes() == content


def test_refuses_unauthorized_target(tmp_path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/example.txt").write_bytes(b"secret\n")
    policy = grant_directories(tmp_path, ("other",))
    with pytest.raises(PatchError, match="hapatchy_path_not_allowed"):
        read_editable_target(tmp_path, definition(), policy)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo"])
def test_refuses_alias_or_special_file(tmp_path, kind: str) -> None:
    (tmp_path / "scripts").mkdir()
    target = tmp_path / "scripts/example.txt"
    source = tmp_path / "scripts/source.txt"
    source.write_bytes(b"secret\n")
    if kind == "symlink":
        target.symlink_to(source)
    elif kind == "hardlink":
        os.link(source, target)
    elif kind == "directory":
        target.mkdir()
    else:
        os.mkfifo(target)
    policy = grant_directories(tmp_path)
    with pytest.raises(PatchError):
        read_editable_target(tmp_path, definition(), policy)
    assert source.read_bytes() == b"secret\n"
