"""Release security gate checks the exact analyzed commit and overall findings."""

import sys

import pytest

from script import check_sonar_release


def _fetch_with_findings(*, revision, status="OK", security=0, hotspots=0):
    def fetch(path, params):
        if path == "/api/project_analyses/search":
            return {"analyses": [{"revision": revision}]}
        if path == "/api/qualitygates/project_status":
            return {"projectStatus": {"status": status}}
        if path == "/api/issues/search":
            assert params["impactSoftwareQualities"] == "SECURITY"
            assert params["resolved"] == "false"
            return {"paging": {"total": security}, "issues": []}
        if path == "/api/hotspots/search":
            assert params["status"] == "TO_REVIEW"
            return {"paging": {"total": hotspots}, "hotspots": []}
        raise AssertionError(path)

    return fetch


def test_release_gate_accepts_only_clean_exact_analysis():
    sha = "a" * 40
    assert check_sonar_release.check_analysis(_fetch_with_findings(revision=sha), sha)


def test_release_gate_waits_for_exact_commit():
    assert not check_sonar_release.check_analysis(
        _fetch_with_findings(revision="b" * 40), "a" * 40
    )


@pytest.mark.parametrize(
    ("finding", "value", "reason"),
    [("security", 1, "security issues"), ("hotspots", 1, "unreviewed hotspots"),
     ("status", "ERROR", "quality gate")],
)
def test_release_gate_blocks_open_findings(finding, value, reason):
    sha = "a" * 40
    options = {"revision": sha, finding: value}
    with pytest.raises(ValueError, match=reason):
        check_sonar_release.check_analysis(_fetch_with_findings(**options), sha)


def test_release_gate_rejects_analysis_that_changes_during_check():
    sha = "a" * 40
    fetch = _fetch_with_findings(revision=sha)
    seen = 0

    def changing_fetch(path, params):
        nonlocal seen
        if path == "/api/project_analyses/search":
            seen += 1
            if seen == 2:
                return {"analyses": [{"revision": "b" * 40}]}
        return fetch(path, params)

    assert not check_sonar_release.check_analysis(changing_fetch, sha)


def test_release_gate_rejects_invalid_sha():
    with pytest.raises(ValueError, match="SHA"):
        check_sonar_release.check_analysis(_fetch_with_findings(revision="a" * 40), "main")


def test_release_gate_rejects_invalid_issue_count():
    sha = "a" * 40
    fetch = _fetch_with_findings(revision=sha)

    def invalid_fetch(path, params):
        result = fetch(path, params)
        if path == "/api/issues/search":
            result["paging"]["total"] = "0"
        return result

    with pytest.raises(ValueError, match="issue count"):
        check_sonar_release.check_analysis(invalid_fetch, sha)


def test_release_gate_cli_waits_for_exact_analysis(monkeypatch, capsys):
    sha = "a" * 40
    revisions = iter(["b" * 40, sha, sha])
    fetch = _fetch_with_findings(revision=sha)
    waits = []

    def delayed_fetch(path, params):
        if path == "/api/project_analyses/search":
            return {"analyses": [{"revision": next(revisions)}]}
        return fetch(path, params)

    monkeypatch.setattr(sys, "argv", ["check_sonar_release", "--sha", sha])
    monkeypatch.setattr(check_sonar_release, "_http_fetch", lambda host, token: delayed_fetch)
    monkeypatch.setattr(check_sonar_release.time, "sleep", waits.append)

    check_sonar_release.main()

    assert waits == [15]
    assert sha in capsys.readouterr().out


def test_release_gate_cli_times_out_on_stale_scan(monkeypatch):
    sha = "a" * 40
    waits = []
    monkeypatch.setattr(sys, "argv", ["check_sonar_release", "--sha", sha])
    monkeypatch.setattr(
        check_sonar_release,
        "_http_fetch",
        lambda host, token: _fetch_with_findings(revision="b" * 40),
    )
    monkeypatch.setattr(check_sonar_release.time, "sleep", waits.append)

    with pytest.raises(RuntimeError, match="exact release SHA"):
        check_sonar_release.main()
    assert waits == [15] * 39
