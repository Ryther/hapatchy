"""The required Sonar result must represent the scanner that actually ran."""

import pytest

from script.sonar_gate import evaluate, main


@pytest.mark.parametrize(
    ("event", "trusted", "cloud", "community", "expected"),
    [
        ("push", False, "success", "skipped", True),
        ("workflow_dispatch", False, "success", "skipped", True),
        ("workflow_dispatch", False, "skipped", "success", False),
        ("pull_request", True, "success", "skipped", True),
        ("pull_request", False, "skipped", "success", True),
        ("push", False, "skipped", "success", False),
        ("pull_request", True, "failure", "skipped", False),
        ("pull_request", False, "skipped", "failure", False),
        ("pull_request", True, "skipped", "skipped", False),
    ],
)
def test_evaluate_requires_the_expected_scanner(event, trusted, cloud, community, expected):
    assert evaluate(event, trusted, "success", cloud, community, True) is expected


def test_evaluate_rejects_missing_coverage_or_report():
    assert not evaluate("push", False, "failure", "success", "skipped", True)
    assert not evaluate("push", False, "success", "success", "skipped", False)


def test_cli_refuses_unrecognized_trust_flag(monkeypatch):
    values = {
        "SONAR_EVENT_NAME": "pull_request",
        "SONAR_TRUSTED_PR": "typo",
        "SONAR_COVERAGE_RESULT": "success",
        "SONAR_CLOUD_RESULT": "skipped",
        "SONAR_COMMUNITY_RESULT": "success",
        "SONAR_REPORT_PRESENT": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit, match="SONAR_TRUSTED_PR"):
        main()


def test_cli_refuses_missing_report(monkeypatch):
    values = {
        "SONAR_EVENT_NAME": "push",
        "SONAR_TRUSTED_PR": "false",
        "SONAR_COVERAGE_RESULT": "success",
        "SONAR_CLOUD_RESULT": "success",
        "SONAR_COMMUNITY_RESULT": "skipped",
        "SONAR_REPORT_PRESENT": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit, match="Required Sonar"):
        main()


def test_cli_accepts_completed_expected_scan(monkeypatch):
    values = {
        "SONAR_EVENT_NAME": "push",
        "SONAR_TRUSTED_PR": "false",
        "SONAR_COVERAGE_RESULT": "success",
        "SONAR_CLOUD_RESULT": "success",
        "SONAR_COMMUNITY_RESULT": "skipped",
        "SONAR_REPORT_PRESENT": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    main()
