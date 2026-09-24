# Troubleshooting, recovery and removal

[← Documentation home](../README.md) · [Status reference](reference.md#status-sensor)

See [the verification record](verification.md) for the behavior exercised in the
disposable HA instance and by automated tests for this revision.

## Start with these checks

1. Open the patch's status sensor and note its state, `last_error` and
   `watcher_available` attributes. Paths and hashes are hidden after a security
   denial.
2. Open **Settings → System → Repairs** for a HAPatchY issue. On some HA versions,
   Repairs is reached from the Settings notification/menu instead.
3. If you need to inspect files without automatic reapplication, reconfigure the
   patch and turn **Apply compatible patches automatically** off.
4. Use **Refresh source** for a read-only check. **Reconcile can write** when
   automatic application is enabled.

Do not edit `.storage` or restore random backup files as an initial troubleshooting
step. Preserve the current target and patch before investigating a mismatch.

## HAPatchY does not appear or fails to load

Check that `custom_components/hapatchy/manifest.json` exists under your actual HA
configuration folder, without an extra nested directory. Restart HA after copying
or downloading the integration. Check the minimum HA version in the README and
read **Settings → System → Logs** for an import or dependency error.

HA's standard warning that a custom integration has not been tested by Home
Assistant is expected. A traceback or missing dependency is a separate problem.
Do not try to fix the HA runtime by installing a different Python version into it.

## Applicable, but the file is not changing

`applicable` means the patch can be applied, not that it already has been.
Check the automatic-application setting. You can leave it off and use **Apply**
for controlled manual changes. A disabled rule must be enabled before any action
is allowed. If startup checks are off, run Reconcile explicitly.

## Applied, but the integration still behaves the same

Check the target contents first. `applied` describes bytes on disk. Python modules
already imported into HA can continue running their previous code until HA is
restarted. Plan an HA restart yourself when needed. HAPatchY does not restart HA,
and cannot verify the behavioral effect of a patch in another integration.

## Conflict or invalid patch

An upstream update may have changed the lines your patch expects. A patch can
also be ambiguous because two blocks contain identical context.

1. Keep a copy of the current upstream file and the original patch.
2. Compare the patch's expected old lines with the current file.
3. Obtain a patch for the installed upstream version. Include distinctive context
   around the intended block, not just a common line such as `enabled = True`.
4. Check that both diff headers name the configured target path.
5. Use Refresh source before deciding to Apply or enable automatic application.

There is no force option. Restoring an old whole-file backup over a newer upstream
version can remove unrelated fixes. Review the differences rather than doing that
blindly. For a controlled example of valid context, revisit
[Your first patch](first-patch.md).


## Source error

For a managed source, keep `.hapatchy/patches/` in your HA backup. If a revision
is missing, Reconfigure can restore its exact original contents. Do not edit
hash-named files directly; use the editor after Revert.

For a local source, confirm the file exists in the configuration folder and is
readable by HA. Check spelling, capitalization, extension and UTF-8 encoding.
For HTTPS, check that the URL returns patch text directly, without an HTML page,
login or redirect. Check connectivity and the optional source fingerprint.

Patch sources larger than 2 MiB are rejected. Download failures never trigger an
application using stale cached data. Fix the source, then run Refresh source.

## Missing target or unavailable watcher

Check the configured target and watch directory. HAPatchY does not create missing
targets for you. It can wait for an integration installer/updater to create one.
The watcher checks missing/replaced directories every 60 seconds; allow for that
interval and the configured debounce delay after an update.

Do not broaden the watch to the whole configuration folder. Use an explicit
subdirectory containing the target. If the directory remains unavailable, inspect
its permissions and check for a symlink rather than repeatedly forcing actions.

## Security error

Start with [both directory lists](directory-permissions.md): the operator must
name the target and watch directory, then restart HA. A changed, missing or
unreadable YAML source also blocks operations until restart. Paths must stay
inside the HA configuration folder. Absolute paths, traversal,
symlinks, hard-linked files, special files and protected internal directories are
not supported. Use a normal file under a normal subdirectory. HAPatchY's own code,
`.storage` and `.hapatchy` are deliberately protected from patch rules.

## Apply error or durability unconfirmed

Check available disk space, file/directory ownership and permissions. If creating
a required backup fails, the write is refused. Backups live in
`.hapatchy/backups/<patch_id>/`, and each completed backup includes original bytes
in `target` plus metadata in `metadata.json`.

A write can replace the file and then fail while asking the filesystem to flush
the directory. For `durability_unconfirmed`, bytes **may already have changed**.
Preserve the current file, inspect the Repair and address the storage problem.
Afterward, run a check again; the error is cleared only after durability is
confirmed. Do not repeatedly overwrite the file with an old backup.

## Revert failed

Revert requires a unique reverse match using the current patch source. It can fail
if upstream changes intervened, the source changed, or the patch was never applied.
Automatic application remains off after a non-security attempt. A security denial
leaves the saved setting unchanged. If `last_error` is
`revert_metadata_unavailable`, the target may already be reverted and automatic
reapplication is suspended; fix HA storage and retry Revert. Inspect the file and source
before retrying. If a manual repair is necessary, preserve both versions and
review the intended edits; the backup is evidence, not an unconditional rollback.

## Remove a patch or uninstall HAPatchY

1. If you want to undo its change, run **Revert** first and verify the target.
   If Revert fails, resolve that separately before assuming the change is gone.
2. Remove the individual patch from its menu on the HAPatchY integration page.
3. To stop using HAPatchY entirely, remove its integration entry from
   **Settings → Devices & services**.
4. For a manual installation, delete `custom_components/hapatchy`, then restart
   HA. HACS removal is outside the verified procedure.

Removing rules or integration files does **not** restore targets or erase backups.
Your patch source files also remain. Keep them until you no longer need recovery;
remove them manually only when you are sure.


## Report a problem

Open an issue with the HA version, HAPatchY version, installation method, sensor
state, controlled error reason and steps to reproduce. Attach a small synthetic
example rather than an entire third-party integration or your full configuration.

Use the integration menu's **Download diagnostics** when available. HAPatchY omits
file contents and full source URLs, but paths, names and source hostnames can
still identify your setup. Review the download and logs before sharing. Never post
credentials, tokens, `.storage`, or a full configuration backup.
