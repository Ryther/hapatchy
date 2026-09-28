"""Find the latest stable Home Assistant and its exact pytest plugin."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

HA_URL = "https://pypi.org/pypi/homeassistant/json"
PLUGIN_URL = "https://pypi.org/pypi/pytest-homeassistant-custom-component/json"
MAX_PLUGIN_RELEASES = 64
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ReviewNeeded(ValueError):
    """The newest HA release cannot be adopted without human review."""


def plugin_version_url(version: str) -> str:
    """Construct a PyPI version-metadata URL from a parsed version."""
    return f"https://pypi.org/pypi/pytest-homeassistant-custom-component/{Version(version)}/json"


def fetch_pypi_json(url: str) -> Mapping[str, Any]:
    """Read bounded metadata from only the known PyPI JSON endpoints."""
    if not url.startswith("https://pypi.org/pypi/") or not url.endswith("/json"):
        raise ValueError("Unexpected metadata endpoint")
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=15) as response:
        if response.status != 200:
            raise ReviewNeeded("PyPI metadata request failed")
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ReviewNeeded("PyPI metadata response exceeded the limit")
    document = json.loads(data)
    if not isinstance(document, dict):
        raise ReviewNeeded("Malformed PyPI metadata")
    return document


def _stable_releases(data: Mapping[str, Any]) -> list[tuple[Version, list[dict[str, Any]]]]:
    releases = data.get("releases")
    if not isinstance(releases, dict):
        raise ReviewNeeded("Missing PyPI release list")
    candidates = []
    for raw, files in releases.items():
        if not isinstance(raw, str) or not isinstance(files, list):
            continue
        try:
            version = Version(raw)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease or version.is_postrelease:
            continue
        valid_files = [item for item in files if isinstance(item, dict) and not item.get("yanked", False)]
        if valid_files:
            candidates.append((version, valid_files))
    return sorted(candidates, reverse=True)


def _supports_python(files: list[dict[str, Any]], python_version: str) -> bool:
    try:
        version = Version(python_version)
        return any(
            not file.get("requires_python")
            or version in SpecifierSet(str(file["requires_python"]))
            for file in files
        )
    except ValueError as error:
        raise ReviewNeeded("Invalid Python compatibility metadata") from error


def _pins_exact_ha(metadata: Mapping[str, Any], ha_version: str) -> bool:
    info = metadata.get("info")
    if not isinstance(info, dict) or not isinstance(info.get("requires_dist"), list):
        raise ReviewNeeded("Missing pytest plugin requirements")
    for raw in info["requires_dist"]:
        if not isinstance(raw, str):
            raise ReviewNeeded("Malformed pytest plugin requirements")
        requirement = Requirement(raw)
        if canonicalize_name(requirement.name) != "homeassistant":
            continue
        return requirement.marker is None and str(requirement.specifier) == f"=={ha_version}"
    return False


def latest_pair(
    fetch_json: Callable[[str], Mapping[str, Any]], current: str, python_version: str
) -> tuple[str, str] | None:
    """Return the newest adoption candidate; reject ambiguity or unsupported Python."""
    ha_releases = _stable_releases(fetch_json(HA_URL))
    if not ha_releases:
        raise ReviewNeeded("No stable Home Assistant release")
    latest_ha, files = ha_releases[0]
    if latest_ha <= Version(current):
        return None
    if not _supports_python(files, python_version):
        raise ReviewNeeded("Newest Home Assistant requires a different Python version")
    plugin_releases = _stable_releases(fetch_json(PLUGIN_URL))
    for plugin, plugin_files in plugin_releases[:MAX_PLUGIN_RELEASES]:
        if not _supports_python(plugin_files, python_version):
            continue
        if _pins_exact_ha(fetch_json(plugin_version_url(str(plugin))), str(latest_ha)):
            return str(latest_ha), str(plugin)
    raise ReviewNeeded("No published exact pytest plugin for newest Home Assistant")
