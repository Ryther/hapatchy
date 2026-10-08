"""Read exact HA-owned dependency pins from a verified release wheel."""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from script.ha_release_catalog import fetch_pypi_json

MAX_WHEEL_BYTES = 120 * 1024 * 1024
MAX_CONSTRAINT_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_MANIFESTS = 4096
VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){2}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _download(url: str, limit: int) -> bytes:
    with build_opener(_NoRedirect).open(Request(url), timeout=30) as response:
        if response.status != 200:
            raise ValueError("HA wheel download failed")
        data = response.read(limit + 1)
    return data


def _exact_requirement(raw: str) -> tuple[str, str]:
    requirement = Requirement(raw)
    specifier = str(requirement.specifier)
    if requirement.marker is not None or not re.fullmatch(r"==[A-Za-z0-9_.!+\-]+", specifier):
        raise ValueError("HA-owned requirement is not an unconditional exact pin")
    return canonicalize_name(requirement.name), specifier[2:]


def _wheel_data(
    version: str,
    fetch_json: Callable[[str], Mapping[str, Any]],
    download: Callable[[str, int], bytes],
) -> bytes:
    if not VERSION.fullmatch(version):
        raise ValueError("Invalid Home Assistant wheel version")
    metadata = fetch_json(f"https://pypi.org/pypi/homeassistant/{version}/json")
    files = metadata.get("urls")
    filename = f"homeassistant-{version}-py3-none-any.whl"
    matches = (
        [item for item in files if isinstance(item, dict) and item.get("filename") == filename]
        if isinstance(files, list)
        else []
    )
    if len(matches) != 1 or matches[0].get("yanked") is not False:
        raise ValueError("Expected one non-yanked Home Assistant wheel")
    record = matches[0]
    url = record.get("url")
    digests = record.get("digests")
    digest = digests.get("sha256") if isinstance(digests, dict) else None
    size = record.get("size")
    if not isinstance(url, str) or not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise ValueError("Invalid Home Assistant wheel metadata")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "files.pythonhosted.org"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.endswith(".whl")
        or parsed.query
        or parsed.fragment
        or not isinstance(size, int)
        or not 0 < size <= MAX_WHEEL_BYTES
    ):
        raise ValueError("Unexpected Home Assistant wheel location or size")
    payload = download(url, MAX_WHEEL_BYTES)
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("Home Assistant wheel size or checksum mismatch")
    return payload


def load_ha_constraints(
    version: str,
    roots: frozenset[str],
    *,
    fetch_json: Callable[[str], Mapping[str, Any]] = fetch_pypi_json,
    download: Callable[[str, int], bytes] = _download,
) -> bytes:
    """Return only the wheel's exact pins for selected HA-owned roots."""
    if not roots:
        return b""
    payload = _wheel_data(version, fetch_json, download)
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate HA wheel paths")
            path = "homeassistant/package_constraints.txt"
            info = archive.getinfo(path)
            if info.file_size > MAX_CONSTRAINT_BYTES:
                raise ValueError("HA constraints exceed the size limit")
            constraints = archive.read(info).decode("utf-8")
            exact: dict[str, str] = {}
            for line in constraints.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                requirement = Requirement(line)
                name = canonicalize_name(requirement.name)
                if name in roots:
                    pin = _exact_requirement(line)[1]
                    if name in exact and exact[name] != pin:
                        raise ValueError("Conflicting HA constraints")
                    exact[name] = pin
            manifests = 0
            for entry in entries:
                if not (entry.filename.startswith("homeassistant/components/") and entry.filename.endswith("/manifest.json")):
                    continue
                manifests += 1
                if manifests > MAX_MANIFESTS or entry.file_size > MAX_MANIFEST_BYTES:
                    raise ValueError("HA manifest inventory exceeds the size limit")
                manifest = json.loads(archive.read(entry))
                requirements = manifest.get("requirements", [])
                if not isinstance(requirements, list):
                    raise ValueError("Malformed HA manifest requirements")
                for raw in requirements:
                    if not isinstance(raw, str):
                        raise ValueError("Malformed HA manifest requirement")
                    requirement = Requirement(raw)
                    name = canonicalize_name(requirement.name)
                    if name not in roots:
                        continue
                    pin = _exact_requirement(raw)[1]
                    if name in exact and exact[name] != pin:
                        raise ValueError(f"Conflicting HA pin for {name}")
                    exact[name] = pin
            if set(exact) != roots:
                raise ValueError(f"Missing HA-owned pins: {', '.join(sorted(roots - set(exact)))}")
            return "".join(f"{name}=={exact[name]}\n" for name in sorted(roots)).encode()
    except (BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid Home Assistant wheel content") from error
