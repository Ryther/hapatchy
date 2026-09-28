"""The proposer edits only recent-baseline inputs and references."""

import sys
from pathlib import Path

import pytest

from script import update_ha_baseline as updater


def _workspace(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1]
    for name in updater.EDITABLE_PATHS:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())
    minimum = tmp_path / "tests/requirements-ha-min.txt"
    minimum.parent.mkdir(exist_ok=True)
    minimum.write_bytes((source / "tests/requirements-ha-min.txt").read_bytes())
    return tmp_path


def _versions(root: Path) -> tuple[str, str]:
    pins = updater.validate_lock(root / updater.TOOLS)
    return pins["homeassistant"], pins["pytest-homeassistant-custom-component"]


def _next(version: str) -> str:
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def test_noop_at_current_baseline(tmp_path):
    root = _workspace(tmp_path)
    assert updater.plan(root, *_versions(root)).edits == {}


def test_candidate_changes_only_allowlisted_paths_and_preserves_minimum(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    minimum = (root / "tests/requirements-ha-min.txt").read_bytes()
    ha, plugin = (_next(version) for version in _versions(root))

    def fake_render(ha, plugin, output_dir):
        tools = output_dir / "requirements-tools.txt"
        runtime = output_dir / "requirements-ha.txt"
        tools.write_text(f"homeassistant=={ha}\npytest-homeassistant-custom-component=={plugin}\n")
        runtime.write_text(f"homeassistant=={ha}\n")
        return tools, runtime

    monkeypatch.setattr(updater, "render", fake_render)
    candidate = updater.plan(root, ha, plugin)
    assert set(candidate.edits) == set(updater.EDITABLE_PATHS)
    assert Path(".github/workflows/tests.yaml") not in candidate.edits
    updater.apply(root, candidate)
    assert (root / "tests/requirements-ha-min.txt").read_bytes() == minimum


def test_failed_second_lock_resolution_never_writes_repository(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    before = {name: (root / name).read_bytes() for name in updater.EDITABLE_PATHS}
    ha, plugin = (_next(version) for version in _versions(root))

    def failed(ha, plugin, output_dir):
        (output_dir / "requirements-tools.txt").write_text("partial")
        raise RuntimeError("second lock failed")

    monkeypatch.setattr(updater, "render", failed)
    with pytest.raises(RuntimeError, match="second lock"):
        updater.plan(root, ha, plugin)
    assert all((root / name).read_bytes() == bytes_ for name, bytes_ in before.items())


def test_older_candidate_requires_review(tmp_path):
    root = _workspace(tmp_path)
    _, plugin = _versions(root)
    with pytest.raises(ValueError, match="older"):
        updater.plan(root, "0.0.0", plugin)


def test_cli_dry_run_reports_candidate_without_writing_and_then_applies(tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    before = {name: (root / name).read_bytes() for name in updater.EDITABLE_PATHS}
    ha, plugin = (_next(version) for version in _versions(root))

    def fake_render(ha, plugin, output_dir):
        paths = (output_dir / "requirements-tools.txt", output_dir / "requirements-ha.txt")
        paths[0].write_text(f"homeassistant=={ha}\npytest-homeassistant-custom-component=={plugin}\n")
        paths[1].write_text(f"homeassistant=={ha}\n")
        return paths

    monkeypatch.setattr(updater, "ROOT", root)
    monkeypatch.setattr(updater, "render", fake_render)
    monkeypatch.setattr(updater, "latest_pair", lambda fetch, current, python: (ha, plugin))
    output = tmp_path / "output.txt"
    body = root / "_tmp/ha-baseline-pr.md"
    argv = ["update_ha_baseline.py", "--output", str(output)]
    monkeypatch.setattr(sys, "argv", [*argv, "--dry-run"])
    assert updater.main() == 0
    assert all((root / path).read_bytes() == data for path, data in before.items())
    assert "changed=true" in output.read_text()
    assert ha in body.read_text()
    monkeypatch.setattr(sys, "argv", argv)
    assert updater.main() == 0
    assert f"homeassistant=={ha}".encode() in (root / updater.TOOLS).read_bytes()
