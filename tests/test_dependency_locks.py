"""Security exceptions for HA test installation require fully resolved locks."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = (
    ".devcontainer/requirements-tools.txt",
    ".devcontainer/requirements-ha.txt",
    "tests/requirements-ha-min.txt",
    "tests/requirements-ha-min-runtime.txt",
    "tests/requirements-commitizen.txt",
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
