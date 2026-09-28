"""Contract checks for a portable, complete Sonar issue export."""

import json
from pathlib import Path

import pytest

from script import sonar_ci_local
from script.sonar_ci_local import candidate_scan_ok
from script.sonar_ci_report import export_analysis, introduced_issues


def test_export_paginates_issues_and_keeps_pr_scope(tmp_path: Path) -> None:
    calls = []

    def fetch(path, params):
        calls.append((path, dict(params)))
        if path == "/api/issues/search":
            page = int(params["p"])
            return {
                "total": 2,
                "issues": [{"key": f"issue-{page}", "rule": "python:S1", "component": "repo:file.py", "hash": f"hash-{page}", "message": "Check me", "status": "OPEN"}],
            }
        if path == "/api/qualitygates/project_status":
            return {"projectStatus": {"status": "ERROR"}}
        if path == "/api/measures/component":
            return {"component": {"measures": []}}
        if path == "/api/measures/component_tree":
            return {"paging": {"total": 0}, "components": []}
        if path == "/api/hotspots/search":
            return {"paging": {"total": 0}, "hotspots": []}
        raise AssertionError(path)

    result = export_analysis(fetch, "repo", tmp_path, pull_request="42", page_size=1)
    assert [issue["key"] for issue in result["issues"]] == ["issue-1", "issue-2"]
    assert json.loads((tmp_path / "issues.json").read_text()) == result["issues"]
    assert "issue-2" in (tmp_path / "report.md").read_text()
    assert all(params.get("pullRequest") == "42" for _, params in calls)


def test_export_refuses_missing_analysis(tmp_path: Path) -> None:
    def fetch(path, params):
        if path == "/api/qualitygates/project_status":
            return {"projectStatus": {"status": "NONE"}}
        raise AssertionError(path)

    with pytest.raises(ValueError, match="not computed"):
        export_analysis(fetch, "repo", tmp_path, pull_request="42")


def test_introduced_issues_uses_stable_fingerprint() -> None:
    before = [{"rule": "python:S1", "component": "baseline:foo.py", "hash": "a", "line": 1}]
    after = [
        {"rule": "python:S1", "component": "candidate:foo.py", "hash": "a", "line": 9},
        {"rule": "python:S2", "component": "candidate:bar.py", "hash": "b", "line": 3},
    ]
    assert introduced_issues(before, after) == [after[1]]


def test_introduced_issues_preserves_duplicate_counts() -> None:
    issue = {"rule": "python:S1", "component": "candidate:foo.py", "hash": "a"}
    assert introduced_issues([{**issue, "component": "baseline:foo.py"}], [issue, issue]) == [issue]


@pytest.mark.parametrize(
    ("exit_code", "gate", "expected"),
    [(0, "OK", True), (1, "OK", False), (0, "ERROR", False), (0, "NONE", False)],
)
def test_candidate_requires_successful_scanner_and_gate(exit_code: int, gate: str, expected: bool) -> None:
    assert candidate_scan_ok(exit_code, gate) is expected


def test_comparison_rejects_failed_gate_even_without_new_issues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def request(path, params=None, *, post=False, token=""):
        if path == "/api/user_tokens/generate":
            return {"token": "disposable"}
        assert path == "/api/user_tokens/revoke"
        return {}

    def export(fetch, project, directory):
        directory.mkdir()
        (directory / "issues.json").write_text("[]")
        (directory / "gate.json").write_text(json.dumps({"projectStatus": {"status": "ERROR"}}))

    monkeypatch.setattr(sonar_ci_local, "request", request)
    monkeypatch.setattr(sonar_ci_local, "scan", lambda *args: 0)
    monkeypatch.setattr(sonar_ci_local, "export_analysis", export)

    with pytest.raises(RuntimeError, match="gate ERROR"):
        sonar_ci_local.compare(tmp_path, tmp_path, tmp_path / "report")
    assert "ERROR" in (tmp_path / "report/report.md").read_text()
