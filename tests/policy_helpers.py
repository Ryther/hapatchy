"""Explicit disposable-HA YAML grants for positive integration tests."""

from pathlib import Path

from custom_components.hapatchy.const import DOMAIN
from custom_components.hapatchy.path_policy import PathPolicy
from custom_components.hapatchy.yaml_policy import load_yaml_policy


def grant_directories(root: Path, directories=("scripts",), *, hass=None):
    explicit = [str(root / directory) for directory in directories]
    yaml_lines = ["homeassistant:", "  allowlist_external_dirs:"]
    yaml_lines += [f"    - {directory}" for directory in explicit]
    yaml_lines += ["hapatchy:", "  allowed_directories:"]
    yaml_lines += [f"    - {directory}" for directory in directories]
    (root / "configuration.yaml").write_text("\n".join(yaml_lines) + "\n")
    boot = {
        "homeassistant": {"allowlist_external_dirs": explicit},
        "hapatchy": {"allowed_directories": list(directories)},
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
