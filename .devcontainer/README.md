# Development environment

This environment starts a disposable development Home Assistant alongside the
editor. It does not connect to an existing HA installation. Open the repository
with VS Code Dev Containers and select **Reopen in Container**. Alternatively,
with a Dev Containers CLI already installed:

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . bash .devcontainer/scripts/status-ha.sh
```

Use VS Code's forwarded port 8123 to open HA. Forwarding binds locally; choose a
different local port if 8123 is occupied. CLI users must arrange local forwarding
separately. No host network, privileged container, Docker socket, home directory
or production configuration mount is required. The workspace user is `vscode`,
with UID adjustment enabled for bind-mount ownership.

## Processes and commands

The entrypoint prepares `.venv` (tools and Supervisor) and `.venv-ha` (HA runtime)
before starting Supervisor. HA autostarts once per container start. Editor
attaches and repeated bootstrap calls do not start additional HA processes.
Explicitly stopping HA leaves it stopped until a start command or container
restart. Crashes remain visible; there is no automatic restart loop.

Run these commands **inside the container**, from the workspace root:

```bash
bash .devcontainer/scripts/bootstrap.sh
bash .devcontainer/scripts/start-ha.sh
bash .devcontainer/scripts/stop-ha.sh
bash .devcontainer/scripts/restart-ha.sh
bash .devcontainer/scripts/status-ha.sh
bash .devcontainer/scripts/wait-ha.sh
tail -n 100 -f .devcontainer/state/ha/ha.log
python3 -m unittest discover -s .devcontainer/tests -v
```

The same operations are available as VS Code tasks. Status exits nonzero unless
the managed HA process owns port 8123 and responds over HTTP. Initial dependency
setup has a bounded 30-minute wait; after Supervisor starts, HTTP readiness has
a separate 120-second deadline. Download or startup failures remain errors.
Inspect container logs for bootstrap failures and `ha.log` for HA failures.
Container shutdown gives Supervisor 40 seconds to drain HA (HA's stop grace is
30 seconds). Only an owner-protected Unix socket exposes process control.

## State and dependencies

HA configuration lives in `.devcontainer/state/ha`. Bootstrap creates
`configuration.yaml` only when absent. Rebuilds preserve the entire state
directory, including onboarding, credentials and backups. Never commit it or
copy household credentials into fixtures. Remove state only as an intentional
manual reset after preserving anything you need.

When `custom_components/hapatchy` exists, cold bootstrap links it into this HA
configuration. A conflicting path is rejected and preserved. Restart the
container after first creating the source tree. Ordinary Python integration
changes generally require an HA restart.

Both requirements files contain complete resolved pins. Markers include their
SHA-256, Python version/implementation/cache tag, platform, architecture and image
identity. Changed inputs recreate only the affected development venv at cold
bootstrap. Existing HA configuration is preserved. Missing/incomplete markers
never certify successful setup. Package mismatches fail visibly.

Do not run `pip install` into either environment while Supervisor is running.
Resolve dependency changes separately, update the owned requirements file and
restart the container. An explicit bootstrap during service operation verifies
the current installation and refuses changed inputs. Concurrent bootstrap calls
serialize. Changes to the Dockerfile require a container rebuild. The base image
is digest-pinned; Debian packages are installed from its configured repositories
at build time, so this is not a fully hermetic OS package build.

## Baseline and handoff

The initial baseline uses Linux/amd64 and
`python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56`.
The image records the Dockerfile SHA-256 and base reference in
`/usr/local/share/hapatchy-image.json`. Python is CPython 3.14.7 (`cpython-314`),
HA 2026.9.0, frontend 20260826.4, Supervisor 4.3.0, pytest 9.1.1,
Ruff 0.16.8 and mypy 2.3.1. These are development pins, not product support claims.

Authored configuration is in `Dockerfile`, `devcontainer.json`,
`configuration.yaml`, `supervisord.conf`, `requirements-ha.txt`,
`requirements-tools.txt`, `scripts/`, `tests/` and `../.vscode/tasks.json`.
Technical acceptance logs and local UI captures remain in ignored planning
storage. The integration phase owns its independent Python 3.13 test environment
and may amend the recent tools lock before restarting the container. Bootstrap
never installs a minimum-lane test lock into these recent environments.

Environment checks are separate from integration tests. A successful container
build or onboarding screen does not validate patch behavior or HACS installation.

### Environment acceptance — 2026-09-23

The initial Linux/amd64 build and CLI attach passed as a non-root user. Both
resolved environments passed `pip check`. Automatic startup displayed the real
HA onboarding screen (a loopback-only acceptance mapping used local port 18123).
Stop/start/restart, duplicate start, crash visibility/manual recovery, graceful
container stop, replacement of the container and preserved state all passed.
Concurrent and repeated bootstrap preserved configuration; changed live pins
were rejected. An unavailable package with networking disabled failed without a
success marker. Thirteen environment tests cover source links, preservation,
PID reuse and lock/interpreter/platform/image invalidation. Whitelist checks and
README links passed. These cover the environment gates DC0–DC4/DC-T01–DC-T15;
no product behavior or Python 3.13 support is certified by this receipt.

Initial lock SHA-256 values (later tool-lock changes require fresh checks):

- HA: `f0ed2f0257b23eacf0067e9f4be2cd8f8ea35e4f7f3712a8b84ddbf5096f4f3f`
- Tools: `ad4096960fac060a91f4dbf3c760c89620324ef67d537e851fd931ad5adb4a80`

Reproduce the source-level environment checks with the unittest command above,
then exercise the lifecycle commands in a disposable container. Detailed build,
resolver, lifecycle, fault-injection and painted UI evidence is retained locally;
it is intentionally excluded from the public source tree.

### Integration test environment amendment

The recent tools environment now includes HA 2026.9.0 and
`pytest-homeassistant-custom-component==0.13.363`; its compatible pytest is 9.0.3.
At P0 the independent browser runtime remained unchanged (see the subsequent UI amendment below). The amended lock was resolved,
installed at cold container restart and verified with `pip check` and API imports.
The separate minimum test lock uses HA 2025.3.0/plugin 0.13.221 on Python 3.13.12.
Run product tests with `.venv/bin/python -m pytest -q`; they create temporary HA
objects and do not use the browser instance. This preliminary dependency check
is not a completed product compatibility certification.

### Authenticated UI runtime amendment

Product acceptance also exercises the authenticated frontend and native service
catalogue. In HA2026.9.0, serializing that catalogue imports base entity domains
(including conversation, camera/stream and TTS) even in this minimal configuration.
The HA lock therefore includes their pinned import dependencies and the image
includes `libturbojpeg0` and `ffmpeg`. Additional pins cover HA's base infrared/radio-frequency domains and the Supervisor client imported by
analytics after onboarding. No household devices are configured.
Testing only the unauthenticated onboarding page did not expose these imports.

The product requires patch-ng1.19.1 and Watchdog6.0.0. These are installed into
the separate HA runtime as well as the test environment. Every dependency/image
amendment uses cold bootstrap; state and onboarding are preserved. The runtime
still uses `--skip-pip`: no live opportunistic installation is used to hide gaps.
The final lock/image identities are:

Run `.venv/bin/mypy --python-version 3.14` for the recent environment; mypy must
parse HA's own 3.14 source syntax. The minimum lane and Ruff continue to target
Python3.13 and run the same integration code. This does not raise the product
minimum to Python3.14.

- `requirements-ha.txt` SHA-256: `7c6e1f4d72cb8eb3ba70d263de84730eef756b05821a209a9a0ae286e37ab14e`
- `requirements-tools.txt` SHA-256: `60abfa5ea7620fe58eb32ca5c04d77ce2527aff22cee8cecf8d55040d6401f56`
- `Dockerfile` SHA-256: `b3c521e6e5ced73824a3a88adfddb206de3f97b29702279a7508d82ad8b6ba62`

Final local acceptance (2026-09-23): the amended image rebuilt successfully,
non-root cold bootstrap installed both full locks and `pip check` passed in each.
A repeat bootstrap verified the environments without restarting managed services.
HA started without errors, retained onboarding/configuration and the example
patch, served the authenticated service catalogue and native options, and rendered
the integration page in Chromium. The README screenshot is from this isolated
manual development installation. HACS installation/release acceptance is pending.
