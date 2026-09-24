# Architecture

HAPatchY separates pure patch decisions from filesystem mutation and Home
Assistant lifecycle. No patch is executed as a shell command or Python program.

| Boundary | Owned responsibility | Public seam |
| --- | --- | --- |
| `models`, `const` | Validated definitions, statuses, limits | `PatchDefinition`, `PatchInspection`, `PatchError` |
| `patch_engine` | Parse and independently inspect forward/reverse exact matches; no I/O | `UnifiedDiffEngine.parse`, `UnifiedDiffEngine.inspect` |
| `safe_io` | Descriptor-relative traversal and file snapshots | `GuardedDirectory`, `GuardedFile` |
| `atomic_writer`, `backup` | Durable transaction and backup retention | `AtomicFileWriter`, `BackupManager` |
| `patch_source` | Bounded managed/local/HTTPS source reads | `PatchSourceClient` |
| `managed_source` | Immutable private patch revisions | `ManagedPatchStore` |
| `source_upload`, `target_picker` | Consume native uploads and enumerate bounded target suggestions | `read_upload`, `list_targets` |
| `reconciler` | Synchronous policy and transaction orchestration | `Reconciler.run` |
| `coordinator` | HA loop state, serialized admission and drained teardown | `PatchManagerRuntime` |
| `watcher` | Observer ownership, loop debounce and root recovery | `PatchWatcher` |
| `state_store`, `repairs` | Metadata persistence and native issue projection | `StateStore`, `IssueManager` |
| `config_flow`, `validation` | Native configuration and read-only validation | HA flow hooks |
| `sensor`, `services`, `diagnostics`, `__init__` | Thin HA projections/composition | HA integration hooks |

The engine uses patch-ng only to parse/check the diff structure. Owned matching
requires unique whole-context placement and inspects both directions against the
same original bytes. It does not use patch-ng's filesystem applicator or change
the process working directory.

Potentially blocking work runs in HA's executor. The runtime owns admitted tasks
and shields them from caller cancellation until their result is recorded. Unload
closes admission, stops watches and drains admitted work before releasing state.
Watchdog threads enqueue immutable event paths onto HA's event loop; they never
change HA entities or configuration directly.

Configuration publication and runtime actions share a lock that survives reloads.
A final source-change check and native update run under that lock; teardown drains
active saves. Managed files are published before their references are configured,
without overwriting existing revisions. Upload processing and discovery run in
the executor.

Native subentries are the source of configuration. Metadata storage contains
status history only. Revert updates native auto-apply configuration before file
work, using HA's normal configuration persistence lifecycle. This is not a
separate fsync transaction spanning HA storage and the target file.

Tests cover decisions independently and exercise native flows, sensors, service
permissions, watcher threads and filesystem failures. End-to-end HACS update
acceptance is a separate release gate; synthetic filesystem events do not replace
it. See the release guide for the manual checks that complement CI.

## Working on the project

Follow [the contribution rules](../CONTRIBUTING.md), including mandatory Dev
Container reproduction when investigating problems with an external PR.

Start with the [Dev Container guide](../.devcontainer/README.md). Opening the
container starts its own HA on forwarded port 8123; it does not need your existing
installation. The browser runtime and test environment use separate virtual
environments. Product tests create temporary HA objects/configuration directories.

Inside the container, from the repository root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests .devcontainer/scripts .devcontainer/tests script
.venv/bin/mypy --python-version 3.14
python3 -m unittest discover -s .devcontainer/tests -v
```

CI repeats product tests in the separate minimum HA/Python environment. Do not
install its lock over the running recent HA environment. Use temporary files and
fake network/GitHub boundaries in tests; no test should need household HA, a real
GitHub token, or publication permissions.

## Packaging and release boundaries

`script/build_release.py` validates the three version files and builds a tracked-file
ZIP/checksum. It has no network or publication responsibility.
`script/release_github.py` owns the GitHub draft lifecycle, checks commit/tag/asset
identity and delegates packaging to the builder. Its narrow GitHub adapter is
substituted in offline tests. YAML workflows orchestrate these helpers and reuse
the same test/validation jobs; they do not contain a second implementation of
version selection or archive building. Release Please owns version proposals and
changelog updates. See [versioning and releases](releasing.md).

The primary language is Python; support files use Bash, Dockerfile, JSON, YAML,
TOML, INI and Markdown, plus PNG captures/branding and text/unified-diff examples.
There is no repository-owned JavaScript frontend or Node package dependency.
GitHub's Release Please action runs its own bundled Node runtime on the runner.

## Contributing without publishing local data

The `.gitignore` starts with a default deny rule. Add narrow exceptions for new
owned paths, keeping explicit private/generated exclusions after them. Check
`git status --untracked-files=all` and `git check-ignore --no-index <path>` before
staging; do not force-add files to bypass the policy. HA state, `.storage`, venvs,
`.env`, caches, `dist` and local planning evidence must stay out of commits.

Use Conventional Commit messages and include behavior tests with code changes.
Update the user guides when visible behavior changes. Keep credentials out of
examples and diagnostics captures. See [the release guide](releasing.md) for
version/changelog ownership; a feature PR should not independently bump one of
the version files while leaving the others behind.
