"""Block recent HA lock updates with active high or critical advisories."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from packaging.utils import canonicalize_name

from script.resolve_ha_locks import validate_lock

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATHS = (
    Path(".devcontainer/requirements-tools.txt"),
    Path(".devcontainer/requirements-ha.txt"),
)
SHA = re.compile(r"[0-9a-f]{40}")
BATCH_SIZE = 20
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


def _pins(lock_paths: tuple[Path, Path]) -> dict[str, str]:
    combined: dict[str, str] = {}
    for path in lock_paths:
        for name, version in validate_lock(path).items():
            if name in combined and combined[name] != version:
                raise ValueError(f"Conflicting recent HA lock pins: {name}")
            combined[name] = version
    return combined


def audit(lock_paths: tuple[Path, Path], advisory_client: AdvisoryClient) -> AuditResult:
    """Scan every package in the union of both candidate locks."""
    pins = _pins(lock_paths)
    ordered = sorted(pins.items())
    findings: set[Finding] = set()
    for offset in range(0, len(ordered), BATCH_SIZE):
        batch = ordered[offset : offset + BATCH_SIZE]
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
            if not matched:
                raise ValueError("Malformed advisory API result: no affected package in batch")
            for name in matched:
                findings.add(Finding(name, batch_pins[name], advisory_id, severity))
    return AuditResult(len(pins), tuple(sorted(findings, key=lambda finding: (finding.package, finding.advisory))))


def audit_if_changed(
    lock_paths: tuple[Path, Path],
    base_bytes: tuple[bytes, bytes],
    advisory_client: AdvisoryClient,
) -> AuditResult | None:
    """Existing alerts do not block PRs that leave both recent locks untouched."""
    if all(path.read_bytes() == baseline for path, baseline in zip(lock_paths, base_bytes, strict=True)):
        return None
    return audit(lock_paths, advisory_client)


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


def _base_lock_bytes(base_sha: str) -> tuple[bytes, bytes]:
    if not SHA.fullmatch(base_sha):
        raise ValueError("Invalid base commit SHA")
    return tuple(
        subprocess.check_output(["git", "show", f"{base_sha}:{path.as_posix()}"], cwd=ROOT)
        for path in LOCK_PATHS
    )  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--candidate-root", type=Path, default=ROOT)
    args = parser.parse_args()
    paths = (args.candidate_root / LOCK_PATHS[0], args.candidate_root / LOCK_PATHS[1])
    result = audit_if_changed(
        paths,
        _base_lock_bytes(args.base_sha),
        lambda pairs: github_advisories(pairs, os.environ.get("GITHUB_TOKEN", "")),
    )
    if result is None:
        print("Recent HA locks unchanged; candidate advisory scan not applicable")
        return 0
    print(f"Scanned {result.package_count} recent-lock packages")
    for finding in result.findings:
        print(f"{finding.package}=={finding.version}: {finding.severity} {finding.advisory}")
    return 1 if result.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
