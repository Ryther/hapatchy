# What has actually been tried

On **24 September 2026**, the user walkthrough was exercised in Chromium against
**Home Assistant 2026.9.0 / Python 3.14.7 / HAPatchY 0.1.0**, using disposable
configuration directories. No household HA installation was involved.

The images linked below are captures of the running HA UI. They are not mockups.
For apply/revert/reapplication, the target file was also read from disk; a sensor
screenshot alone would not prove that the bytes were correct.

## Managed editor, upload and target picker

The revised workflow was exercised in the Dev Container's isolated HA on the
same date and versions. The current [first-patch tutorial](first-patch.md) follows
this run. The older local-source run below remains evidence for unchanged actions
and error handling; its old path form is not the current Add patch form.

| Operation performed | Observed result | Screenshot |
| --- | --- | --- |
| Search the server-side target list and select a file | `hapatchy_ui_demo/settings.txt` selected without typing its path | [Picker](images/managed-target-picker.png) |
| Enter a multiline diff and submit with auto-apply off | Enter inserted a newline; managed source saved; target retained `interval = 30` | [Editor](images/managed-editor.png), [options](images/managed-options.png), [status](images/managed-applicable.png) |
| Upload a `.patch` for a second target | Native upload accepted; the editor prefilled the exact submitted text; final submit created a second managed rule | [Upload](images/managed-upload.png) |
| Restart the isolated HA | Both rules loaded their managed sources from disk; unchanged reconfiguration also saved successfully | [Reopened uploaded patch](images/managed-upload-reopened.png) |
| Apply, then attempt to change the applied patch | Target became `interval = 5`; editor refused replacement and retained the original revision | [Applied](images/managed-applied.png), [blocked edit](images/managed-revert-before-edit.png) |
| Revert, reopen the editor and change the replacement to `interval = 7` | Original target restored; old patch prefilled; new revision saved with the same rule ID | [Reverted](images/managed-reverted.png), [edit](images/managed-edit-revision.png) |
| Enable automatic application, then replace target with original bytes | New revision restored `interval = 7`; final Revert returned `interval = 30` | [Reapplied](images/managed-auto-reapplied.png) |

The patch revision files were read back and their SHA-256 names checked against
contents. Previous revisions were retained. Native configuration contains only
the revision reference; neither upload identifiers nor editor text were persisted
in the rule. Race/failure handling, including an apply or reload during save,
was tested automatically rather than inferred from screenshots.

## Earlier local-source browser and filesystem checks

| Operation performed | Observed result | Screenshot |
| --- | --- | --- |
| Copy the integration into a separate HA configuration, start HA and use Add integration | HAPatchY found; setup completed; Add patch available | [Search](images/install-search.png), [ready](images/install-ready.png) |
| Add the earlier local-source example with auto-apply off | Sensor `applicable`; original `interval=30` retained | [Paths](images/patch-paths.png), [options](images/patch-options.png), [state](images/applicable.png) |
| Perform Apply in the Actions YAML editor | `applied`; file contained `interval=5`; completed backup contained target bytes and metadata | [Action](images/action-apply.png), [state](images/applied.png) |
| Perform Revert | `applicable`; file returned to `interval=30`; auto-apply remained off in the reconfiguration form | [State](images/reverted.png), [persisted option](images/revert-auto-off.png) |
| Enable automatic application, then replace the target with its original contents | Watcher restored `interval=5`; sensor returned to `applied` | [After reapplication](images/auto-reapplied.png) |
| Replace target contents with a nonmatching version and Refresh source | `conflict`; Repairs showed “Patch needs attention” | [Conflict](images/conflict.png), [Repair](images/repair-conflict.png) |
| Temporarily remove the local source and Refresh source | `source_error` | [Source error](images/source-error.png) |
| Supply invalid patch text and Refresh source | `invalid_patch` | [Invalid patch](images/invalid-patch.png) |
| Temporarily remove the target and Refresh source | `missing_target` | [Missing target](images/missing-target.png) |
| Restore source and target, then Refresh source | Returned to `applicable` | [Recovered](images/recovered.png) |
| Disable the rule, then enable it again | Sensor became `disabled`; normal checking resumed after enabling | [Disabled](images/disabled.png) |
| Open integration options and submit backup retention | Native retention form accepted the setting | [Options](images/retention.png) |
| Download diagnostics from the integration menu | JSON downloaded successfully; kept out of the repository | [Menu](images/diagnostics-menu.png) |
| Delete the reverted demo rule | Rule removed; target and backups remained | [Confirmation](images/remove-patch.png) |
| Delete the integration, remove its copied folder and restart the separate HA | Native deletion completed; HAPatchY no longer appeared in Add integration | [Confirmation](images/remove-integration.png), [after restart](images/uninstalled.png) |

That earlier run used the previous tutorial fixtures (`mode=demo`, `interval=30`,
and the `hapatchy_demo` target path). The current downloadable files match the
managed-editor example above.
Browser automation entered forms and performed actions; direct file writes were
used only to create the example and simulate the documented replacements/errors.
On this HA frontend, developer tools appear under the title **Tools**.

## Limits of this evidence

The manual-copy test reused the development Python runtime, with dependencies
already provisioned and HA's `--skip-pip` option. It verifies folder layout,
discovery and native setup. It does **not** verify first-time dependency downloads
on HA OS. The development instance uses a source link; the separate manual test
used a real copy of the integration directory.

The following have **not** been demonstrated by this walkthrough:

- Installation/update from HACS or from a published GitHub release.
- An actual HACS update of a third-party integration being patched.
- A newer HAPatchY release replacing an older installed version.
- The first GitHub Actions release run, token setup and public asset download.
- The same browser walkthrough on HA 2025.3; that baseline has automated tests.
- Live HTTPS source downloads and every filesystem failure/recovery condition.

The reference's parser, path, permission, concurrency and durability contracts
are covered by automated tests, not by claiming screenshots prove all edge cases.
In particular, `security_error` and `durability_unconfirmed` recovery guidance is
implementation/test-backed and was not fault-injected in this browser session.

When documenting a new user procedure, first perform it in a disposable HA,
record the HA/HAPatchY versions and actual result, and capture the relevant UI.
Check the target bytes for write operations. Keep credentials, raw diagnostics
and HA state private. Add only reviewed screenshots to the whitelist and link
them at the step they demonstrate; explicitly retain any unverified limitations.
