"""Resolve the two recent Home Assistant locks from explicit direct inputs."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from script.ha_distribution import load_ha_constraints

INPUT_DIR = Path(__file__).resolve().parents[1] / ".devcontainer"
ROOT = INPUT_DIR.parent
LOCK_NAMES = ("requirements-tools", "requirements-ha")
HA_OWNED_ROOTS = frozenset(
    {
        "uv",
        "aiohasupervisor",
        "av",
        "gazetteer-matcher",
        "ha-ffmpeg",
        "hassil",
        "home-assistant-frontend",
        "infrared-protocols",
        "mutagen",
        "pymicro-vad",
        "pyspeex-noise",
        "pyturbojpeg",
        "rf-protocols",
    }
)
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){2}")
PIN = re.compile(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+\-]+)")


def render_input(template: str, ha_version: str, plugin_version: str) -> str:
    """Fill only stable package-version placeholders in a direct-input file."""
    if not VERSION.fullmatch(ha_version):
        raise ValueError("Invalid Home Assistant version")
    if not VERSION.fullmatch(plugin_version):
        raise ValueError("Invalid pytest plugin version")
    return template.format(ha_version=ha_version, plugin_version=plugin_version)


def validate_lock(path: Path) -> dict[str, str]:
    """Reject incomplete or ambiguous outputs before publishing either lock."""
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PIN.fullmatch(stripped)
        if match is None:
            raise ValueError(f"Unpinned requirement in {path.name}")
        name = canonicalize_name(match.group(1))
        if name in pins:
            raise ValueError(f"Duplicate requirement in {path.name}: {name}")
        pins[name] = match.group(2)
    if "homeassistant" not in pins:
        raise ValueError(f"Missing Home Assistant in {path.name}")
    return pins


def _ha_owned_roots(inputs: dict[str, str]) -> frozenset[str]:
    roots: set[str] = set()
    for content in inputs.values():
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            name = canonicalize_name(requirement.name)
            if not requirement.specifier:
                if name not in HA_OWNED_ROOTS or requirement.marker or requirement.extras:
                    raise ValueError(f"Unpinned non-HA requirement: {name}")
                roots.add(name)
            elif name in HA_OWNED_ROOTS:
                raise ValueError(f"HA-owned requirement is pinned in an input: {name}")
    return frozenset(roots)


def render(
    ha_version: str,
    plugin_version: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Resolve both locks in staging; publish only after both validate."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hapatchy-locks-", dir=output_dir) as temporary:
        staging = Path(temporary)
        inputs = {
            name: render_input(
                (INPUT_DIR / f"{name}.in").read_text(encoding="utf-8"),
                ha_version,
                plugin_version,
            )
            for name in LOCK_NAMES
        }
        roots = _ha_owned_roots(inputs)
        constraints = staging / "ha-constraints.txt"
        if roots:
            constraints.write_bytes(load_ha_constraints(ha_version, roots))
        for name in LOCK_NAMES:
            input_path = staging / f"{name}.in"
            output_path = staging / f"{name}.txt"
            input_path.write_text(inputs[name])
            previous = output_dir / f"{name}.txt"
            if not previous.exists():
                previous = INPUT_DIR / f"{name}.txt"
            shutil.copyfile(previous, output_path)
            command = [
                sys.executable,
                "-m",
                "uv",
                "pip",
                "compile",
                str(input_path),
                "--output-file",
                str(output_path),
                "--no-header",
                "--no-annotate",
                "--python-version",
                "3.14.7",
                "--quiet",
            ]
            if roots:
                command.extend(("--constraint", str(constraints)))
            subprocess.run(
                command,
                check=True,
                env={**os.environ, "UV_CACHE_DIR": str(staging / "uv-cache")},
            )
            pins = validate_lock(output_path)
            if pins["homeassistant"] != ha_version:
                raise ValueError(f"Resolver returned the wrong HA version in {name}")
            if name == "requirements-tools" and pins.get("pytest-homeassistant-custom-component") != plugin_version:
                raise ValueError("Resolver returned the wrong pytest plugin version")
        paths = (output_dir / "requirements-tools.txt", output_dir / "requirements-ha.txt")
        for name, destination in zip(LOCK_NAMES, paths, strict=True):
            os.replace(staging / f"{name}.txt", destination)
        return paths


def check_current() -> bool:
    """Compare fresh current-baseline resolution with tracked lock bytes."""
    tools = validate_lock(INPUT_DIR / "requirements-tools.txt")
    with tempfile.TemporaryDirectory(prefix="hapatchy-lock-check-") as temporary:
        paths = render(
            tools["homeassistant"],
            tools["pytest-homeassistant-custom-component"],
            Path(temporary),
        )
        return all(
            path.read_bytes() == (INPUT_DIR / path.name).read_bytes()
            for path in paths
        )


def main() -> int:
    """Generate a candidate pair or verify the committed current pair."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--ha")
    parser.add_argument("--plugin")
    args = parser.parse_args()
    if args.check:
        if args.ha or args.plugin:
            parser.error("--check cannot be combined with generation options")
        return 0 if check_current() else 1
    if not (args.ha and args.plugin):
        parser.error("generation needs --ha and --plugin")
    render(args.ha, args.plugin, ROOT / "_tmp" / "resolved-ha-locks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
