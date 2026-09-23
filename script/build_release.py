"""Build a deterministic integration archive from Git-visible authored files."""

import hashlib
import json
import subprocess
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "custom_components/hapatchy/manifest.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())
    version = manifest["version"]
    if version != project["project"]["version"]:
        raise SystemExit("Manifest and project versions differ")
    visible = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
        )
        .decode()
        .split("\0")
    )
    paths = sorted(
        {p for p in visible if p.startswith("custom_components/hapatchy/") or p == "LICENSE"}
    )
    for name in paths:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"Not an authored regular file: {name}")
        if path.suffix not in {".py", ".json", ".yaml", ".png"} and name != "LICENSE":
            raise SystemExit(f"Unexpected archive input: {name}")
    output = root / "dist" / f"hapatchy-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in paths:
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (root / name).read_bytes())
    print(f"{output.name}  SHA256 {hashlib.sha256(output.read_bytes()).hexdigest()}")
    print(f"{len(paths)} files; archive uses repository-relative installation paths")


if __name__ == "__main__":
    main()
