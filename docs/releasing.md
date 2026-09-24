# Release HAPatchY

Releases use a pull request. **Merging a feature does not publish a release;
merging the release PR authorizes publication after its checks pass.**

Release Please proposes the version and changelog. Commitizen checks commit
messages. The publishing helper builds the integration archive, uploads it to a
GitHub draft and publishes that draft only after verification.

This automation has been tested locally, including failure and retry cases. It
has **not completed a real GitHub release run**. The GitHub configuration needed
for publication is described below. User installation instructions are in
[installation.md](installation.md).

During a private release rehearsal, the HACS Action is skipped: [HACS cannot
use private GitHub repositories](https://hacs.dev/docs/faq/private_repositories/).
The workflow still checks the local HACS metadata and runs hassfest, but those
checks do not prove that HACS can install the integration. After making the
repository public, run Integration validation again and require its HACS job to
pass before claiming HACS compatibility.

## What happens after a merge

There are two separate runs of the **Release** workflow:

| Event on `main` | Result |
| --- | --- |
| Merge a feature/fix PR | Check commit messages, then open or update the release PR. No release assets are published. |
| Merge the release PR | Check commit messages, create a draft, test the release commit, upload the ZIP/checksum, then publish. |

For example, starting from the development version `0.1.0`:

1. Merge `feat: support a new patch source`. Release Please normally proposes
   `0.2.0` in a new PR. Further feature/fix merges update that same PR.
2. Review its `CHANGELOG.md` and the version changes in `pyproject.toml`,
   `custom_components/hapatchy/manifest.json` and `.release-please-manifest.json`.
   All three versions must agree. The PR runs the normal CI checks.
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
   publication. The draft/upload/publish sequence supports it, but the current
   workflow does not check whether that GitHub setting is enabled.
2. Add the repository Actions secret **`RELEASE_PLEASE_TOKEN`**: a fine-grained
   personal access token for this repository with **Contents**, **Pull requests**
   and **Issues** read/write permissions. Release Please uses it to create PRs,
   labels and drafts. Keep Issues enabled. Do not commit the token.
3. Allow Actions to create PRs if required by repository/organization policy.
4. Enable **squash merging**, with the PR title as the default commit title.
   Require the **Conventional Commits**, **Workflow lint**, **Secrets**, **Tests**
   matrix, both **HA boot smoke** matrix jobs and **Integration validation**
   checks in the branch rules for `main`. Select the
   actual check names shown after their first run. Avoid bypassing these rules.
   A personal GitHub Free repository cannot enforce branch protection while
   private; review every check manually in that phase, then enable the rules
   after making the repository public or upgrading the plan.
5. Fill in the repository metadata required by HACS, including its description
   and topics. The HACS job reports missing metadata.

The separate token lets bot-created PRs trigger PR checks; most events created
with the built-in `GITHUB_TOKEN` do not trigger another workflow. Publication
uses the built-in token in the same run, so no tag-triggered workflow is needed.
See [GitHub's trigger rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

## Commit messages and version ownership

[.cz.yaml](../.cz.yaml) configures standard Conventional Commits. The
[Dev Container](../.devcontainer/README.md) includes **Python Commitizen 4.19.0**,
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

| Commit | Release Please effect |
| --- | --- |
| `fix: ...` or `perf: ...` | Patch increment |
| `feat: ...` | Minor increment |
| `feat!: ...` or a `BREAKING CHANGE:` footer | Minor increment before 1.0; major afterward |
| `docs: ...`, `ci: ...`, `build: ...`, `chore: ...` | No release by themselves |

**Do not run `cz bump`.** Release Please alone updates versions and the changelog.
The Commitizen configuration intentionally has no bump/version-file settings.
Only stable `vMAJOR.MINOR.PATCH` releases are supported by the publisher today.

## Which workflow does what

| File | Trigger and responsibility |
| --- | --- |
| [commits.yaml](../.github/workflows/commits.yaml) | PR creation/update/title edit and pushes to `main`; validate messages. Also called by Release before preparing a PR/draft. |
| [tests.yaml](../.github/workflows/tests.yaml) | Push/PR/manual run; lint workflow definitions, scan for secrets, test both HA/Python baselines, and exercise native managed-patch Apply/Revert and denied-target flows in disposable HA on both baselines. Release can supply an exact commit. |
| [validation.yaml](../.github/workflows/validation.yaml) | Push/PR/manual run; local metadata and hassfest on the checkout, plus HACS repository validation when public. Also called by Release. |
| [release.yaml](../.github/workflows/release.yaml) | Push to `main` or manual run on `main`; maintain the release PR, then validate and publish its merged candidate. |

[dependabot.yml](../.github/dependabot.yml) proposes weekly updates for Actions
and Python requirements in `.devcontainer/` and `tests/`. Python lock changes
require manual review and both CI lanes; Dependabot neither merges PRs nor
changes the HA baseline pins automatically. Workflow container-image digests
are reviewed and updated separately.

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
