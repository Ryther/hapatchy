"""The recent HA lock pair is generated and published as one unit."""

import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from script import resolve_ha_locks


def test_render_input_rejects_invalid_version_text():
    template = "homeassistant=={ha_version}\npytest-homeassistant-custom-component=={plugin_version}\n"
    with pytest.raises(ValueError, match="Invalid Home Assistant version"):
        resolve_ha_locks.render_input(template, "2026.9.4; echo unsafe", "0.13.367")


def test_render_input_pairs_exact_versions():
    template = "homeassistant=={ha_version}\npytest-homeassistant-custom-component=={plugin_version}\n"
    assert resolve_ha_locks.render_input(template, "2026.9.4", "0.13.367") == (
        "homeassistant==2026.9.4\npytest-homeassistant-custom-component==0.13.367\n"
    )


def test_validate_lock_rejects_duplicate_and_unpinned_packages(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("homeassistant==2026.9.4\nhomeassistant==2026.9.4\n")
    with pytest.raises(ValueError, match="Duplicate"):
        resolve_ha_locks.validate_lock(lock)
    lock.write_text("homeassistant>=2026.9.4\n")
    with pytest.raises(ValueError, match="Unpinned"):
        resolve_ha_locks.validate_lock(lock)


def test_render_keeps_existing_pair_when_second_resolution_fails(tmp_path, monkeypatch):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for name in ("requirements-tools", "requirements-ha"):
        (source / f"{name}.in").write_text("homeassistant=={ha_version}\n")
        (source / f"{name}.txt").write_text("homeassistant==2026.9.0\n")
        (target / f"{name}.txt").write_text("previous result\n")
    monkeypatch.setattr(resolve_ha_locks, "INPUT_DIR", source)

    def compile_once(command, **kwargs):
        output = Path(command[command.index("--output-file") + 1])
        if "requirements-ha" in output.name:
            raise RuntimeError("resolver failed")
        output.write_text(
            "homeassistant==2026.9.4\n"
            "pytest-homeassistant-custom-component==0.13.367\n"
        )
        return CompletedProcess(command, 0)

    monkeypatch.setattr(resolve_ha_locks.subprocess, "run", compile_once)
    with pytest.raises(RuntimeError, match="resolver failed"):
        resolve_ha_locks.render("2026.9.4", "0.13.367", target)
    for name in ("requirements-tools", "requirements-ha"):
        assert (target / f"{name}.txt").read_text() == "previous result\n"


def test_successful_resolution_publishes_both_complete_locks(tmp_path, monkeypatch):
    source = tmp_path / "inputs"
    output = tmp_path / "output"
    source.mkdir()
    for name in ("requirements-tools", "requirements-ha"):
        (source / f"{name}.in").write_text("homeassistant=={ha_version}\n")
        (source / f"{name}.txt").write_text("homeassistant==2026.9.0\n")
    monkeypatch.setattr(resolve_ha_locks, "INPUT_DIR", source)

    def compile_once(command, **kwargs):
        path = Path(command[command.index("--output-file") + 1])
        pins = "homeassistant==2026.9.4\n"
        if path.name == "requirements-tools.txt":
            pins += "pytest-homeassistant-custom-component==0.13.367\n"
        path.write_text(pins)
        return CompletedProcess(command, 0)

    monkeypatch.setattr(resolve_ha_locks.subprocess, "run", compile_once)
    tools, runtime = resolve_ha_locks.render("2026.9.4", "0.13.367", output)
    assert tools.read_text().startswith("homeassistant==2026.9.4\n")
    assert runtime.read_text() == "homeassistant==2026.9.4\n"
    assert not list(output.glob(".hapatchy-locks-*"))


def test_check_current_detects_drift_and_cli_returns_failure(tmp_path, monkeypatch):
    source = tmp_path / "inputs"
    source.mkdir()
    (source / "requirements-tools.txt").write_text(
        "homeassistant==2026.9.0\npytest-homeassistant-custom-component==0.13.363\n"
    )
    (source / "requirements-ha.txt").write_text("homeassistant==2026.9.0\n")
    monkeypatch.setattr(resolve_ha_locks, "INPUT_DIR", source)

    def changed(ha, plugin, output):
        paths = (output / "requirements-tools.txt", output / "requirements-ha.txt")
        paths[0].write_text("homeassistant==2026.9.1\n")
        paths[1].write_text("homeassistant==2026.9.1\n")
        return paths

    monkeypatch.setattr(resolve_ha_locks, "render", changed)
    monkeypatch.setattr(sys, "argv", ["resolve_ha_locks.py", "--check"])
    assert resolve_ha_locks.main() == 1
