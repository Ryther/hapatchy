"""Real temporary files exercise rejection, backup and commit boundaries."""

import importlib
import os
from pathlib import Path

import pytest


def modules():
    assert Path("custom_components/hapatchy/atomic_writer.py").exists(), "Guarded writer is missing"
    return (
        importlib.import_module("custom_components.hapatchy.atomic_writer"),
        importlib.import_module("custom_components.hapatchy.safe_io"),
        importlib.import_module("custom_components.hapatchy.backup"),
    )


@pytest.fixture
def root(tmp_path):
    (tmp_path / "python_scripts").mkdir()
    (tmp_path / "python_scripts/test.py").write_bytes(b"original\n")
    return tmp_path


def test_commit_preserves_mode_and_makes_durable_backup(root):
    writer, io, backup = modules()
    target = root / "python_scripts/test.py"
    target.chmod(0o640)
    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        snap = opened.read()
        manager = backup.BackupManager(root, "patch1", 10)
        writer.AtomicFileWriter().commit(
            opened,
            snap,
            b"changed\n",
            before_replace=lambda: manager.create(
                snap, "python_scripts/test.py", b"changed\n", "a" * 64, "apply"
            ),
        )
    assert target.read_bytes() == b"changed\n"
    assert target.stat().st_mode & 0o777 == 0o640
    assert [p.read_bytes() for p in (root / ".hapatchy/backups/patch1").glob("*/target")] == [
        b"original\n"
    ]
    assert not list(target.parent.glob(".hapatchy-*.tmp"))


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/outside",
        "python_scripts/../x",
        "python_scripts//x",
        "python_scripts\\x",
        ".storage/x",
        ".hapatchy/x",
        "custom_components/hapatchy/x",
    ],
)
def test_unsafe_paths_cannot_open(root, path):
    _, io, _ = modules()
    with pytest.raises(ValueError):
        with io.GuardedFile(root, path):
            pass


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_non_regular_or_aliased_target_is_rejected(root, kind):
    _, io, _ = modules()
    target = root / "python_scripts/test.py"
    if kind == "hardlink":
        os.link(target, root / "alias")
    else:
        target.unlink()
        if kind == "symlink":
            target.symlink_to(root / "outside")
        elif kind == "fifo":
            os.mkfifo(target)
        else:
            target.mkdir()
    with pytest.raises(ValueError):
        with io.GuardedFile(root, "python_scripts/test.py") as opened:
            opened.read()


def test_changed_preimage_aborts_and_cleans_temp(root):
    writer, io, _ = modules()
    target = root / "python_scripts/test.py"
    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        snap = opened.read()
        with pytest.raises(ValueError, match="target_changed"):
            writer.AtomicFileWriter().commit(
                opened, snap, b"changed\n", before_replace=lambda: target.write_bytes(b"upstream\n")
            )
    assert target.read_bytes() == b"upstream\n"
    assert not list(target.parent.glob(".hapatchy-*.tmp"))


def test_failed_backup_prevents_replacement(root):
    writer, io, _ = modules()

    def fail():
        raise OSError("disk full")

    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        with pytest.raises(ValueError, match="backup_failed"):
            writer.AtomicFileWriter().commit(
                opened, opened.read(), b"changed\n", before_replace=fail
            )
    assert (root / "python_scripts/test.py").read_bytes() == b"original\n"
    assert not list((root / "python_scripts").glob(".hapatchy-*.tmp"))


def test_post_replace_fsync_reports_actual_mutation(root, monkeypatch):
    writer, io, _ = modules()
    real_fsync = os.fsync
    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        snap = opened.read()

        def fail_directory(fd):
            if fd == opened.parent_fd:
                raise OSError("directory sync failed")
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", fail_directory)
        with pytest.raises(writer.CommitError) as error:
            writer.AtomicFileWriter().commit(opened, snap, b"changed\n")
        assert error.value.replaced
        assert error.value.reason == "durability_unconfirmed"
        assert (root / "python_scripts/test.py").read_bytes() == b"changed\n"
        monkeypatch.setattr(os, "fsync", real_fsync)
        writer.AtomicFileWriter().confirm_durability(opened, opened.read())


def test_parent_swap_detected_before_commit(root):
    writer, io, _ = modules()
    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        snap = opened.read()
        (root / "python_scripts").rename(root / "moved")
        (root / "python_scripts").mkdir()
        (root / "python_scripts/test.py").write_bytes(b"other\n")
        with pytest.raises(ValueError):
            writer.AtomicFileWriter().commit(opened, snap, b"changed\n")
    assert (root / "moved/test.py").read_bytes() == b"original\n"
    assert (root / "python_scripts/test.py").read_bytes() == b"other\n"


def test_backup_storage_symlink_rejected(root):
    _, io, backup = modules()
    (root / ".hapatchy").symlink_to(root / "python_scripts", target_is_directory=True)
    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        with pytest.raises(ValueError):
            backup.BackupManager(root, "patch1", 10).create(
                opened.read(), "python_scripts/test.py", b"after", "a" * 64, "apply"
            )
    assert not (root / "python_scripts/backups").exists()


def test_retention_is_per_patch_and_only_explicit_after_success(root):
    _, io, backup = modules()
    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        snap = opened.read()
        manager = backup.BackupManager(root, "patch1", 1)
        for n in range(3):
            manager.create(snap, "python_scripts/test.py", str(n).encode(), "a" * 64, "apply")
        backup.BackupManager(root, "other", 1).create(
            snap, "python_scripts/test.py", b"other", "a" * 64, "apply"
        )
    assert len(list((root / ".hapatchy/backups/patch1").iterdir())) == 3
    manager.prune()
    assert len(list((root / ".hapatchy/backups/patch1").iterdir())) == 1
    assert len(list((root / ".hapatchy/backups/other").iterdir())) == 1


@pytest.mark.parametrize("operation", ["fchmod", "replace"])
def test_precommit_syscall_failure_preserves_target(root, monkeypatch, operation):
    writer, io, _ = modules()

    def fail(*args, **kwargs):
        raise OSError("injected failure")

    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        snap = opened.read()
        monkeypatch.setattr(os, operation, fail)
        with pytest.raises(writer.CommitError) as caught:
            writer.AtomicFileWriter().commit(opened, snap, b"changed\n")
        assert not caught.value.replaced
    assert (root / "python_scripts/test.py").read_bytes() == b"original\n"
    assert not list((root / "python_scripts").glob(".hapatchy-*.tmp"))


def test_incomplete_backup_does_not_evict_valid_backup(root):
    _, io, backup = modules()
    manager = backup.BackupManager(root, "patch1", 1)
    with io.GuardedFile(root, "python_scripts/test.py") as opened:
        name = manager.create(opened.read(), "python_scripts/test.py", b"new", "a" * 64, "apply")
    incomplete = root / ".hapatchy/backups/patch1" / ("99991231T235959.999999Z-" + "f" * 32)
    incomplete.mkdir()
    manager.prune()
    assert (root / ".hapatchy/backups/patch1" / name / "target").read_bytes() == b"original\n"
