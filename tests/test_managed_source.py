"""Owned patch files must never become arbitrary paths or partial revisions."""

import hashlib
import os

import pytest

from custom_components.hapatchy.models import PatchDefinition, PatchError

DIFF = b"--- a/demo/file.txt\n+++ b/demo/file.txt\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"


def store(root):
    from custom_components.hapatchy.managed_source import ManagedPatchStore

    return ManagedPatchStore(root)


def test_revision_roundtrip_is_private_and_idempotent(tmp_path):
    owned = store(tmp_path)
    revision = owned.save(DIFF)
    assert revision == hashlib.sha256(DIFF).hexdigest()
    assert owned.load(revision) == DIFF
    assert owned.save(DIFF) == revision
    path = tmp_path / ".hapatchy/patches" / f"{revision}.patch"
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(list(path.parent.iterdir())) == 1
    second = owned.save(DIFF.replace(b"+new", b"+newer"))
    assert second != revision and owned.load(revision) == DIFF


@pytest.mark.parametrize("revision", ["../secrets", "A" * 64, ".storage/auth", "a" * 63])
def test_revision_is_an_identifier_not_a_path(tmp_path, revision):
    with pytest.raises(PatchError):
        store(tmp_path).load(revision)


def test_rejects_tampered_revision_without_overwriting(tmp_path):
    owned = store(tmp_path)
    revision = owned.save(DIFF)
    path = tmp_path / ".hapatchy/patches" / f"{revision}.patch"
    path.write_bytes(b"changed")
    with pytest.raises(PatchError):
        owned.load(revision)
    with pytest.raises(PatchError):
        owned.save(DIFF)
    assert path.read_bytes() == b"changed"


@pytest.mark.parametrize("where", ["directory", "file", "hardlink"])
def test_managed_storage_rejects_links(tmp_path, where):
    owned = store(tmp_path)
    revision = hashlib.sha256(DIFF).hexdigest()
    if where == "directory":
        outside = tmp_path / "outside"
        outside.mkdir()
        (tmp_path / ".hapatchy").symlink_to(outside)
    else:
        parent = tmp_path / ".hapatchy/patches"
        parent.mkdir(parents=True)
        outside = tmp_path / "outside.patch"
        outside.write_bytes(DIFF)
        path = parent / f"{revision}.patch"
        if where == "file":
            path.symlink_to(outside)
        else:
            os.link(outside, path)
    with pytest.raises(PatchError):
        owned.save(DIFF)
    with pytest.raises(PatchError):
        owned.load(revision)


@pytest.mark.parametrize(
    "data", [b"", b"\xff", b"x" * (2 * 1024 * 1024 + 1)], ids=["empty", "encoding", "oversize"]
)
def test_bad_managed_content_never_persisted(tmp_path, data):
    with pytest.raises(PatchError):
        store(tmp_path).save(data)
    assert not list(tmp_path.rglob("*.patch"))


def test_failed_write_does_not_publish_revision(tmp_path, monkeypatch):
    owned = store(tmp_path)

    def fail(fd):
        raise OSError("disk failed")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(PatchError):
        owned.save(DIFF)
    assert not list(tmp_path.rglob("*.patch"))


async def test_managed_source_loads_without_network(hass, tmp_path):
    from custom_components.hapatchy.patch_source import PatchSourceClient

    revision = store(tmp_path).save(DIFF)
    definition = PatchDefinition.from_mapping(
        "example",
        {
            "name": "Example",
            "target_path": "demo/file.txt",
            "watch_root": "demo",
            "source_type": "managed",
            "source": revision,
        },
    )
    client = PatchSourceClient(tmp_path, hass.async_add_executor_job)
    assert await client.load(definition) == DIFF


def test_managed_type_cannot_bypass_protected_target_paths():
    with pytest.raises(PatchError):
        PatchDefinition.from_mapping(
            "example",
            {
                "name": "Example",
                "target_path": ".hapatchy/patches/a.patch",
                "watch_root": ".hapatchy/patches",
                "source_type": "managed",
                "source": "a" * 64,
            },
        )
