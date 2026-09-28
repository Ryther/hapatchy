"""Read GitHub state and execute only a freshly eligible auto-merge opt-in."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlencode

from script.ha_release_catalog import fetch_pypi_json, latest_pair
from script.ha_update_merge import (
    RELEASE_BRANCH,
    RELEASE_PATHS,
    REPOSITORY,
    UPDATE_BRANCH,
    UPDATE_PATHS,
    PullRequestSnapshot,
    RepoSnapshot,
    eligible_release,
    eligible_update,
)
from script.resolve_ha_locks import validate_lock
from script.update_ha_baseline import ROOT, TOOLS, plan

MAX_FILE_BYTES = 1024 * 1024


def _gh_json(endpoint: str) -> Any:
    """Read a fixed GitHub API endpoint with brief transient-failure retries."""
    for attempt in range(3):
        result = subprocess.run(
            ["gh", "api", endpoint], capture_output=True, text=True, timeout=30, check=False
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        if attempt < 2:
            time.sleep(2**attempt)
    raise ValueError(f"GitHub API request failed: {endpoint.split('?', 1)[0]}")


def _api_list(endpoint: str) -> list[dict[str, Any]]:
    value = _gh_json(endpoint)
    if not isinstance(value, list) or len(value) >= 100 or not all(isinstance(item, dict) for item in value):
        raise ValueError("Incomplete GitHub API list")
    return value


def open_targets() -> tuple[list[int], list[int]]:
    """Return all open updater and Release Please PR numbers; reject duplicates."""
    pulls = _api_list(f"repos/{REPOSITORY}/pulls?state=open&per_page=100")
    updates = [item["number"] for item in pulls if item.get("head", {}).get("ref") == UPDATE_BRANCH]
    releases = [item["number"] for item in pulls if item.get("head", {}).get("ref") == RELEASE_BRANCH]
    if len(updates) > 1 or len(releases) > 1:
        raise ValueError("Multiple matching automation PRs require review")
    return updates, releases


def load_repo(release_numbers: list[int]) -> RepoSnapshot:
    """Read branch rule, latest published release and exact unreleased commits."""
    repository = _gh_json(f"repos/{REPOSITORY}")
    branch = _gh_json(f"repos/{REPOSITORY}/branches/main")
    release = _gh_json(f"repos/{REPOSITORY}/releases/latest")
    main_sha = branch["commit"]["sha"]
    latest_tag = release["tag_name"]
    comparison = _gh_json(f"repos/{REPOSITORY}/compare/{latest_tag}...{main_sha}")
    commits = comparison.get("commits")
    protection = branch.get("protection", {}).get("required_status_checks", {})
    if (
        branch.get("protected") is not True
        or branch.get("protection", {}).get("enabled") is not True
        or protection.get("enforcement_level") != "everyone"
        or not isinstance(protection.get("contexts"), list)
        or not isinstance(commits, list)
        or comparison.get("ahead_by") != len(commits)
        or len(commits) >= 100
    ):
        raise ValueError("Branch protection or release comparison is incomplete")
    return RepoSnapshot(
        main_sha=main_sha,
        latest_version=latest_tag.removeprefix("v"),
        unreleased=tuple(item["commit"]["message"].splitlines()[0] for item in commits),
        open_release_prs=tuple(release_numbers),
        required_checks=frozenset(protection["contexts"]),
        auto_merge_allowed=repository.get("allow_auto_merge") is True,
    )


def _required_results(head_sha: str) -> dict[str, str]:
    response = _gh_json(f"repos/{REPOSITORY}/commits/{head_sha}/check-runs?per_page=100")
    runs = response.get("check_runs")
    if not isinstance(runs, list) or response.get("total_count", len(runs)) >= 100:
        raise ValueError("Incomplete required-check result list")
    outcomes: dict[str, list[str]] = {}
    for run in runs:
        name = run.get("name")
        if not isinstance(name, str) or run.get("head_sha") != head_sha:
            continue
        outcome = run.get("conclusion") or "pending"
        outcomes.setdefault(name, []).append(outcome)
    statuses = _api_list(f"repos/{REPOSITORY}/commits/{head_sha}/statuses?per_page=100")
    for status in statuses:
        name = status.get("context")
        if isinstance(name, str):
            outcomes.setdefault(name, []).append(status.get("state", "pending"))
    return {name: "success" if all(value == "success" for value in values) else "failed" for name, values in outcomes.items()}


def _content(path: str, sha: str) -> bytes:
    endpoint = f"repos/{REPOSITORY}/contents/{quote(path, safe='/')}?{urlencode({'ref': sha})}"
    response = _gh_json(endpoint)
    if response.get("encoding") != "base64" or not isinstance(response.get("content"), str):
        raise ValueError("Missing release file contents")
    encoded = response["content"]
    if len(encoded) > MAX_FILE_BYTES * 2:
        raise ValueError("Release file exceeded review limit")
    data = base64.b64decode(encoded.replace("\n", "").replace("\r", ""), validate=True)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Release file exceeded review limit")
    return data


def exact_update(head_sha: str, title: str, base_sha: str) -> bool:
    """Compare the PR with a freshly resolved proposal from the trusted main checkout."""
    match = re.fullmatch(r"fix\(compat\): validate Home Assistant ([0-9]+\.[0-9]+\.[0-9]+)", title)
    local_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True, timeout=10
    ).stdout.strip()
    if match is None or local_sha != base_sha:
        return False
    current = validate_lock(ROOT / TOOLS)["homeassistant"]
    pair = latest_pair(fetch_pypi_json, current, "3.14.7")
    if pair is None or pair[0] != match.group(1):
        return False
    expected = plan(ROOT, *pair).edits
    return set(expected) == UPDATE_PATHS and all(
        _content(str(path), head_sha) == content for path, content in expected.items()
    )


def version_only_release(
    base: Mapping[str, bytes],
    head: Mapping[str, bytes],
    old_version: str,
    new_version: str,
    ha_version: str,
    update_sha: str,
) -> bool:
    """Require only the four expected Release Please file transformations."""
    if set(base) != RELEASE_PATHS or set(head) != RELEASE_PATHS:
        return False
    try:
        old_manifest = json.loads(base[".release-please-manifest.json"])
        new_manifest = json.loads(head[".release-please-manifest.json"])
        old_integration = json.loads(base["custom_components/hapatchy/manifest.json"])
        new_integration = json.loads(head["custom_components/hapatchy/manifest.json"])
    except (ValueError, UnicodeDecodeError):
        return False
    if old_manifest != {".": old_version} or new_manifest != {".": new_version}:
        return False
    if old_integration.get("version") != old_version or new_integration.get("version") != new_version:
        return False
    if {**new_integration, "version": old_version} != old_integration:
        return False
    old_pyproject = base["pyproject.toml"]
    new_pyproject = head["pyproject.toml"]
    old_field = f'version = "{old_version}"'.encode()
    new_field = f'version = "{new_version}"'.encode()
    if old_pyproject.count(old_field) != 1 or old_pyproject.replace(old_field, new_field) != new_pyproject:
        return False
    old_log = base["CHANGELOG.md"]
    new_log = head["CHANGELOG.md"]
    header = b"# Changelog\n\n"
    if not old_log.startswith(header) or not new_log.startswith(header):
        return False
    old_body = old_log[len(header) :]
    new_body = new_log[len(header) :]
    if not new_body.endswith(old_body):
        return False
    inserted = new_body[: -len(old_body)] if old_body else new_body
    try:
        section = inserted.decode("utf-8")
    except UnicodeDecodeError:
        return False
    heading = re.escape(f"## [{new_version}](https://github.com/{REPOSITORY}/compare/v{old_version}...v{new_version})")
    line = re.escape(f"validate Home Assistant {ha_version}")
    sha = re.escape(update_sha)
    issue = rf"(?: \(\[#\d+\]\(https://github.com/{REPOSITORY}/issues/\d+\)\))?"
    pattern = rf"{heading} \(\d{{4}}-\d{{2}}-\d{{2}}\)\n+### Bug Fixes\n+\* {line}{issue} \(\[{sha[:7]}\]\(https://github.com/{REPOSITORY}/commit/{sha}\)\)\n+"
    return re.fullmatch(pattern, section) is not None


def load_pr(number: int, repo: RepoSnapshot) -> PullRequestSnapshot:
    response = _gh_json(f"repos/{REPOSITORY}/pulls/{number}")
    if response.get("state") != "open":
        raise ValueError("Automation PR is no longer open")
    head_sha = response["head"]["sha"]
    base_sha = response["base"]["sha"]
    files = _api_list(f"repos/{REPOSITORY}/pulls/{number}/files?per_page=100")
    commits = _api_list(f"repos/{REPOSITORY}/pulls/{number}/commits?per_page=100")
    checks = _required_results(head_sha)
    checks_green = all(checks.get(name) == "success" for name in repo.required_checks)
    content_ok = False
    update_ok = False
    if checks_green and response["head"]["ref"] == UPDATE_BRANCH:
        update_ok = exact_update(head_sha, response["title"], base_sha)
    if checks_green and response["head"]["ref"] == RELEASE_BRANCH:
        title = response["title"]
        match = re.fullmatch(r"chore\(main\): release ([0-9]+\.[0-9]+\.[0-9]+)", title)
        update = re.fullmatch(
            r"fix\(compat\): validate Home Assistant ([0-9]+\.[0-9]+\.[0-9]+)",
            repo.unreleased[0] if len(repo.unreleased) == 1 else "",
        )
        if match and update and {item["filename"] for item in files} == RELEASE_PATHS:
            base_content = {path: _content(path, base_sha) for path in RELEASE_PATHS}
            head_content = {path: _content(path, head_sha) for path in RELEASE_PATHS}
            content_ok = version_only_release(
                base_content, head_content, repo.latest_version, match.group(1),
                update.group(1), repo.main_sha,
            )
    return PullRequestSnapshot(
        number=number,
        title=response["title"],
        author=response["user"]["login"],
        head_ref=response["head"]["ref"],
        head_repo=response["head"]["repo"]["full_name"],
        base_ref=response["base"]["ref"],
        base_sha=base_sha,
        head_sha=head_sha,
        changed_files=tuple(item["filename"] for item in files),
        commits=tuple(item["commit"]["message"].splitlines()[0] for item in commits),
        checks=checks,
        auto_merge_enabled=response.get("auto_merge") is not None,
        version_only_release=content_ok,
        exact_update=update_ok,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    updates, releases = open_targets()
    if not updates and not releases:
        print("No HA automation PR is open")
        return 0
    repo = load_repo(releases)
    number = updates[0] if updates else releases[0]
    kind = "update" if updates else "release"
    pr = load_pr(number, repo)
    evaluate = eligible_update if kind == "update" else eligible_release
    decision = evaluate(repo, pr)
    print(f"PR #{number}: {decision.reason}")
    if args.dry_run or not decision.eligible:
        return 0
    # A second snapshot closes the discovery-to-merge time-of-check gap.
    fresh_updates, fresh_releases = open_targets()
    if (fresh_updates, fresh_releases) != (updates, releases):
        raise ValueError("Automation PR set changed before merge opt-in")
    fresh_repo = load_repo(fresh_releases)
    fresh_pr = load_pr(number, fresh_repo)
    if fresh_repo.main_sha != repo.main_sha or fresh_pr.head_sha != pr.head_sha:
        raise ValueError("Automation commit changed before merge opt-in")
    if not evaluate(fresh_repo, fresh_pr).eligible:
        raise ValueError("Automation eligibility changed before merge opt-in")
    subprocess.run(
        ["gh", "pr", "merge", str(number), "--repo", REPOSITORY, "--auto", "--squash", "--match-head-commit", pr.head_sha],
        check=True, timeout=60,
    )
    print(f"Enabled auto-merge for eligible PR #{number} at {pr.head_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
