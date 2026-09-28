"""The required Sonar result must represent the scanner that actually ran."""

import pytest

from script.sonar_gate import evaluate


@pytest.mark.parametrize(
    ("event", "trusted", "cloud", "community", "expected"),
    [
        ("push", False, "success", "skipped", True),
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
