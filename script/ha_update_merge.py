"""Opt in only an isolated, exact-SHA HA update and its patch release."""

from __future__ import annotations

import re
from dataclasses import dataclass

from packaging.version import Version

from script.update_ha_baseline import EDITABLE_PATHS

REPOSITORY = "Ryther/hapatchy"
UPDATE_BRANCH = "automation/ha-baseline"
RELEASE_BRANCH = "release-please--branches--main--components--hapatchy"
UPDATE_PATHS = frozenset(EDITABLE_PATHS)
RELEASE_PATHS = frozenset(
    (
        ".release-please-manifest.json",
        "CHANGELOG.md",
        "custom_components/hapatchy/manifest.json",
        "pyproject.toml",
    )
)
MANDATORY_CHECKS = frozenset(
    ("Sonar required", "HA tests required", "HA boot required", "Recent HA advisory gate")
)
SHA = re.compile(r"[0-9a-f]{40}")
UPDATE_TITLE = re.compile(r"fix\(compat\): validate Home Assistant ([0-9]+\.[0-9]+\.[0-9]+)")
RELEASE_TITLE = re.compile(r"chore\(main\): release ([0-9]+\.[0-9]+\.[0-9]+)")


@dataclass(frozen=True)
class RepoSnapshot:
    main_sha: str
    latest_version: str
    unreleased: tuple[str, ...]
    open_release_prs: tuple[int, ...]
    required_checks: frozenset[str]
    auto_merge_allowed: bool


@dataclass(frozen=True)
class PullRequestSnapshot:
    number: int
    title: str
    author: str
    head_ref: str
    head_repo: str
    base_ref: str
    base_sha: str
    head_sha: str
    changed_files: tuple[str, ...]
    commits: tuple[str, ...]
    checks: dict[str, str]
    auto_merge_enabled: bool
    version_only_release: bool
    exact_update: bool = False


@dataclass(frozen=True)
class Decision:
    eligible: bool
    reason: str


def _common(repo: RepoSnapshot, pr: PullRequestSnapshot) -> Decision:
    if not repo.auto_merge_allowed:
        return Decision(False, "Repository auto-merge is disabled")
    if not MANDATORY_CHECKS.issubset(repo.required_checks):
        return Decision(False, "Required Sonar, HA or advisory branch rule is absent")
    if pr.author != "Ryther" or pr.head_repo != REPOSITORY:
        return Decision(False, "Unexpected PR author or repository")
    if pr.base_ref != "main" or pr.base_sha != repo.main_sha:
        return Decision(False, "PR base changed")
    if not SHA.fullmatch(pr.head_sha) or not SHA.fullmatch(repo.main_sha):
        return Decision(False, "Invalid commit identity")
    if pr.auto_merge_enabled:
        return Decision(False, "Auto-merge is already enabled")
    if any(pr.checks.get(name) != "success" for name in repo.required_checks):
        return Decision(False, "A required check is missing, pending or failed")
    return Decision(True, "All required checks passed at the current head")


def eligible_update(repo: RepoSnapshot, pr: PullRequestSnapshot) -> Decision:
    """Select one trusted update PR only before other unreleased work exists."""
    common = _common(repo, pr)
    if not common.eligible:
        return common
    if pr.head_ref != UPDATE_BRANCH or UPDATE_TITLE.fullmatch(pr.title) is None:
        return Decision(False, "Not the expected HA update proposal")
    if set(pr.changed_files) != {str(path) for path in UPDATE_PATHS}:
        return Decision(False, "HA update changes unexpected files")
    if not pr.exact_update:
        return Decision(False, "HA update differs from trusted baseline calculation")
    if pr.commits != (pr.title,):
        return Decision(False, "HA update contains unexpected commits")
    if repo.unreleased or repo.open_release_prs:
        return Decision(False, "Unrelated work or a release PR is already pending")
    return Decision(True, "Isolated HA update can opt into auto-merge")


def eligible_release(repo: RepoSnapshot, pr: PullRequestSnapshot) -> Decision:
    """Release only the immediately preceding HA update as a patch version."""
    common = _common(repo, pr)
    if not common.eligible:
        return common
    title = RELEASE_TITLE.fullmatch(pr.title)
    if pr.head_ref != RELEASE_BRANCH or title is None:
        return Decision(False, "Not the expected Release Please proposal")
    if set(pr.changed_files) != RELEASE_PATHS or not pr.version_only_release:
        return Decision(False, "Release PR contains changes beyond version and changelog")
    if pr.commits != (pr.title,) or repo.open_release_prs != (pr.number,):
        return Decision(False, "Release PR identity or uniqueness changed")
    if len(repo.unreleased) != 1 or UPDATE_TITLE.fullmatch(repo.unreleased[0]) is None:
        return Decision(False, "Main contains unrelated unreleased commits")
    proposed = Version(title.group(1))
    previous = Version(repo.latest_version)
    if proposed.release != (previous.major, previous.minor, previous.micro + 1):
        return Decision(False, "Release is not the next patch version")
    return Decision(True, "Isolated HA patch release can opt into auto-merge")
