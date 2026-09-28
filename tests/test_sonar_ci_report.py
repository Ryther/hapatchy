"""Contract checks for a portable, complete Sonar issue export."""

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from script import sonar_ci_local, sonar_ci_report
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


def test_scan_waits_for_compute_result_and_preserves_scanner_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = "hapatchy-candidate"
    output = tmp_path / "report"
    output.mkdir()

    def run(command, *, env, stdout, stderr, check):
        assert f"{tmp_path}:{tmp_path}:ro" in command
        assert command[command.index("-w") + 1] == str(tmp_path)
        assert "-Dsonar.python.coverage.reportPaths=coverage.xml" in command
        assert env["SONAR_TOKEN"] == "temporary-token"
        (output / (project + "-task") / "report-task.txt").write_text("ceTaskId=task-123\n")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(sonar_ci_local.subprocess, "run", run)
    monkeypatch.setattr(sonar_ci_local, "request", lambda path, params, *, token: {"task": {"status": "SUCCESS"}})

    assert sonar_ci_local.scan(tmp_path, project, output, "temporary-token") == 1


def test_scan_rejects_missing_receipt_and_stale_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "report"
    task = output / "hapatchy-baseline-task"
    task.mkdir(parents=True)
    (task / "report-task.txt").write_text("ceTaskId=stale\n")
    monkeypatch.setattr(sonar_ci_local.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    with pytest.raises(RuntimeError, match="did not submit an analysis"):
        sonar_ci_local.scan(tmp_path, "hapatchy-baseline", output, "temporary-token")
    assert not (task / "report-task.txt").exists()


def test_scan_uses_absolute_docker_mount_with_relative_report_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "baseline").mkdir()

    def run(command, **kwargs):
        mount = command[command.index("-v", command.index("-v") + 1) + 1]
        assert mount == f"{tmp_path / 'sonar-report/hapatchy-baseline-task'}:/sonar-task"
        return SimpleNamespace(returncode=125)

    monkeypatch.setattr(sonar_ci_local.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="did not submit an analysis"):
        sonar_ci_local.scan(Path("baseline"), "hapatchy-baseline", Path("sonar-report"), "temporary-token")


def test_report_cli_uses_fixed_output_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["sonar_ci_report.py", "--project", "repo", "--pull-request", "47"])
    monkeypatch.setattr(sonar_ci_report, "_http_fetch", lambda host, token: lambda path, params: {})
    monkeypatch.setattr(
        sonar_ci_report,
        "export_analysis",
        lambda fetch, project, directory, *, pull_request: calls.append((project, directory, pull_request)),
    )

    sonar_ci_report.main()
    assert calls == [("repo", Path("sonar-report"), "47")]


def test_local_api_request_sends_ephemeral_token_only_to_local_server(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []

    class Response(io.BytesIO):
        status = 200

    def urlopen(request, *, timeout):
        requests.append(request)
        assert timeout == 30
        return Response(b'{"task":{"status":"SUCCESS"}}')

    monkeypatch.setattr(sonar_ci_local.urllib.request, "urlopen", urlopen)
    result = sonar_ci_local.request("/api/ce/task", {"id": "task-123"}, token="temporary-token")

    assert result == {"task": {"status": "SUCCESS"}}
    assert requests[0].full_url == sonar_ci_local.SERVER + "/api/ce/task?id=task-123"
    assert requests[0].get_header("Authorization") == "Bearer temporary-token"


def test_disposable_server_readiness_retries_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter([OSError("not listening"), {"status": "STARTING"}, {"status": "UP"}])
    waits = []

    def request(path):
        assert path == "/api/system/status"
        state = next(states)
        if isinstance(state, OSError):
            raise state
        return state

    monkeypatch.setattr(sonar_ci_local, "request", request)
    monkeypatch.setattr(sonar_ci_local.time, "sleep", waits.append)

    sonar_ci_local.ready()
    assert waits == [2, 2]
