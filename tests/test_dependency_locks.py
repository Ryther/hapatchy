"""Security exceptions for HA test installation require fully resolved locks."""

import json
import re
import tomllib
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
LOCKS = (
    ".devcontainer/requirements-tools.txt",
    ".devcontainer/requirements-ha.txt",
    "tests/requirements-ha-min.txt",
    "tests/requirements-ha-min-runtime.txt",
)
PIN = re.compile(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.!+-]+")


def test_ci_locks_contain_only_exact_versions_and_known_includes():
    for name in LOCKS:
        lines = (ROOT / name).read_text().splitlines()
        for line in lines:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            assert PIN.fullmatch(value) or (
                name == "tests/requirements-ha-min-runtime.txt"
                and value == "-r requirements-ha-min.txt"
            ), f"{name}: unpinned requirement {value!r}"


def test_minimum_ha_baseline_uses_patched_https_client():
    minimum = json.loads((ROOT / "hacs.json").read_text())["homeassistant"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    pins = dict(
        line.split("==", 1)
        for line in (ROOT / "tests/requirements-ha-min.txt").read_text().splitlines()
        if "==" in line and not line.startswith("#")
    )
    direct_pins = dict(
        line.split("==", 1)
        for line in (ROOT / "tests/requirements-ha-min.in").read_text().splitlines()
        if "==" in line and not line.startswith("#")
    )

    assert Version(minimum) >= Version("2026.7.4")
    assert pins["homeassistant"] == minimum
    assert all(pins[name] == version for name, version in direct_pins.items())
    assert Version(pins["aiohttp"]) >= Version("3.14.3")
    assert project["requires-python"] == ">=3.14.2"
