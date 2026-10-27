"""Block PRs with high or critical advisories in HAPatchY requirements."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from packaging.utils import canonicalize_name
from packaging.version import Version

from script.resolve_ha_locks import PIN, validate_lock

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATHS = (
    Path(".devcontainer/requirements-tools.txt"),
    Path(".devcontainer/requirements-ha.txt"),
    Path("tests/requirements-ha-min.txt"),
)
MANIFEST_PATH = Path("custom_components/hapatchy/manifest.json")
SHARED_MINIMUM = "watchdog>=6.0.0"
MAX_PAGES = 10
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
AdvisoryClient = Callable[[list[tuple[str, str]]], list[dict[str, Any]]]


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    advisory: str
    severity: str


@dataclass(frozen=True)
class AuditResult:
    package_count: int
    findings: tuple[Finding, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.findings)


def _owned_versions(lock_paths: tuple[Path, ...], manifest_path: Path) -> dict[str, frozenset[str]]:
    """Resolve declared product requirements to every exact tested version."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("requirements"), list):
        raise ValueError("Invalid HAPatchY manifest requirements")
    rules: dict[str, tuple[str, str]] = {}
    for requirement in manifest["requirements"]:
        exact = PIN.fullmatch(requirement) if isinstance(requirement, str) else None
        minimum = requirement == SHARED_MINIMUM
        if exact is not None:
            name, bound = canonicalize_name(exact.group(1)), exact.group(2)
        elif minimum:
            name, bound = "watchdog", "6.0.0"
        else:
            raise ValueError("HAPatchY manifest requirements need exact pins or a shared watchdog minimum")
        if name in rules:
            raise ValueError(f"Duplicate HAPatchY manifest requirements: {name}")
        rules[name] = ("minimum" if minimum else "exact", bound)
    if not lock_paths:
        raise ValueError("Product requirements need at least one tested lock")
    owned: dict[str, set[str]] = {name: set() for name in rules}
    for path in lock_paths:
        locked = validate_lock(path)
        for name, (kind, bound) in rules.items():
            pin = locked.get(name)
            if pin is None or (kind == "exact" and pin != bound) or (
                kind == "minimum" and Version(pin) < Version(bound)
            ):
                raise ValueError(f"HAPatchY requirement {name} does not match {path.name}")
            owned[name].add(pin)
    return {name: frozenset(versions) for name, versions in owned.items()}


def audit(lock_paths: tuple[Path, ...], manifest_path: Path, advisory_client: AdvisoryClient) -> AuditResult:
    """Scan product requirements regardless of the HA-only lock contents."""
    pins = _owned_versions(lock_paths, manifest_path)
    ordered = sorted((name, pin) for name, versions in pins.items() for pin in versions)
    findings: set[Finding] = set()
    for pair in ordered:
        # Query versions separately: a name-keyed batch would lose older lanes.
        batch = [pair]
        returned = advisory_client(batch)
        if not isinstance(returned, list):
            raise ValueError("Malformed advisory API result")
        batch_pins = dict(batch)
        for item in returned:
            if not isinstance(item, dict):
                raise ValueError("Malformed advisory API result")
            advisory_id = item.get("ghsa_id")
            severity = item.get("severity")
            vulnerable = item.get("vulnerabilities")
            if (
                not isinstance(advisory_id, str)
                or not advisory_id.startswith("GHSA-")
                or severity not in {"unknown", "low", "medium", "high", "critical"}
                or not isinstance(vulnerable, list)
                or not isinstance(item.get("type"), str)
            ):
                raise ValueError("Malformed advisory API result")
            if item.get("withdrawn_at") is not None or severity not in {"high", "critical"}:
                continue
            matched = set()
            for entry in vulnerable:
                if not isinstance(entry, dict) or not isinstance(entry.get("package"), dict):
                    raise ValueError("Malformed advisory API result")
                package = entry["package"]
                if package.get("ecosystem") != "pip" or not isinstance(package.get("name"), str):
                    continue
                name = canonicalize_name(package["name"])
                if name in batch_pins:
                    matched.add(name)
            for name in matched:
                findings.add(Finding(name, batch_pins[name], advisory_id, severity))
    return AuditResult(len(pins), tuple(sorted(findings, key=lambda finding: (finding.package, finding.version, finding.advisory))))


def _request_page(url: str, token: str) -> tuple[list[dict[str, Any]], str | None]:
    if urlparse(url).scheme != "https" or urlparse(url).netloc != "api.github.com":
        raise ValueError("Unexpected advisory API endpoint")
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                link = response.headers.get("Link", "")
            break
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise ValueError(f"Advisory API HTTP {error.code}") from error
        except (URLError, TimeoutError) as error:
            if attempt == 2:
                raise ValueError("Advisory API network failure") from error
        time.sleep(2**attempt)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("Advisory API response exceeded limit")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("Malformed advisory API result")
    next_url = None
    for part in link.split(","):
        if 'rel="next"' in part:
            next_url = part.strip().split(";", 1)[0].strip("<>")
    return data, next_url


def github_advisories(pairs: list[tuple[str, str]], token: str) -> list[dict[str, Any]]:
    """Query both reviewed and unreviewed advisories with bounded pagination."""
    if not token:
        raise ValueError("Advisory API token unavailable")
    affects = ",".join(f"{name}@{version}" for name, version in pairs)
    advisories: dict[str, dict[str, Any]] = {}
    for review_type in ("reviewed", "unreviewed"):
        query = urlencode({"ecosystem": "pip", "type": review_type, "affects": affects, "per_page": 100})
        url: str | None = f"https://api.github.com/advisories?{query}"
        for _ in range(MAX_PAGES):
            if url is None:
                break
            page, url = _request_page(url, token)
            for item in page:
                if not isinstance(item, dict) or not isinstance(item.get("ghsa_id"), str):
                    raise ValueError("Malformed advisory API result")
                advisories[item["ghsa_id"]] = item
        else:
            if url is not None:
                raise ValueError("Advisory API pagination limit reached")
    return list(advisories.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # The trusted-base scanner on the transition PR still expects this argument.
    parser.add_argument("--base-sha", help=argparse.SUPPRESS)
    parser.add_argument("--candidate-root", type=Path, default=ROOT)
    args = parser.parse_args()
    paths = tuple(args.candidate_root / path for path in LOCK_PATHS)
    result = audit(
        paths,
        args.candidate_root / MANIFEST_PATH,
        lambda pairs: github_advisories(pairs, os.environ.get("GITHUB_TOKEN", "")),
    )
    print(f"Scanned {result.package_count} HAPatchY requirements")
    for finding in result.findings:
        print(f"{finding.package}=={finding.version}: {finding.severity} {finding.advisory}")
    return 1 if result.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
