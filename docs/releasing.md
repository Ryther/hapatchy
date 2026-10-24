# Release HAPatchY

[Documentation home](index.md) · [Contribution rules](https://github.com/Ryther/hapatchy/blob/main/CONTRIBUTING.md)

Release Please owns the version and changelog. Merging a product PR proposes a
release; merging the release PR authorizes publication after validation. The
publisher creates a draft, checks its exact commit, uploads the ZIP/checksum and
publishes only after those checks pass. A draft is not an available update.

<span id="what-happens-after-a-merge"></span>

## Review and publish a release

1. Merge the tested feature/fix PR into `main` using its Conventional Commit
   title. The Release workflow opens or updates the version PR.
2. Inspect the proposed changelog and these three version files:
   `pyproject.toml`, `custom_components/hapatchy/manifest.json` and
   `.release-please-manifest.json`. Their versions must agree. Check any required
   user migration in the README and installation guide before a breaking release.
3. Verify the release PR's current head and required checks. A version-only
   manifest change does not require new UI evidence; other product changes do.
4. Merge the release PR when publication is authorized. The workflow creates a
   draft for that commit and runs both HA test/boot lanes, metadata validation,
   hassfest, HACS validation for this public repository, and the product advisory
   gate. HACS validation checks repository information; it does not install the
   candidate into HA.
5. Wait for **Exact release security** and **publish**. Sonar's latest `main`
   analysis must match the exact release SHA, pass its gate, and contain no open
   product security issues or unreviewed hotspots. A stale/missing scan or failed
   test leaves the draft unpublished. A green PR analysis alone is insufficient.
6. Inspect the public release, tag, ZIP and checksum. Verify that the tag names
   the validated commit and that the downloaded archive contains the matching
   integration version. A newly published GitHub release can appear in HACS after
   its information refresh; see [updating HAPatchY](installation.md#updates).

Only stable `vMAJOR.MINOR.PATCH` releases are supported by the publisher. Do not
move a published tag or overwrite an immutable release.

<span id="commit-messages-and-version-ownership"></span>

## Version proposals and commit messages

| Commit | Release Please effect |
| --- | --- |
| `fix: ...` or `perf: ...` | Patch increment |
| `feat: ...` | Minor increment |
| `feat!: ...` or a `BREAKING CHANGE:` footer | Major increment after 1.0; minor before 1.0 |
| `docs: ...`, `ci: ...`, `build: ...`, `chore: ...` | No release by themselves |

Use Python Commitizen (`.venv/bin/cz commit`) or write a Conventional Commit
message directly. Check the actual base-to-head range with
`.venv/bin/cz check --rev-range BASE..HEAD`. CI validates the PR title and commits;
Release also runs that check. Do not leave `fixup!` or `squash!` messages in the
final range.

**Do not run `cz bump` or manually change a feature PR's version files.** Release
Please proposes versions. For an explicitly approved version override, use a
`Release-As:` footer containing that approved version in a Conventional Commit;
review the generated proposal. Do not leave a persistent `release-as` setting.

<span id="configure-github-once"></span>

## Repository setup and required checks

These are the intended settings. Inspect the live GitHub rules and a current PR's
check runs before changing protection; tracked workflows do not certify remote
settings.

- Use `main`, enable Actions and Issues, and enable release immutability under
  **Settings → Releases** before publishing.
- Configure `RELEASE_PLEASE_TOKEN` as a repository Actions secret: a fine-grained
  personal token with Contents, Pull requests and Issues read/write access to
  this repository. It lets bot-created PRs trigger CI. The current HA updater does
  not change workflow files, so it does not require Workflows write permission.
  Do not commit tokens. Allow Actions to create PRs where repository policy
  requires it.
- Enable squash merging with the PR title as the commit title. Require a current
  base, linear history and a PR; disallow force pushes/deletion and administrator
  bypasses on `main`.
- Require the actual check contexts: **Conventional Commits**, **Workflow lint**,
  **Secrets**, **UX evidence gate**, **HA tests required**, **HA boot required**, **Sonar required**,
  **Recent HA advisory gate**, **metadata**, **hassfest**, **hacs**,
  **CodeQL (python)** and **CodeQL (actions)**. `Integration validation` is the
  workflow title, not a single aggregate check. Matrix version labels are not
  stable substitutes for the HA aggregate names.
- Keep repository description/topics valid for HACS. Enable **Allow auto-merge**
  only with the named gates enforced. This setting alone does not enable
  automatic merging on arbitrary PRs.

The separate release token creates proposals/drafts; publication uses the
workflow's built-in token. Preserve the separation between untrusted PR execution
and credential-bearing publishing jobs. See
[GitHub's workflow trigger rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

<span id="automatic-home-assistant-baseline-proposals"></span>

## Automatic Home Assistant baseline updates

[Update HA baseline](https://github.com/Ryther/hapatchy/actions/workflows/update-ha-baseline.yaml)
looks for the latest stable HA release with an exactly matching published pytest
plugin. It verifies the candidate wheel's size/hash, reads HA-owned dependency
pins and resolves both recent locks together from the tracked inputs. Missing or
conflicting required pins stop the proposal. HAPatchY and independent-tool pins
remain explicit; the minimum lane is unchanged.

The current recent baseline is **HA 2026.10.2**. Read the matching pytest plugin
and resolver versions from `.devcontainer/requirements-tools.txt`, rather than
copying them from prose. The minimum lane's inputs and test/runtime locks are in
`tests/requirements-ha-min*`. Optional boot-smoke additions must match that HA
release's frontend and integration manifests. Follow the
[Dev Container resolver procedure](https://github.com/Ryther/hapatchy/blob/main/.devcontainer/README.md#run-the-checks)
for recent candidate locks. Never update an HA-owned pin independently or overlay
one lane's requirements onto another.

Run the updater with **Run workflow → dry_run** first. Proposals use
`automation/ha-baseline/<HA version>` and only one may be open at a time. A branch
for the candidate without its PR stops the updater for review; merged branches
are deleted by GitHub's repository setting.

[Merge HA baseline](https://github.com/Ryther/hapatchy/actions/workflows/merge-ha-baseline.yaml)
uses trusted `main` code to enable auto-merge only when the proposal is the sole
unreleased change, no release PR is already open, the allowed diff and exact
head/base match, and all live required checks pass. It then handles only the
isolated Release Please patch proposal produced by that update. Other unreleased
commits, advisory findings, altered SHAs or missing enforcement require human
review. Use its dry-run mode before changing coordinator rules. Never broaden
allowed paths or provenance checks merely to pass a proposal.

The product advisory gate checks the exact manifest requirements and their pins
in the recent locks on every PR. High/critical product advisories block even if
the pin is unchanged; an unavailable advisory API also blocks. HA-only and
tooling-only lock packages are outside that product gate. Tests ensure no
mandatory product transitive is left unscanned. Sonar dependency analysis is
separately disabled so it cannot treat HA test locks as distributed product code.

Dependabot proposes individual updates only for allowed standalone tools and
Actions. Review the whole withheld HA graph and minimum-lane exclusions at least
monthly, after baseline changes and when an advisory affects it. Regenerate a
compatible lane for an HA-owned dependency fix. Do not treat an exclusion as
permanent upstream policy. All ordinary dependency PRs still require manual
review; workflow image digests are maintained separately.

GitHub schedules can be delayed. Auto-merge starts the existing exact-commit
release pipeline; it does not bypass tests, Sonar or publication verification.

<span id="which-workflow-does-what"></span>

## Workflows and artifacts

| Workflow | Responsibility |
| --- | --- |
| `commits.yaml` | Validate Conventional Commit titles/messages; also called by Release. |
| `tests.yaml` | Workflow lint, secrets, both HA test/boot lanes and the product advisory gate; accepts an exact release revision. |
| `validation.yaml` | Local metadata, pinned hassfest and public-repository HACS validation. |
| `codeql.yaml` | Product Python and separate GitHub Actions security scans. |
| `sonar.yaml` | Product coverage/quality analysis; manual exact-draft scan recovery. |
| `docs.yaml` | Strict site build on PR/main; Pages publication when configured and `DOCS_PAGES_ENABLED=true`. |
| `release.yaml` | Propose versions, validate the merged candidate and publish verified artifacts. |
| `update-ha-baseline.yaml`, `merge-ha-baseline.yaml` | Propose and conditionally merge an isolated HA baseline and its patch release. |

Workflow files are in [`.github/workflows`](https://github.com/Ryther/hapatchy/tree/main/.github/workflows).
For Sonar's trusted/untrusted scan separation and report artifacts, follow
[the contributor guide](https://github.com/Ryther/hapatchy/blob/main/CONTRIBUTING.md#sonar-checks-on-pull-requests).
Secret scanning covers tracked files/history even though product quality metrics
exclude test and CI code. Locked test installation retries the same lock at most
three times; it preserves a final package-installation failure.

Build locally with `.venv/bin/python script/build_release.py`. The `dist/` ZIP
contains tracked `custom_components/hapatchy/` files and `LICENSE`; the checksum
is beside it. In `dist/`, run `sha256sum --check hapatchy-<version>.zip.sha256`
with the actual filename. HACS uses the repository layout (`zip_release` is not
enabled); the attached ZIP is for manual installation.

## If publication fails

1. Open the failed **Release** run and identify the failed job. Do not publish its
   draft manually to bypass a gate.
2. For a transient failure, run **Actions → Release → Run workflow** on `main`
   with **resume_tag** set to the existing draft tag. It retests that draft's
   original commit. A later main push also discovers an unfinished draft before
   proposing another version. Draft-list visibility has a bounded retry; other
   API/identity errors remain failures.
3. For a missing exact Sonar result, first run **Actions → Sonar quality → Run
   workflow** on `main` with **release_tag** set to that draft tag. It must point
   to an ancestor of `main` and an existing draft. Wait for **Sonar required**,
   then resume Release with the same tag. A PR scan or newer-main result cannot
   replace the exact candidate scan.
4. Matching partially uploaded assets are retained. Different bytes, invalid
   digests, a mismatched tag or an already published release stop publication;
   the helper does not overwrite them. Select **resume_tag** explicitly when
   more than one draft exists.
5. If candidate code is broken, merging a later fix does not repair the old
   draft. Resolve that failed draft state before preparing a corrected version.
   Never move a published tag. Recovering a draft consumes that workflow run;
   a separate push/manual run resumes version-PR maintenance afterward.
