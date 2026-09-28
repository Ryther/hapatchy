"""Fail closed when the scanner selected for an event did not produce a report."""

from __future__ import annotations

import os


def evaluate(
    event_name: str,
    trusted_pr: bool,
    coverage: str,
    cloud: str,
    community: str,
    report_present: bool,
) -> bool:
    """Return whether coverage and the event's sole expected scanner passed."""
    if coverage != "success" or not report_present:
        return False
    if event_name == "push":
        return cloud == "success" and community == "skipped"
    if event_name == "pull_request":
        if trusted_pr:
            return cloud == "success" and community == "skipped"
        return community == "success" and cloud == "skipped"
    return False


def main() -> None:
    """Evaluate explicit GitHub job outcomes without using a privileged token."""
    if not evaluate(
        os.environ["SONAR_EVENT_NAME"],
        os.environ["SONAR_TRUSTED_PR"] == "true",
        os.environ["SONAR_COVERAGE_RESULT"],
        os.environ["SONAR_CLOUD_RESULT"],
        os.environ["SONAR_COMMUNITY_RESULT"],
        os.environ["SONAR_REPORT_PRESENT"] == "true",
    ):
        raise SystemExit("Required Sonar scan or report is missing or unsuccessful")


if __name__ == "__main__":
    main()
