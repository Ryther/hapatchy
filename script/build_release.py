"""Validate version identity and build a deterministic archive from tracked files."""

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


def release_version(root: Path, expected_tag: str | None = None) -> str:
    """All three version authorities must agree before any artifact is created."""
    manifest = json.loads((root / "custom_components/hapatchy/manifest.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())
    tracker = json.loads((root / ".release-please-manifest.json").read_text())
    version = manifest["version"]
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("Release versions must use stable MAJOR.MINOR.PATCH syntax")
    if project["project"]["version"] != version or tracker.get(".") != version:
        raise ValueError("Manifest, project and release tracker versions disagree")
    if expected_tag is not None and expected_tag != f"v{version}":
        raise ValueError("Release tag does not match the source version")
    return version


def build_archive(root: Path, expected_tag: str | None = None) -> tuple[Path, Path]:
    version = release_version(root, expected_tag)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    paths = sorted(
        {p for p in tracked if p.startswith("custom_components/hapatchy/") or p == "LICENSE"}
    )
    required = {
        "LICENSE",
        "custom_components/hapatchy/manifest.json",
        "custom_components/hapatchy/__init__.py",
    }
    if not required.issubset(paths):
        raise ValueError("Required integration files and license must be tracked")
    for name in paths:
        path = root / name
        if path.is_symlink() or not path.is_file() or path.resolve() != root.resolve() / name:
            raise ValueError(f"Not an authored regular file: {name}")
        if path.suffix not in {".py", ".json", ".yaml", ".png"} and name != "LICENSE":
            raise ValueError(f"Unexpected archive input: {name}")
    output = root / "dist" / f"hapatchy-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in paths:
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (root / name).read_bytes())
    checksum = output.with_suffix(".zip.sha256")
    checksum.write_text(f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output.name}\n")
    return output, checksum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Require the source version to match this vX.Y.Z tag")
    args = parser.parse_args()
    try:
        archive, checksum = build_archive(Path(__file__).resolve().parents[1], args.tag)
    except (ValueError, KeyError) as error:
        raise SystemExit(str(error)) from None
    print(checksum.read_text().strip())
    print(f"Created {archive.relative_to(archive.parents[1])} and {checksum.name}")


if __name__ == "__main__":
    main()
