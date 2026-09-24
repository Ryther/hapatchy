"""Immutable YAML grants and configuration-source provenance checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import yaml
from homeassistant.config import Secrets, load_yaml_config_file
from homeassistant.exceptions import HomeAssistantError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from .models import PatchError, Status, relative_parts
from .path_policy import LoadedGrants, PathPolicy
from .safe_io import GuardedFile
from .yaml_source_graph import SourceGraph, scan_source_graph

_MISSING = object()
_MAX_DIRECTORIES = 128
_MAX_DIRECTORY_LENGTH = 1024
_MAX_SOURCE_BYTES = 512 * 1024
_YAML_STR = "tag:yaml.org,2002:str"


@dataclass(frozen=True)
class YamlPolicy:
    """Frozen startup grants and the configuration graph that produced them."""

    root: Path
    hapatchy_directories: tuple[str, ...]
    ha_explicit_directories: tuple[str, ...]
    graph: SourceGraph

    def check_current(self) -> None:
        """Reject operations when any protected configuration source changed."""
        try:
            current = scan_source_graph(self.root)
        except (OSError, PatchError, yaml.YAMLError):
            raise PatchError("configuration_source_unavailable", Status.SECURITY_ERROR) from None
        if current != self.graph:
            raise PatchError("configuration_source_changed", Status.SECURITY_ERROR)


@dataclass(frozen=True)
class DeniedYamlPolicy:
    """Deny-all policy published after a post-schema setup failure."""

    reason: str
    hapatchy_directories: tuple[str, ...] = ()
    ha_explicit_directories: tuple[str, ...] = ()

    def check_current(self) -> None:
        """Keep denying until Home Assistant reloads the YAML configuration."""
        raise PatchError(self.reason, Status.SECURITY_ERROR)


def policy_for_hass(hass) -> PathPolicy:
    """Use only grants frozen by YAML setup; absent setup denies all."""
    from .const import DOMAIN

    shared = hass.data.get(DOMAIN, {})
    grants = shared.get("yaml_policy") or DeniedYamlPolicy("configuration_source_unavailable")
    return PathPolicy(
        Path(hass.config.config_dir),
        hass.config.is_allowed_path,
        cast(LoadedGrants, grants),
    )


def load_yaml_policy(root: Path, boot_config: dict[str, Any]) -> YamlPolicy:
    """Load strict grants only when raw YAML and HA's boot configuration agree.

    This synchronous adapter is intentionally called from Home Assistant's executor.
    """
    try:
        first_graph = scan_source_graph(root)
    except (OSError, PatchError, yaml.YAMLError):
        raise PatchError("configuration_source_unavailable", Status.SECURITY_ERROR) from None

    try:
        raw_document = load_yaml_config_file(str(root / "configuration.yaml"), Secrets(root))
        main_present = _validate_main_root(root)
    except PatchError:
        raise
    except (OSError, ValueError, yaml.YAMLError, HomeAssistantError):
        raise PatchError("hapatchy_yaml_invalid", Status.SECURITY_ERROR) from None

    if not isinstance(raw_document, dict) or not isinstance(boot_config, dict):
        _deny("configuration_mismatch")
    _reject_package_grants(raw_document)
    _reject_package_grants(boot_config)

    raw_value = raw_document.get("hapatchy", _MISSING)
    boot_value = boot_config.get("hapatchy", _MISSING)
    if main_present != (raw_value is not _MISSING) or main_present != (boot_value is not _MISSING):
        _deny("configuration_mismatch")
    raw_grants = validate_hapatchy_directories(raw_value) if main_present else ()
    boot_grants = validate_hapatchy_directories(boot_value) if main_present else ()
    if raw_grants != boot_grants:
        _deny("configuration_mismatch")

    raw_allowlist = _explicit_allowlist(raw_document)
    boot_allowlist = _explicit_allowlist(boot_config)
    if raw_allowlist != boot_allowlist:
        _deny("configuration_mismatch")

    try:
        second_graph = scan_source_graph(root)
    except (OSError, PatchError, yaml.YAMLError):
        raise PatchError("configuration_source_unavailable", Status.SECURITY_ERROR) from None
    if second_graph != first_graph:
        raise PatchError("configuration_source_changed", Status.SECURITY_ERROR)
    return YamlPolicy(root, raw_grants, raw_allowlist, first_graph)


def _validate_main_root(root: Path) -> bool:
    """Validate syntax HA normalizes away before ``async_setup`` sees it."""
    try:
        document = _compose_source(root, "configuration.yaml")
    except PatchError:
        raise
    except yaml.YAMLError:
        _deny("hapatchy_yaml_invalid")
    if document is None:
        return False
    if not isinstance(document, MappingNode):
        _deny("hapatchy_yaml_invalid")
    matches = [value for key, value in document.value if _plain_key(key) == "hapatchy"]
    if len(matches) > 1:
        _deny("hapatchy_yaml_invalid")
    if not matches:
        return False
    value = matches[0]
    if isinstance(value, ScalarNode) and value.tag == "!include":
        if not value.value:
            _deny("hapatchy_yaml_invalid")
        try:
            include_path = "/".join(relative_parts(value.value))
        except PatchError:
            _deny("hapatchy_yaml_invalid")
        included = _compose_source(root, include_path)
        if included is None:
            _deny("hapatchy_yaml_invalid")
        _validate_section_node(included)
        return True
    _validate_section_node(value)
    return True


def _compose_source(root: Path, path: str) -> Node | None:
    try:
        with GuardedFile(root, path, internal=True) as file:
            data = file.read(_MAX_SOURCE_BYTES).data
    except PatchError:
        raise PatchError("configuration_source_unavailable", Status.SECURITY_ERROR) from None
    return yaml.compose(data, Loader=yaml.Loader)


def _plain_key(node: Node) -> str | None:
    if isinstance(node, ScalarNode) and node.tag == _YAML_STR:
        return node.value
    return None


def _validate_section_node(node: Node) -> None:
    if not isinstance(node, MappingNode):
        _deny("hapatchy_yaml_invalid")
    if len(node.value) != 1 or _plain_key(node.value[0][0]) != "allowed_directories":
        _deny("hapatchy_yaml_invalid")
    directories = node.value[0][1]
    if not isinstance(directories, SequenceNode) or directories.tag != "tag:yaml.org,2002:seq":
        _deny("hapatchy_yaml_invalid")
    for directory in directories.value:
        if not isinstance(directory, ScalarNode) or directory.tag != _YAML_STR:
            _deny("hapatchy_yaml_invalid")


def validate_hapatchy_directories(value: object) -> tuple[str, ...]:
    """Strict HA-schema validator for the optional top-level HAPatchY section."""
    if not isinstance(value, dict) or set(value) != {"allowed_directories"}:
        _deny("hapatchy_yaml_invalid")
    directories = value["allowed_directories"]
    if not isinstance(directories, list) or len(directories) > _MAX_DIRECTORIES:
        _deny("hapatchy_yaml_invalid")
    checked: list[str] = []
    for directory in directories:
        if not isinstance(directory, str) or len(directory) > _MAX_DIRECTORY_LENGTH:
            _deny("hapatchy_yaml_invalid")
        try:
            relative_parts(directory)
        except PatchError:
            _deny("hapatchy_yaml_invalid")
        if any(character in directory for character in "*?[]"):
            _deny("hapatchy_yaml_invalid")
        checked.append(directory)
    if len(set(checked)) != len(checked):
        _deny("hapatchy_yaml_invalid")
    return tuple(checked)


def _explicit_allowlist(document: dict[str, Any]) -> tuple[str, ...]:
    homeassistant = document.get("homeassistant", _MISSING)
    if homeassistant is _MISSING:
        return ()
    if not isinstance(homeassistant, dict):
        _deny("configuration_mismatch")
    directories = homeassistant.get("allowlist_external_dirs", _MISSING)
    if directories is _MISSING:
        return ()
    if not isinstance(directories, list) or any(not isinstance(item, str) for item in directories):
        _deny("configuration_mismatch")
    return tuple(directories)


def _reject_package_grants(document: dict[str, Any]) -> None:
    homeassistant = document.get("homeassistant", _MISSING)
    if homeassistant is _MISSING:
        return
    if not isinstance(homeassistant, dict):
        _deny("configuration_mismatch")
    packages = homeassistant.get("packages", _MISSING)
    if packages is _MISSING:
        return
    if not isinstance(packages, dict):
        _deny("configuration_mismatch")
    for package in packages.values():
        if not isinstance(package, dict):
            _deny("configuration_mismatch")
        if "hapatchy" in package:
            _deny("hapatchy_package_forbidden")


def _deny(reason: str) -> NoReturn:
    raise PatchError(reason, Status.SECURITY_ERROR)
