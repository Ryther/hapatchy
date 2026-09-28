"""Prepare a reviewable, exact-lock Home Assistant baseline proposal."""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.version import Version

from script.ha_release_catalog import fetch_pypi_json, latest_pair
from script.resolve_ha_locks import render, render_input, validate_lock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(".devcontainer/requirements-tools.txt")
RUNTIME = Path(".devcontainer/requirements-ha.txt")
TEXT_PATHS = (
    Path(".github/workflows/tests.yaml"),
    Path(".github/dependabot.yml"),
    Path(".devcontainer/README.md"),
    Path("README.md"),
    Path("AGENTS.md"),
    Path("docs/releasing.md"),
)
EDITABLE_PATHS = (TOOLS, RUNTIME, *TEXT_PATHS)
HA_REFERENCES = {
    Path(".github/workflows/tests.yaml"): 2,
    Path(".github/dependabot.yml"): 3,
    Path(".devcontainer/README.md"): 1,
    Path("README.md"): 1,
    Path("AGENTS.md"): 1,
    Path("docs/releasing.md"): 1,
}
PLUGIN_REFERENCES = {
    Path(".github/dependabot.yml"): 2,
    Path(".devcontainer/README.md"): 1,
}


@dataclass(frozen=True)
class BaselineChange:
    old_ha: str
    new_ha: str
    old_plugin: str
    new_plugin: str
    originals: dict[Path, bytes]
    edits: dict[Path, bytes]


def _replace_counted(data: bytes, old: str, new: str, expected: int, path: Path) -> bytes:
    original = old.encode()
    if data.count(original) != expected:
        raise ValueError(f"Unexpected baseline references in {path}")
    return data.replace(original, new.encode())


def plan(
    repo_root: Path, ha: str, plugin: str, *, uv_binary: Path = Path("uv")
) -> BaselineChange:
    """Resolve both locks before calculating any allowlisted repository edit."""
    render_input("{ha_version}:{plugin_version}", ha, plugin)
    tools = validate_lock(repo_root / TOOLS)
    runtime = validate_lock(repo_root / RUNTIME)
    old_ha = tools["homeassistant"]
    old_plugin = tools["pytest-homeassistant-custom-component"]
    if runtime["homeassistant"] != old_ha:
        raise ValueError("Recent HA locks disagree")
    originals = {path: (repo_root / path).read_bytes() for path in EDITABLE_PATHS}
    if Version(ha) < Version(old_ha):
        raise ValueError("Candidate HA version is older than the recent baseline")
    if ha == old_ha:
        if plugin != old_plugin:
            raise ValueError("Plugin changed without a new HA baseline")
        return BaselineChange(old_ha, ha, old_plugin, plugin, originals, {})

    with tempfile.TemporaryDirectory(prefix="hapatchy-baseline-") as temporary:
        generated = render(ha, plugin, Path(temporary), uv_binary=uv_binary)
        edits = {TOOLS: generated[0].read_bytes(), RUNTIME: generated[1].read_bytes()}
    for path in TEXT_PATHS:
        content = originals[path]
        content = _replace_counted(content, old_ha, ha, HA_REFERENCES[path], path)
        if path in PLUGIN_REFERENCES:
            content = _replace_counted(
                content, old_plugin, plugin, PLUGIN_REFERENCES[path], path
            )
        edits[path] = content
    if set(edits) != set(EDITABLE_PATHS):
        raise ValueError("Unexpected baseline edit set")
    return BaselineChange(old_ha, ha, old_plugin, plugin, originals, edits)


def apply(repo_root: Path, change: BaselineChange) -> None:
    """Reject a stale plan and write only the calculated files."""
    if set(change.edits) - set(EDITABLE_PATHS):
        raise ValueError("Unexpected baseline edit path")
    for path, original in change.originals.items():
        if (repo_root / path).read_bytes() != original:
            raise ValueError(f"Baseline source changed during planning: {path}")
    for path, content in change.edits.items():
        destination = repo_root / path
        temporary = destination.with_name(f".{destination.name}.hapatchy-update")
        temporary.write_bytes(content)
        os.replace(temporary, destination)


def _body(change: BaselineChange) -> str:
    old_pins = validate_lock(ROOT / TOOLS)
    # The candidate lock bytes have already passed the resolver's exact-pin checks.
    with tempfile.TemporaryDirectory(prefix="hapatchy-pr-body-") as temporary:
        candidate = Path(temporary) / TOOLS.name
        candidate.write_bytes(change.edits[TOOLS])
        new_pins = validate_lock(candidate)
    changed = sum(old_pins.get(name) != version for name, version in new_pins.items())
    return (
        f"Validate Home Assistant {change.new_ha} with pytest plugin {change.new_plugin} "
        f"(from HA {change.old_ha} / plugin {change.old_plugin}).\n\n"
        f"The recent tool lock changes {changed} package pins; both recent locks are "
        "resolved as one candidate. The minimum HA lane remains unchanged.\n\n"
        "Required HA tests, boot smoke, Sonar and the full candidate-lock advisory "
        "gate decide whether this proposal can merge. An existing release PR or "
        "unrelated change requires manual review.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--uv", type=Path, default=Path("uv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    current = validate_lock(ROOT / TOOLS)["homeassistant"]
    pair = latest_pair(fetch_pypi_json, current, "3.14.7")
    if pair is None:
        with args.output.open("a") as output:
            output.write("changed=false\n")
        print("Recent HA baseline is current")
        return 0
    change = plan(ROOT, *pair, uv_binary=args.uv)
    body = _body(change)
    if not args.dry_run:
        apply(ROOT, change)
    args.body_file.write_text(body, encoding="utf-8")
    with args.output.open("a") as output:
        output.write(f"changed=true\nha={change.new_ha}\nplugin={change.new_plugin}\n")
    action = "Evaluated" if args.dry_run else "Prepared"
    print(f"{action} HA {change.new_ha} / plugin {change.new_plugin} baseline proposal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
