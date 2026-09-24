"""The target selector lists actual regular files within permitted subdirectories."""

import os

import pytest

from custom_components.hapatchy.models import PatchError
from custom_components.hapatchy.path_policy import PathPolicy
from tests.policy_helpers import grant_directories


def candidates(root):
    from custom_components.hapatchy.target_picker import list_targets

    return list_targets(root, grant_directories(root, ("scripts", "custom_components")))


def test_lists_targets_but_not_protected_or_linked_paths(tmp_path):
    for name in [
        "scripts/a.py",
        "custom_components/example/test.py",
        "custom_components/hapatchy/secret.py",
        ".storage/auth",
        ".hapatchy/a.patch",
        "configuration.yaml",
        ".git/config",
        "scripts/.env",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test")
    (tmp_path / "scripts/link.py").symlink_to(tmp_path / "scripts/a.py")
    (tmp_path / "linked").symlink_to(tmp_path / "scripts")
    os.link(tmp_path / "scripts/a.py", tmp_path / "scripts/hard.py")
    assert candidates(tmp_path) == ["custom_components/example/test.py"]


def test_picker_lists_text_and_sorts_stably(tmp_path):
    (tmp_path / "scripts").mkdir()
    for name in ["z.py", "a.txt"]:
        (tmp_path / "scripts" / name).write_text("example")
    assert candidates(tmp_path) == ["scripts/a.txt", "scripts/z.py"]


def test_picker_does_not_rescan_yaml_for_each_suggestion(tmp_path, monkeypatch):
    from custom_components.hapatchy import yaml_policy

    folder = tmp_path / "scripts"
    folder.mkdir()
    for index in range(30):
        (folder / f"file_{index:02}.txt").write_text("example")
    policy = grant_directories(tmp_path)
    original_scan = yaml_policy.scan_source_graph
    scans = 0

    def counted_scan(root):
        nonlocal scans
        scans += 1
        return original_scan(root)

    monkeypatch.setattr(yaml_policy, "scan_source_graph", counted_scan)
    from custom_components.hapatchy.target_picker import list_targets

    assert len(list_targets(tmp_path, policy)) == 30
    assert scans <= 3


def test_picker_rejects_yaml_change_during_listing(tmp_path):
    folder = tmp_path / "scripts"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    (folder / "b.txt").write_text("b")
    policy = grant_directories(tmp_path)
    changed = False

    def allowed(_path):
        nonlocal changed
        if not changed:
            (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")
            changed = True
        return True

    policy = PathPolicy(tmp_path, allowed, policy.grants)
    from custom_components.hapatchy.target_picker import list_targets

    with pytest.raises(PatchError, match="configuration_source_changed"):
        list_targets(tmp_path, policy)
