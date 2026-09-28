# Contributing to HAPatchY

AI contributors must read the root [AGENTS.md](AGENTS.md). Security-sensitive
changes must preserve the path and authorization checks covered by the tests.

Use the [Dev Container](.devcontainer/README.md) for a reproducible development
environment. It starts an isolated Home Assistant and supplies the Python test,
lint, type-checking and commit-message tools. Household HA is not needed.

## Required when investigating a pull request

**If a pull request from another contributor fails, behaves unexpectedly, or
cannot be reproduced, the reviewer must reproduce the problem in this
repository's Dev Container before attributing it to the contributor's code.**
This also applies when the failure appears to be a tooling or dependency issue.

1. Inspect the changes before running them, then check out the PR's exact commit
   in a disposable checkout without household configuration or credentials.
2. Use **Dev Containers: Rebuild and Reopen in Container** to load that checkout's
   Dockerfile, configuration and pinned tools. Do not reuse host-installed tools
   or install packages over the running HA environment.
3. Wait for HA readiness and run `bash .devcontainer/scripts/bootstrap.sh`. A
   version/marker mismatch is an environment failure to resolve before drawing
   conclusions about the patch.
4. Rerun the reported failing command and the relevant checks below. Record the
   commit SHA, HA/Python/tool versions, command and actual result in the PR review.
5. If the failure cannot be reproduced, report that result and compare the failing
   environment with the container/CI versions. Do not treat a host-only failure
   as sufficient evidence that the contribution is broken.

The container uses the **recent** HA/Python baseline. A failure specific to the
minimum baseline still needs that exact CI lane; success on the recent baseline
alone does not dismiss it. Both lanes and their locks are in
[tests.yaml](.github/workflows/tests.yaml). Never install the minimum lock into
one of the running container's virtual environments.
CI runs the native API/file-byte smoke on both HA/Python pairs; the local smoke
command below exercises the recent pair only.

This is a contributor/reviewer requirement. GitHub checks validate the submitted
code and messages; they cannot prove which local environment a reviewer used.

## Before submitting

From the repository root inside the container:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests .devcontainer/scripts .devcontainer/tests script
.venv/bin/mypy --python-version 3.14
.venv/bin/python -m unittest discover -s .devcontainer/tests -v
.venv/bin/cz check --rev-range HEAD
.venv/bin/python script/build_release.py
.venv-ha/bin/python script/smoke_ha.py
```

VS Code's **Tasks: Run Task → Checks: all** runs these checks in order. Individual
checks and **Commit: guided message** are also available. HA lifecycle tasks
start, stop or inspect the container's HA only.

Use `.venv/bin/cz commit` for the Python Commitizen prompt, or write a Conventional
Commit message yourself. Check the PR title with
`.venv/bin/cz check --message "fix: describe the change" --allowed-prefixes`.
CI validates both the title and commits. Release Please owns version/changelog
updates: do not run `cz bump` or independently bump the integration manifest.
Dependabot proposes updates for Actions and the two Python dependency locations.
Review every proposed version and its lock changes manually, then require the
normal checks; no dependency PR is merged automatically. HA baseline versions
remain operator-owned rather than being raised by Dependabot. Container image
digests used in workflows remain a separate manual update.

For user-facing changes, first exercise the documented operation in disposable
HA, capture the actual UI, and record the checks and their limits in the PR.
Use synthetic examples; keep credentials, diagnostics and HA state private.
The repository uses a default-deny `.gitignore`: add narrow exceptions for new
source/docs/screenshots and check them before staging. Do not use `git add -f`.

## Documentation

Start at the [documentation home](docs/index.md). Keep the guides in Markdown so
they work both on GitHub and in the generated site. The site navigation is in
`mkdocs.yml`; update it when adding a page. Review the documentation impact and
reader journey rules in [AGENTS.md](AGENTS.md) before changing product behavior.

To preview the site in the Dev Container, use a separate disposable environment
so the HA and test environments keep their locked dependencies:

```bash
python3 -m venv /tmp/hapatchy-docs-venv
/tmp/hapatchy-docs-venv/bin/python -m pip install 'mkdocs-material==9.7.7'
/tmp/hapatchy-docs-venv/bin/python -m mkdocs build --strict
/tmp/hapatchy-docs-venv/bin/python -m mkdocs serve
```

Open the forwarded preview port, check desktop and narrow-screen navigation,
and follow the links for the changed task. CI builds every PR; the site is
published from `main` only when GitHub Pages is configured for GitHub Actions.

## Optional Sonar analysis

Run SonarScanner from the repository root against your own SonarQube server.
The tracked `sonar-project.properties` defines sources, tests and targeted
rule/file exclusions; those exclusions are sent with each analysis, so they do
not depend on retained server settings. They preserve HA-required hook signatures,
the immutable Docker image pin, the credential-free coverage job's exact HA
lock/source-only package exception and a report-content false positive in the
fixed-path exporter. Other rules continue checking those files.
Review exclusions as described in [AGENTS.md](AGENTS.md).

Set `SONAR_HOST_URL` to your server and `SONAR_TOKEN` to a project analysis token
in your shell or secret store. Never commit either credentials or generated
scanner reports. Then run an installed SonarScanner CLI:

```bash
sonar-scanner -Dsonar.scm.revision="$(git rev-parse HEAD)"
# For a local Community server with a different project key, also pass:
# -Dsonar.projectKey=your-local-project-key
```

For coverage, first generate a fresh coverage.py XML report from the current
checkout's test runs, then pass its path with
`-Dsonar.python.coverage.reportPaths=/path/to/coverage.xml`. A stale report can
misrepresent coverage or refer to lines that no longer exist. Server quality
gates and quality profiles are separate server configuration: scanner exclusions
do not recreate them. Record their names, analyzer version, exact commit and
actual results when reporting an analysis. Sonar does not replace both HA test
lanes, the native smoke tests or security review.

## Sonar checks on pull requests

`Sonar quality` runs coverage without secrets on every PR. On `main` and PRs
originating in this repository, a separate scanner job submits to SonarQube
Cloud with the repository `SONAR_TOKEN`. It only reads the proposed source; it
does not run project code or install PR dependencies with that token. A PR from
a fork or Dependabot uses a disposable Sonar Community Build and compares the
base and proposed revisions without a persistent credential. This fallback
checks introduced findings but is not a SonarQube Cloud PR quality gate. Both
scanners use settings from the PR base revision once this workflow is on `main`,
so a PR cannot relax its own source scope or rule exclusions; scanner-setting
changes take effect after merge. This initial setup PR uses its new settings.

Each scan publishes complete JSON findings and a readable report as a GitHub
Actions artifact linked from the PR's checks. Artifacts expire after 90 days.
Sonar's own PR decoration remains the authoritative Cloud result where present.
The baseline and candidate reports distinguish existing findings from new ones;
reviewers should inspect the linked report rather than treating a green check as
proof of safety.

The Cloud project uses CI-based analysis. Keep automatic analysis disabled under
SonarQube Cloud **Administration → Analysis Method**; the two methods cannot
run against the same project at once. When setting up the workflow, scan `main`
first so PRs have a baseline. Only require the new check in branch protection
after the first complete run and a real fork PR check.
