"""Auto-merge requires a single trusted baseline update or release."""

from dataclasses import replace

from script import ha_update_merge as merge


def _repo(**changes):
    return merge.RepoSnapshot(
        main_sha="a" * 40,
        latest_version="1.0.3",
        unreleased=(),
        open_release_prs=(),
        required_checks=merge.MANDATORY_CHECKS,
        auto_merge_allowed=True,
        **changes,
    )


def _update(**changes):
    return merge.PullRequestSnapshot(
        number=61,
        title="fix(compat): validate Home Assistant 2026.9.4",
        author="Ryther",
        head_ref="automation/ha-baseline",
        head_repo="Ryther/hapatchy",
        base_ref="main",
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=tuple(str(path) for path in merge.UPDATE_PATHS),
        commits=("fix(compat): validate Home Assistant 2026.9.4",),
        checks={name: "success" for name in merge.MANDATORY_CHECKS},
        auto_merge_enabled=False,
        version_only_release=False,
        **changes,
    )


def _release(**changes):
    return merge.PullRequestSnapshot(
        number=62,
        title="chore(main): release 1.0.4",
        author="Ryther",
        head_ref="release-please--branches--main--components--hapatchy",
        head_repo="Ryther/hapatchy",
        base_ref="main",
        base_sha="a" * 40,
        head_sha="c" * 40,
        changed_files=tuple(merge.RELEASE_PATHS),
        commits=("chore(main): release 1.0.4",),
        checks={name: "success" for name in merge.MANDATORY_CHECKS},
        auto_merge_enabled=False,
        version_only_release=True,
        **changes,
    )


def test_clean_update_is_eligible():
    assert merge.eligible_update(_repo(), _update()).eligible


def test_preexisting_release_pr_blocks_update():
    repo = replace(_repo(), open_release_prs=(53,))
    assert not merge.eligible_update(repo, _update()).eligible


def test_unrelated_main_commit_blocks_update():
    repo = replace(_repo(), unreleased=("docs: improve user guide",))
    assert not merge.eligible_update(repo, _update()).eligible


def test_changed_head_or_base_blocks_update():
    assert not merge.eligible_update(_repo(), replace(_update(), base_sha="d" * 40)).eligible
    assert not merge.eligible_update(_repo(), replace(_update(), head_sha="not-a-sha")).eligible


def test_extra_file_or_failed_required_check_blocks_update():
    pr = replace(_update(), changed_files=(*_update().changed_files, "custom_components/hapatchy/__init__.py"))
    assert not merge.eligible_update(_repo(), pr).eligible
    checks = {name: "success" for name in merge.MANDATORY_CHECKS}
    checks["Sonar required"] = "pending"
    assert not merge.eligible_update(_repo(), replace(_update(), checks=checks)).eligible


def test_clean_isolated_release_is_eligible():
    repo = replace(
        _repo(),
        unreleased=("fix(compat): validate Home Assistant 2026.9.4",),
        open_release_prs=(62,),
    )
    assert merge.eligible_release(repo, _release()).eligible


def test_release_rejects_unrelated_commits_or_non_version_diff():
    repo = replace(
        _repo(),
        unreleased=("fix(compat): validate Home Assistant 2026.9.4", "docs: unrelated"),
        open_release_prs=(62,),
    )
    assert not merge.eligible_release(repo, _release()).eligible
    repo = replace(repo, unreleased=("fix(compat): validate Home Assistant 2026.9.4",))
    assert not merge.eligible_release(repo, replace(_release(), version_only_release=False)).eligible


def test_duplicate_run_does_not_reenable_auto_merge():
    assert not merge.eligible_update(_repo(), replace(_update(), auto_merge_enabled=True)).eligible
