"""Explicit disposable-HA YAML grants for positive integration tests."""

from pathlib import Path

from custom_components.hapatchy.const import DOMAIN
from custom_components.hapatchy.models import PatchError, relative_parts
from custom_components.hapatchy.path_policy import PathPolicy
from custom_components.hapatchy.yaml_policy import load_yaml_policy


def grant_directories(root: Path, directories=("scripts",), *, hass=None, extra_yaml="", files=None):
    if files is None:
        allowed = {"scripts/a.py"} if "scripts" in directories else set()
        for directory in directories:
            folder = root / directory
            if folder.is_dir():
                for path in folder.rglob("*"):
                    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                        continue
                    relative = path.relative_to(root).as_posix()
                    try:
                        relative_parts(relative)
                    except PatchError:
                        continue
                    allowed.add(relative)
        files = tuple(sorted(allowed))
    explicit = [str(root / directory) for directory in directories]
    yaml_lines = ["homeassistant:", "  allowlist_external_dirs:"]
    yaml_lines += [f"    - {directory}" for directory in explicit]
    yaml_lines += ["hapatchy:", "  allowed_files:"]
    if files:
        yaml_lines += [f"    - {file}" for file in files]
    else:
        yaml_lines[-1] += " []"
    (root / "configuration.yaml").write_text("\n".join(yaml_lines) + "\n" + extra_yaml)
    boot = {
        "homeassistant": {"allowlist_external_dirs": explicit},
        "hapatchy": {"allowed_files": list(files)},
    }
    loaded = load_yaml_policy(root, boot)
    if hass is not None:
        hass.config.allowlist_external_dirs = set(explicit)
        hass.data.setdefault(DOMAIN, {"restart_required": set()})["yaml_policy"] = loaded
        return PathPolicy(root, hass.config.is_allowed_path, loaded)
    return PathPolicy(
        root,
        lambda path: any(Path(path).is_relative_to(root / directory) for directory in directories),
        loaded,
    )
