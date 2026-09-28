"""Fail a release unless Sonar analyzed its exact commit with no security debt."""

from __future__ import annotations

import argparse
import re
import time

from .sonar_ci_report import Fetch, _http_fetch

PROJECT = "Ryther_hapatchy"
BRANCH = "main"
SHA = re.compile(r"[0-9a-f]{40}\Z")


def _revision(fetch: Fetch) -> str | None:
    result = fetch(
        "/api/project_analyses/search",
        {"project": PROJECT, "branch": BRANCH, "ps": 1},
    )
    analyses = result["analyses"]
    return analyses[0]["revision"] if analyses else None


def _total(result: dict) -> int:
    count = result["paging"]["total"]
    if type(count) is not int or count < 0:
        raise ValueError("Invalid Sonar issue count")
    return count


def check_analysis(fetch: Fetch, sha: str) -> bool:
    """Return False for a pending revision; reject an analyzed unsafe revision."""
    if not SHA.fullmatch(sha):
        raise ValueError("Invalid release SHA")
    if _revision(fetch) != sha:
        return False

    scope = {"branch": BRANCH}
    gate = fetch("/api/qualitygates/project_status", {"projectKey": PROJECT, **scope})
    if gate["projectStatus"]["status"] != "OK":
        raise ValueError("Sonar quality gate is not OK")
    issues = fetch(
        "/api/issues/search",
        {
            "componentKeys": PROJECT,
            "impactSoftwareQualities": "SECURITY",
            "resolved": "false",
            "ps": 1,
            **scope,
        },
    )
    if _total(issues) != 0:
        raise ValueError("Sonar has open security issues")
    hotspots = fetch(
        "/api/hotspots/search",
        {"projectKey": PROJECT, "status": "TO_REVIEW", "ps": 1, **scope},
    )
    if _total(hotspots) != 0:
        raise ValueError("Sonar has unreviewed hotspots")
    return _revision(fetch) == sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    fetch = _http_fetch("https://sonarcloud.io", "")
    for attempt in range(40):
        if check_analysis(fetch, args.sha):
            print(f"Sonar security gate passed for {args.sha}")
            return
        if attempt < 39:
            time.sleep(15)
    raise RuntimeError("Sonar did not analyze the exact release SHA within 10 minutes")


if __name__ == "__main__":
    main()
