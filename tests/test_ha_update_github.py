"""Release Please may change only the next patch version and its one entry."""

import base64
import json
import sys
from subprocess import CompletedProcess

from script import ha_update_github as github
from script.ha_update_merge import MANDATORY_CHECKS, UPDATE_PATHS, PullRequestSnapshot, RepoSnapshot

version_only_release = github.version_only_release


def _release_files():
    old, new = "1.0.3", "1.0.4"
    sha = "a" * 40
    manifest = {"domain": "hapatchy", "version": old, "requirements": ["watchdog==6.0.0"]}
    base = {
        ".release-please-manifest.json": json.dumps({".": old}).encode(),
        "CHANGELOG.md": b"# Changelog\n\n## [1.0.3] (old)\n",
        "custom_components/hapatchy/manifest.json": json.dumps(manifest).encode(),
        "pyproject.toml": b'[project]\nversion = "1.0.3"\nname = "hapatchy"\n',
    }
    section = (
        f"## [1.0.4](https://github.com/Ryther/hapatchy/compare/v1.0.3...v1.0.4) (2026-09-28)\n"
        f"* validate Home Assistant 2026.9.4 (https://github.com/Ryther/hapatchy/commit/{sha})\n\n"
    ).encode()
    head = {
        ".release-please-manifest.json": json.dumps({".": new}).encode(),
        "CHANGELOG.md": b"# Changelog\n\n" + section + base["CHANGELOG.md"][len(b"# Changelog\n\n") :],
        "custom_components/hapatchy/manifest.json": json.dumps({**manifest, "version": new}).encode(),
        "pyproject.toml": base["pyproject.toml"].replace(b"1.0.3", b"1.0.4"),
    }
    return base, head, sha


def test_version_only_release_accepts_one_exact_update():
    base, head, sha = _release_files()
    assert version_only_release(base, head, "1.0.3", "1.0.4", "2026.9.4", sha)


def test_version_only_release_rejects_hidden_manifest_change():
    base, head, sha = _release_files()
    manifest = json.loads(head["custom_components/hapatchy/manifest.json"])
    manifest["requirements"] = ["untrusted==1.0"]
    head["custom_components/hapatchy/manifest.json"] = json.dumps(manifest).encode()
    assert not version_only_release(base, head, "1.0.3", "1.0.4", "2026.9.4", sha)


def test_version_only_release_rejects_unrelated_changelog_entry():
    base, head, sha = _release_files()
    head["CHANGELOG.md"] += b"\n* unrelated change\n"
    assert not version_only_release(base, head, "1.0.3", "1.0.4", "2026.9.4", sha)


def test_github_api_parses_success_without_logging_token(monkeypatch):
    monkeypatch.setattr(
        github.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args, 0, stdout='{"ok": true}', stderr=""),
    )
    assert github._gh_json("repos/Ryther/hapatchy") == {"ok": True}


def test_exact_update_snapshot_and_dry_run(monkeypatch, capsys):
    main_sha, head_sha = "a" * 40, "b" * 40

    def get(endpoint):
        if endpoint.endswith("pulls?state=open&per_page=100"):
            return [{"number": 61, "head": {"ref": "automation/ha-baseline"}}]
        if endpoint.endswith("branches/main/protection/required_status_checks"):
            return {"strict": True, "contexts": list(MANDATORY_CHECKS)}
        if endpoint.endswith("branches/main"):
            return {"commit": {"sha": main_sha}}
        if endpoint.endswith("releases/latest"):
            return {"tag_name": "v1.0.3"}
        if "/compare/" in endpoint:
            return {"ahead_by": 0, "commits": []}
        if endpoint.endswith("/pulls/61"):
            return {
                "state": "open",
                "title": "fix(compat): validate Home Assistant 2026.9.4",
                "user": {"login": "Ryther"},
                "head": {"ref": "automation/ha-baseline", "sha": head_sha, "repo": {"full_name": "Ryther/hapatchy"}},
                "base": {"ref": "main", "sha": main_sha},
                "auto_merge": None,
            }
        if endpoint.endswith("/pulls/61/files?per_page=100"):
            return [{"filename": str(path)} for path in UPDATE_PATHS]
        if endpoint.endswith("/pulls/61/commits?per_page=100"):
            return [{"commit": {"message": "fix(compat): validate Home Assistant 2026.9.4"}}]
        if endpoint.endswith("/check-runs?per_page=100"):
            return {
                "total_count": len(MANDATORY_CHECKS),
                "check_runs": [
                    {"name": name, "head_sha": head_sha, "completed_at": "2026-09-28T00:00:00Z", "conclusion": "success"}
                    for name in MANDATORY_CHECKS
                ],
            }
        if endpoint.endswith("/statuses?per_page=100"):
            return []
        if endpoint == "repos/Ryther/hapatchy":
            return {"allow_auto_merge": True}
        raise AssertionError(endpoint)

    monkeypatch.setattr(github, "_gh_json", get)
    monkeypatch.setattr(sys, "argv", ["ha_update_github.py", "--dry-run"])
    assert github.main() == 0
    assert "Isolated HA update" in capsys.readouterr().out


def test_file_reader_decodes_exact_commit_contents(monkeypatch):
    observed = []

    def get(endpoint):
        observed.append(endpoint)
        return {"encoding": "base64", "content": base64.b64encode(b"version=1").decode()}

    monkeypatch.setattr(github, "_gh_json", get)
    assert github._content("pyproject.toml", "a" * 40) == b"version=1"
    assert "ref=" + "a" * 40 in observed[0]


def test_merge_command_rechecks_state_and_matches_exact_head(monkeypatch):
    repo = RepoSnapshot("a" * 40, "1.0.3", (), (), MANDATORY_CHECKS, True)
    pr = PullRequestSnapshot(
        61,
        "fix(compat): validate Home Assistant 2026.9.4",
        "Ryther",
        "automation/ha-baseline",
        "Ryther/hapatchy",
        "main",
        repo.main_sha,
        "b" * 40,
        tuple(str(path) for path in UPDATE_PATHS),
        ("fix(compat): validate Home Assistant 2026.9.4",),
        {name: "success" for name in MANDATORY_CHECKS},
        False,
        False,
    )
    calls = []
    monkeypatch.setattr(github, "open_targets", lambda: ([61], []))
    monkeypatch.setattr(github, "load_repo", lambda releases: repo)
    monkeypatch.setattr(github, "load_pr", lambda number, snapshot: pr)
    monkeypatch.setattr(
        github.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or CompletedProcess(command, 0),
    )
    monkeypatch.setattr(sys, "argv", ["ha_update_github.py"])
    assert github.main() == 0
    assert calls[0][-2:] == ["--match-head-commit", "b" * 40]
