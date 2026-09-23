# Architecture

HAPatchY separates pure patch decisions from filesystem mutation and Home
Assistant lifecycle. No patch is executed as a shell command or Python program.

| Boundary | Owned responsibility | Public seam |
| --- | --- | --- |
| `models`, `const` | Validated definitions, statuses, limits | `PatchDefinition`, `PatchInspection`, `PatchError` |
| `patch_engine` | Parse and independently inspect forward/reverse exact matches; no I/O | `UnifiedDiffEngine.parse`, `UnifiedDiffEngine.inspect` |
| `safe_io` | Descriptor-relative traversal and file snapshots | `GuardedDirectory`, `GuardedFile` |
| `atomic_writer`, `backup` | Durable transaction and backup retention | `AtomicFileWriter`, `BackupManager` |
| `patch_source` | Bounded local/HTTPS source reads | `PatchSourceClient` |
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

Native subentries are the source of configuration. Metadata storage contains
status history only. Revert updates native auto-apply configuration before file
work, using HA's normal configuration persistence lifecycle. This is not a
separate fsync transaction spanning HA storage and the target file.

Tests cover decisions independently and exercise native flows, sensors, service
permissions, watcher threads and filesystem failures. End-to-end HACS update
acceptance is a separate release gate; synthetic filesystem events do not replace
it. See the release procedure for the remaining external checks.
