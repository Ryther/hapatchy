# Contributing to HAPatchY

AI contributors must read the root [AGENTS.md](AGENTS.md). Security-sensitive
changes must account for the [security review](docs/security-review.md).

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
```

VS Code's **Tasks: Run Task → Checks: all** runs these checks in order. Individual
checks and **Commit: guided message** are also available. HA lifecycle tasks
start, stop or inspect the container's HA only.

Use `.venv/bin/cz commit` for the Python Commitizen prompt, or write a Conventional
Commit message yourself. Check the PR title with
`.venv/bin/cz check --message "fix: describe the change" --allowed-prefixes`.
CI validates both the title and commits. Release Please owns version/changelog
updates: do not run `cz bump` or independently bump the integration manifest.

For user-facing changes, first exercise the documented operation in disposable
HA and capture the actual UI. See [documentation verification](docs/verification.md).
Use synthetic examples; keep credentials, diagnostics and HA state private.
The repository uses a default-deny `.gitignore`: add narrow exceptions for new
source/docs/screenshots and check them before staging. Do not use `git add -f`.
