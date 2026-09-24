"""One executor transaction owns inspection, backup, write and error precedence."""

import importlib
import os
from pathlib import Path

import pytest

from custom_components.hapatchy.models import PatchDefinition
from tests.policy_helpers import grant_directories

DIFF = b"--- a/scripts/a.py\n+++ b/scripts/a.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"


def api():
    assert Path("custom_components/hapatchy/reconciler.py").exists(), "Reconciler is missing"
    return importlib.import_module("custom_components.hapatchy.reconciler").Reconciler


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\n")
    return tmp_path


def definition(**changes):
    return PatchDefinition.from_mapping(
        "patch1",
        dict(
            name="Patch",
            target_path="scripts/a.py",
            watch_root="scripts",
            source_type="local",
            source="patches/a.patch",
        )
        | changes,
    )


@pytest.mark.parametrize(
    ("action", "auto", "expected", "mutated"),
    [
        ("reconcile", True, "applied", True),
        ("reconcile", False, "applicable", False),
        ("refresh_source", True, "applicable", False),
        ("apply", False, "applied", True),
    ],
)
def test_action_policy(tree, action, auto, expected, mutated):
    result = api()(tree, grant_directories(tree)).run(
        definition(auto_apply=auto), DIFF, action, 10, False
    )
    assert result.inspection.status == expected
    assert result.mutated == mutated
    assert (tree / "scripts/a.py").read_bytes() == (
        b"context\nnew\n" if mutated else b"context\nold\n"
    )
    assert bool(list((tree / ".hapatchy").glob("backups/*/*/target"))) == mutated


def test_reconcile_is_idempotent_and_revert_always_backs_up(tree):
    reconciler = api()(tree, grant_directories(tree))
    reconciler.run(definition(backup_before_apply=False), DIFF, "apply", 10, False)
    again = reconciler.run(definition(), DIFF, "reconcile", 10, False)
    assert again.inspection.status == "applied" and not again.mutated
    result = reconciler.run(definition(backup_before_apply=False), DIFF, "revert", 10, False)
    assert result.inspection.status == "applicable" and result.mutated
    assert (tree / "scripts/a.py").read_bytes() == b"context\nold\n"
    assert [p.read_bytes() for p in (tree / ".hapatchy").glob("backups/*/*/target")] == [
        b"context\nnew\n"
    ]


def test_revert_not_applied_is_no_write_service_failure(tree):
    result = api()(tree, grant_directories(tree)).run(definition(), DIFF, "revert", 10, False)
    assert result.service_error == "not_applied"
    assert result.inspection.status == "applicable"
    assert not result.mutated
    assert not (tree / ".hapatchy/backups").exists()


def test_durability_failure_remains_error_until_sync_succeeds(tree, monkeypatch):
    reconciler = api()(tree, grant_directories(tree))
    real = os.fsync

    def fail_dir(fd):
        import stat

        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("fsync failed")
        real(fd)

    monkeypatch.setattr(os, "fsync", fail_dir)
    first = reconciler.run(definition(backup_before_apply=False), DIFF, "apply", 10, False)
    assert first.inspection.status == "apply_error"
    assert first.inspection.reason == "durability_unconfirmed"
    assert first.mutated
    assert (tree / "scripts/a.py").read_bytes() == b"context\nnew\n"
    again = reconciler.run(definition(), DIFF, "reconcile", 10, True)
    assert again.inspection.status == "apply_error"
    monkeypatch.setattr(os, "fsync", real)
    resolved = reconciler.run(definition(), DIFF, "reconcile", 10, True)
    assert resolved.inspection.status == "applied" and not resolved.mutated


def test_conflict_never_creates_backup_or_changes_target(tree):
    (tree / "scripts/a.py").write_bytes(b"context\nupstream changed\n")
    result = api()(tree, grant_directories(tree)).run(definition(), DIFF, "apply", 10, False)
    assert result.inspection.status == "conflict"
    assert result.service_error == "context_not_unique"
    assert not (tree / ".hapatchy/backups").exists()
    assert (tree / "scripts/a.py").read_bytes() == b"context\nupstream changed\n"


def test_missing_target_is_visible(tree):
    (tree / "scripts/a.py").unlink()
    result = api()(tree, grant_directories(tree)).run(definition(), DIFF, "reconcile", 10, False)
    assert result.inspection.status == "missing_target"
    assert not result.mutated


def test_pending_durability_is_not_cleared_by_missing_target(tree):
    (tree / "scripts/a.py").unlink()
    result = api()(tree, grant_directories(tree)).run(definition(), DIFF, "reconcile", 10, True)
    assert result.inspection.status == "apply_error"
    assert result.inspection.reason == "durability_unconfirmed"
