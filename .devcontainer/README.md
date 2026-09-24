# Develop in the Dev Container

The container supplies the project's development tools and starts its own Home
Assistant. It does not need or connect to your household HA installation.
For contribution and review requirements, read [CONTRIBUTING.md](../CONTRIBUTING.md).

## Open the environment

On the host, install Docker and VS Code with the Dev Containers extension.
Open this repository and run **Dev Containers: Reopen in Container**. The initial
start installs the pinned Python environments before starting HA; wait for the
post-start readiness check to finish.

Open forwarded port **8123** to complete HA onboarding with disposable credentials.
Forwarding binds locally. If that host port is occupied, select another local port
in VS Code's Ports panel. No privileged container, Docker socket, host networking
or household configuration mount is required.

With a Dev Containers CLI already installed on the host, the equivalent commands
are:

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . bash .devcontainer/scripts/status-ha.sh
```

CLI users must arrange local port forwarding separately. The workspace user is
`vscode`; Dev Containers adjusts its UID for bind-mount ownership.

**When Dockerfile, tool locks or Dev Container configuration change, use
Rebuild and Reopen in Container.** Reopening also loads the terminal PATH setting.
HA state survives a rebuild. Do not repair a stale environment by installing
packages into the running container's managed virtual environments.

## Included tools

| Tool | Purpose |
| --- | --- |
| Git, Bash and native build dependencies | Source control, scripts and Python package installation |
| Python Commitizen **4.19.0** (`cz`) | Guided Conventional Commits and message validation; same version as commit-message CI |
| pytest **9.0.3** and HA pytest plugin **0.13.363** | Isolated integration/unit tests |
| Ruff **0.16.8** | Python linting and formatting |
| mypy **2.3.1** | Type checking |
| Supervisor **4.3.0** | Manage the separate browser HA process |
| Python standard library | Version validation and release ZIP/checksum generation |

Commitizen is the Python package from `commitizen-tools`; no npm Commitizen
installation is needed. Its complete resolved dependencies are pinned in
[requirements-tools.txt](requirements-tools.txt). Release Please executes as a
GitHub Action; it does not need a local daemon. The publishing helper uses the
GitHub CLI on GitHub's runner; local development checks never require publication
credentials or the `gh` executable.

The editor/Dev Containers CLI remote PATH starts with `.venv/bin`. Run `cz version`
or `.venv/bin/cz version` to inspect the installed version. Explicit `.venv/bin/`
commands also work in a plain `docker exec`, which does not apply editor settings.

## Run the checks

From the repository root **inside the container**:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests .devcontainer/scripts .devcontainer/tests script
.venv/bin/mypy --python-version 3.14
.venv/bin/python -m unittest discover -s .devcontainer/tests -v
.venv/bin/cz check --rev-range HEAD
.venv/bin/python script/build_release.py
```

Use `.venv/bin/cz commit` to write a commit interactively. Release Please owns
versions and changelog updates, so **do not run `cz bump`**.

VS Code's **Tasks: Run Task** offers each check, **Checks: all** (sequential) and
**Commit: guided message**, as well as the HA lifecycle tasks below.

Tests create temporary HA objects/configuration directories. They do not make
requests to the browser HA or to a household installation. The container runs
the recent baseline, **HA 2026.9.0 / Python 3.14.7**. CI also tests
**HA 2025.3.0 / Python 3.13.12** with its separate lock. Passing this container's
checks is not proof that a minimum-lane-specific failure is fixed.

## Investigate a PR failure

**Reproducing problems with external PRs in this Dev Container is mandatory.**
Check out the exact PR commit in a disposable checkout, inspect its changes,
rebuild/reopen, verify bootstrap and rerun the failing command. Record the commit,
versions and result in the review. This separates dependency/tooling mismatches
from code defects. The full policy and minimum-lane caveat are in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Control development Home Assistant

Run these commands inside the container:

```bash
bash .devcontainer/scripts/bootstrap.sh
bash .devcontainer/scripts/status-ha.sh
bash .devcontainer/scripts/stop-ha.sh
bash .devcontainer/scripts/start-ha.sh
bash .devcontainer/scripts/restart-ha.sh
bash .devcontainer/scripts/wait-ha.sh
tail -n 100 -f .devcontainer/state/ha/ha.log
```

HA autostarts once per container start. Editor attaches and repeated bootstrap do
not start duplicates. An explicitly stopped or crashed HA stays stopped until a
start command or container restart. Status succeeds only when the managed process
owns port 8123 and responds over HTTP. Startup preparation has a 30-minute bound;
HA readiness then has its own 120-second deadline. Failures remain visible in
container logs and `.devcontainer/state/ha/ha.log`.

For a separate, repeatable startup check, run
`.venv-ha/bin/python script/smoke_ha.py`. It copies the integration into a
temporary configuration, starts another HA process on a free local port,
checks HAPatchY setup and HTTP readiness, then creates a managed patch through
HA's API and verifies Apply, Revert and an unlisted-target refusal against file
bytes. It stops that process without modifying the managed HA instance or its
configuration. CI runs the same flow on the minimum HA/Python pair as well.

## State and dependency ownership

- `.venv` contains development/test tools and Supervisor.
- `.venv-ha` contains the browser HA runtime, started with `--skip-pip`.
- `.devcontainer/state/ha` contains configuration, onboarding and backups. Bootstrap
  creates `configuration.yaml` only if absent and links the integration source
  into `custom_components`. Conflicting files/links are preserved and rejected.
- A cold start rebuilds a venv when its lock, interpreter, platform, architecture
  or image identity changes. It verifies installed pins and `pip check` before
  writing a success marker. A live bootstrap checks and refuses changed inputs;
  it never reinstalls packages underneath HA or Supervisor.

Both locks include complete resolved dependency pins. To add a dependency, resolve
it separately, preserve existing pins unless an upgrade is intended, update the
owned lock and rebuild/reopen. Never install the minimum CI lock over these recent
environments. Python integration changes generally need an HA restart.

The base Python image is pinned by digest; OS packages are installed from Debian
repositories during build. This is not a fully hermetic OS build. HA stops with
its normal grace period when the container stops. An owner-protected Unix socket
controls Supervisor; there is no public process-control endpoint.

State, virtual environments, caches and `dist/` stay ignored. Back up any disposable
state you want to retain before intentionally resetting it. A successful container
startup does not certify HACS installation; actual product UI evidence and its
limits are recorded in [verification.md](../docs/verification.md).
