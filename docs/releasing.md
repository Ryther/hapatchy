# Release HAPatchY

[Documentation home](index.md) · [Contribution rules](https://github.com/Ryther/hapatchy/blob/main/CONTRIBUTING.md)

Releases use a pull request. **Merging a feature does not publish a release;
merging the release PR authorizes publication after its checks pass.** A narrow
exception can opt an isolated Home Assistant baseline update and its resulting
patch release into GitHub auto-merge, after all required checks succeed.

Release Please proposes the version and changelog. Commitizen checks commit
messages. The publishing helper builds the integration archive, uploads it to a
GitHub draft and publishes that draft only after verification.
Before publication, the release workflow also waits for SonarCloud to analyze
the exact release commit on `main`. The project analysis covers the distributed
integration under `custom_components/hapatchy`; tests and CI tooling are outside
its quality metrics. It requires a passing quality gate, zero open security
issues in that product scope, and zero unreviewed security
hotspots. A missing or stale analysis leaves the draft unpublished. The normal
Sonar quality gate focuses on new code, so its green badge alone does not meet
this release condition.

Sonar does not scan the HA test locks for dependency advisories. The separate
product advisory gate uses the exact requirements in HAPatchY's manifest.
GitHub's raw Dependabot alert inventory can still show dependencies found in
tracked HA/test locks; alerts tied only to those locks are not product findings
or release gates.

User installation instructions are in [installation.md](installation.md).
HACS validation checks repository metadata; the HA boot-smoke lanes exercise
the integration in a running disposable HA. Neither check alone proves that a
published release works in every user's installation.

## What happens after a merge

There are two separate runs of the **Release** workflow:

| Event on `main` | Result |
| --- | --- |
| Merge a feature/fix PR | Check commit messages, then open or update the release PR. No release assets are published. |
| Merge the release PR | Check commit messages, create a draft, test the release commit, verify its exact Sonar security result, upload the ZIP/checksum, then publish. |

The prepare job handles draft creation before considering another release PR.
When a merged release PR creates a draft, PR creation is skipped; subsequent
feature/fix commits can start the next proposal after that release is published.

For example, starting from the development version `0.1.0`:

1. Merge `feat: support a new patch source`. Release Please normally proposes
   `0.2.0` in a new PR. Further feature/fix merges update that same PR.
2. Review its `CHANGELOG.md` and the version changes in `pyproject.toml`,
   `custom_components/hapatchy/manifest.json` and `.release-please-manifest.json`.
   All three versions must agree. The PR runs the normal CI checks. A manifest
   change limited to its `version` value does not require new UI evidence;
   changes to other manifest fields still do.
3. Merge that PR when the release is ready. Release Please creates a draft for
   its exact commit. The workflow runs both HA/Python test baselines and
   integration validation against that candidate.
4. If checks succeed, the publisher uploads `hapatchy-0.2.0.zip` and
   `hapatchy-0.2.0.zip.sha256`, verifies their hashes, and publishes `v0.2.0`.
   If a check or upload fails, the draft stays unpublished.

`0.1.0` is the initial development baseline, not a claim that it was released.
Review the actual proposed version before merging; do not create an old tag just
to initialize the workflow.

## Configure GitHub once

1. Use **`main`** as the default branch and enable Actions. In repository
   **Settings → Releases**, enable **release immutability** before the first
   publication. HAPatchY's v0.2.0 release is reported as immutable by GitHub;
   the workflow itself does not check the repository setting.
2. Add the repository Actions secret **`RELEASE_PLEASE_TOKEN`**: a fine-grained
   personal access token for this repository with **Contents**, **Pull requests**
   and **Issues** read/write permissions. The HA updater does not edit workflow
   files, so the token does not need **Workflows: write**. Release Please uses it to create PRs,
   labels and drafts. Keep Issues enabled. Do not commit the token.
3. Allow Actions to create PRs if required by repository/organization policy.
4. Enable **squash merging**, with the PR title as the default commit title.
   Require **Conventional Commits**, **Workflow lint**, **Secrets**,
   **HA tests required**, **HA boot required**, **Sonar required**,
   **Recent HA advisory gate**, **Integration validation**, and both **CodeQL**
   jobs in the branch rules for `main`. Select the
   actual check names shown after their first run. Avoid bypassing these rules.
   A personal GitHub Free repository cannot enforce branch protection while
   private; review every check manually in that phase, then enable the rules
   after making the repository public or upgrading the plan. On this public
   repository, `main` requires the listed checks, a PR, current base, and linear
   history, and disallows force pushes and deletion even for administrators.
   Enable the repository **Allow auto-merge** setting only after the named gates
   have appeared and passed on a PR. This does not auto-merge arbitrary PRs;
   the guarded coordinator opts in only an eligible PR at an exact head SHA.
5. Fill in the repository metadata required by HACS, including its description
   and topics. The HACS job reports missing metadata.

The separate token lets bot-created PRs trigger PR checks; most events created
with the built-in `GITHUB_TOKEN` do not trigger another workflow. Publication
uses the built-in token in the same run, so no tag-triggered workflow is needed.
See [GitHub's trigger rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).
The guarded coordinator reads the protected-branch summary through GitHub's
branch endpoint using the token's existing **Contents: read** permission. It
also requires the PR base to equal the current `main` commit. If the branch
summary omits the required checks or their enforcement, it fails closed and
leaves merging to a maintainer.

## Automatic Home Assistant baseline proposals

The scheduled [Update HA baseline](https://github.com/Ryther/hapatchy/actions/workflows/update-ha-baseline.yaml)
workflow checks PyPI for the latest stable HA release and a published pytest
plugin that pins it exactly. It resolves both recent Python locks from the
tracked `.in` inputs with pinned `uv`, then proposes a `fix(compat):` PR. It
lets the test/boot matrix read the new HA pin directly from each lock and updates its current-version references;
the minimum HA/Python lane and dated screenshot evidence remain unchanged.
Use **Run workflow → dry_run** to inspect a candidate without creating a PR.

On every PR, the advisory gate checks the exact Python requirements in
HAPatchY's `manifest.json` against active high/critical GitHub advisories and
verifies that both recent locks contain those pins. An affected HAPatchY
requirement blocks the PR even if its pin did not change. Packages that appear
only because of HA or test tooling do not enter this gate and do not block an
HA baseline update. The test matrix checks
that product requirements have no mandatory transitives outside the manifest;
if that changes, the gate must be extended to cover them. An unavailable
advisory API fails the gate. Its status is required on `main` alongside Sonar
and both HA matrix aggregates.

The [guarded coordinator](https://github.com/Ryther/hapatchy/actions/workflows/merge-ha-baseline.yaml)
runs from trusted `main` code. It can enable auto-merge only when the updater PR
is the sole unreleased change, no release PR is open, its diff is restricted to
the baseline files, its exact head has all required checks green, and the live
branch rule includes the four mandatory HA/Sonar/advisory gates. After that
merge, Release Please proposes a patch version. The coordinator opts in that
release PR only if it contains the expected version/changelog changes from that
single HA commit. It checks the PR and `main` SHAs again immediately before
opting in. Other release PRs, unrelated commits, unsupported Python, missing
plugin metadata or advisory findings require human review. **Run workflow →
dry_run** reports the current decision without changing a PR.

GitHub schedules may be delayed. Auto-merge only starts the existing exact-SHA
release pipeline; its tests, Sonar security check, draft upload and immutable
publication rules still apply. A failing pipeline leaves the draft unpublished.

## Commit messages and version ownership

[.cz.yaml](https://github.com/Ryther/hapatchy/blob/main/.cz.yaml) configures standard Conventional Commits. The
[Dev Container](https://github.com/Ryther/hapatchy/blob/main/.devcontainer/README.md) includes **Python Commitizen 4.19.0**,
the same version used by the commit-message workflow. Inside it:

```bash
.venv/bin/cz commit
# Or check a message without committing:
.venv/bin/cz check --message "fix: preserve the patch status"
```

The editor/CLI remote environment puts `.venv/bin` on PATH, so `cz` is also
available directly after reopening the container.

CI checks both the PR title and its commits. Title edits rerun the check. On
`main`, CI checks the committed history; merge commits are exempt, temporary
`fixup!`/`squash!` messages are not. A red check prevents merging only when branch
rules require it. The Release workflow also requires the commit check itself.
The commit check installs Python Commitizen and its transitive packages from an
exact version list in the workflow, using binary wheels with dependency
resolution disabled. The HA test and boot lanes use their separate exact locks;
their pytest plugin requires a source-only `mock-open` package. Those jobs have
read-only permissions and no release credentials, and their lock syntax is
checked by `tests/test_dependency_locks.py`.
CI retries each locked HA/test installation at most three times to tolerate
intermittent package-index failures; a persistent error still fails the check.

| Commit | Release Please effect |
| --- | --- |
| `fix: ...` or `perf: ...` | Patch increment |
| `feat: ...` | Minor increment |
| `feat!: ...` or a `BREAKING CHANGE:` footer | Minor increment before 1.0; major afterward |
| `docs: ...`, `ci: ...`, `build: ...`, `chore: ...` | No release by themselves |

For an explicitly approved major version such as 1.0.0, add a
`Release-As: 1.0.0` footer to a Conventional Commit on `main`. Release Please
then proposes that version in its release PR; review the three version files
and changelog before merging. Do not set a persistent `release-as` value in
`release-please-config.json` or edit the version files by hand.

**Do not run `cz bump`.** Release Please alone updates versions and the changelog.
The Commitizen configuration intentionally has no bump/version-file settings.
Only stable `vMAJOR.MINOR.PATCH` releases are supported by the publisher today.

## Which workflow does what

| File | Trigger and responsibility |
| --- | --- |
| [commits.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/commits.yaml) | PR creation/update/title edit and pushes to `main`; validate messages. Also called by Release before preparing a PR/draft. |
| [tests.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/tests.yaml) | Push/PR/manual run; lint workflow definitions, scan for secrets, test both HA/Python baselines, and exercise native managed-patch Apply/Revert and denied-target flows in disposable HA on both baselines. Release can supply an exact commit. |
| [validation.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/validation.yaml) | Push/PR/manual run; local metadata and hassfest on the checkout, plus HACS repository validation when public. Also called by Release. |
| [codeql.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/codeql.yaml) | Push/PR/weekly/manual scan of product Python and our GitHub Actions workflows with the extended security query suite; results appear under GitHub code scanning. It has no release-publishing permission. |
| [docs.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/docs.yaml) | PR and `main` build of the documentation site with strict link validation; a `main` push or manual run publishes to GitHub Pages when Pages uses GitHub Actions and `DOCS_PAGES_ENABLED=true`. |
| [release.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/release.yaml) | Push to `main` or manual run on `main`; maintain the release PR, then validate its merged candidate, require a clean exact-commit Sonar security result, and publish. |
| [update-ha-baseline.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/update-ha-baseline.yaml) | Schedule/manual run on trusted `main`; propose the newest compatible recent HA lock pair in one PR. |
| [merge-ha-baseline.yaml](https://github.com/Ryther/hapatchy/blob/main/.github/workflows/merge-ha-baseline.yaml) | Schedule/manual run on trusted `main`; recheck exact PR provenance, diff, checks and branch rule before opting eligible HA update/release PRs into auto-merge. |

[dependabot.yml](https://github.com/Ryther/hapatchy/blob/main/.github/dependabot.yml) proposes weekly updates for Actions
and a small allowlist of standalone Python tools (`commitizen` in the recent
lane, plus `mypy`, `ruff` and `supervisor` where present). The files in
`.devcontainer/` and `tests/` are fully resolved HA/test-plugin locks; individual
updates to their HA-owned packages are deliberately withheld. Regenerate a whole
lane when changing its HA release or test plugin. Dependabot neither merges PRs
nor changes the HA baseline pins automatically. The guarded updater can propose
a whole recent-lane change; newly introduced advisory findings or unrelated release work stop its
automatic merge. Other Python lock changes require manual review and both CI
lanes. Workflow container-image digests are reviewed and updated separately.

The minimum-lane `ignore` entries in [dependabot.yml](https://github.com/Ryther/hapatchy/blob/main/.github/dependabot.yml)
reflect versions pinned by HA, its optional integrations, or the HA pytest
plugin. The recent lane has an allowlist but no version-specific ignores, so
its baseline updater does not leave stale exclusions behind. Recheck the
minimum-lane exclusions when its baseline or plugin changes. The allowlists
can still suppress Dependabot security-update PRs for withheld packages:
inspect GitHub security alerts at least monthly and after baseline changes,
and change the whole compatible lock deliberately when a fix is needed.

The minimum lane's direct inputs are in `tests/requirements-ha-min.in`. In the
Dev Container, regenerate its complete test lock with:

```bash
UV_CACHE_DIR=_tmp/uv-cache .venv/bin/python -m uv pip compile \
  tests/requirements-ha-min.in -o tests/requirements-ha-min.txt \
  --python-version 3.14.7 --no-header --no-annotate
```

Update `tests/requirements-ha-min-runtime.txt` from the matching HA frontend
and optional integration manifests, then run that exact test and boot-smoke
lane. Do not change an HA-owned pin alone.

The minimum HA 2026.7.4 test plugin is `0.13.348`; it requires that exact HA
release and pins `pytest-socket==0.8.0` and `pipdeptree==2.26.1`. The recent
HA 2026.9.4 plugin is `0.13.367` with the same two test-tool pins. The minimum
HA frontend manifest requires `home-assistant-frontend==20260624.6`, and its
camera manifest requires `PyTurboJPEG==1.8.3` for boot smoke. A passing generic
test run cannot authorize changing an optional integration's pin: inspect HA's
manifest and re-resolve the relevant lane when upgrading HA.

Tests, local metadata validation and hassfest use the candidate SHA. When the
repository is public, HACS checks remote repository metadata in its event
context; it does **not** install the candidate into HA. A successful HACS job is
not proof of a successful HACS installation or upstream update.

The ZIP contains tracked integration files under `custom_components/hapatchy/`
and `LICENSE`. HACS currently reads the repository layout (`zip_release` is not
enabled); the attached ZIP is for manual installation. To build it without
publishing, run `python script/build_release.py`. The output is under `dist/`.
From that directory, use `sha256sum --check hapatchy-<version>.zip.sha256`.

## If publication fails

Open the failed **Release** run first and identify the failed job. A draft is
not a published version. Do not manually publish it to bypass a failed check.
After Release Please creates a draft, the prepare job waits briefly if GitHub's
release list has not yet caught up. It retries only that missing-draft case;
API errors, duplicate drafts and invalid release identities still stop the run.

For a transient failure, choose **Actions → Release → Run workflow**, select
`main` and set **resume_tag** to the draft tag. The workflow retests that draft's
original commit. A later push to `main` also discovers and retries an unfinished
draft before maintaining another release PR.

Matching assets from a partial upload are retained. Different bytes, an
unverifiable digest, a tag pointing elsewhere or an already published release
stop the helper; it never overwrites them. If several drafts exist, choose one
explicitly with `resume_tag`.

If the candidate code is broken, retrying after merging a fix does not help: the
draft still names the old commit. Stop retrying that candidate and resolve the
failed release state before preparing a corrected version. Do not move a
published tag. A draft recovery also consumes that workflow run; another push
or manual run is needed to resume release PR maintenance.
