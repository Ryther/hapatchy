"""Security exceptions for HA test installation require fully resolved locks."""

import json
import tomllib
from pathlib import Path

from packaging.version import Version

from script.resolve_ha_locks import validate_lock

ROOT = Path(__file__).resolve().parents[1]
LOCKS = (
    ".devcontainer/requirements-tools.txt",
    ".devcontainer/requirements-ha.txt",
    "tests/requirements-ha-min.txt",
    "tests/requirements-ha-min-runtime.txt",
)


def _lock_pins(name, tmp_path):
    path = ROOT / name
    if name != "tests/requirements-ha-min-runtime.txt":
        return validate_lock(path)
    lines = path.read_text().splitlines()
    include = "-r requirements-ha-min.txt"
    assert lines.count(include) == 1
    merged = tmp_path / "minimum-runtime.txt"
    merged.write_text(
        (ROOT / "tests/requirements-ha-min.txt").read_text()
        + "\n"
        + "\n".join(line for line in lines if line != include)
    )
    return validate_lock(merged)


def test_ci_locks_contain_only_exact_versions_and_known_includes(tmp_path):
    for name in LOCKS:
        _lock_pins(name, tmp_path)


def test_minimum_ha_baseline_uses_patched_https_client():
    minimum = json.loads((ROOT / "hacs.json").read_text())["homeassistant"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    pins = validate_lock(ROOT / "tests/requirements-ha-min.txt")
    direct_pins = validate_lock(ROOT / "tests/requirements-ha-min.in")

    assert Version(minimum) >= Version("2026.7.4")
    assert pins["homeassistant"] == minimum
    assert all(pins[name] == version for name, version in direct_pins.items())
    assert Version(pins["aiohttp"]) >= Version("3.14.3")
    assert project["requires-python"] == ">=3.14.2"


def test_ha_environment_locks_use_updated_certificate_and_tls_helpers(tmp_path):
    for name in LOCKS:
        pins = _lock_pins(name, tmp_path)
        assert Version(pins["certifi"]) >= Version("2026.10.19"), name
        assert Version(pins["anyio"]) >= Version("4.14.2"), name
