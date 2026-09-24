"""The target selector lists actual regular files within permitted subdirectories."""

import os

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
