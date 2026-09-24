# Verification of this revision

[← Documentation home](../README.md) · [Your first patch](first-patch.md)

On **24 September 2026**, this revision ran in the Dev Container's disposable
**Home Assistant 2026.9.0 / Python 3.14.7**. The operator YAML contained explicit
`homeassistant.allowlist_external_dirs` and `hapatchy.allowed_directories` entries
for two test directories. After restarting HA, the integration loaded and the
current Add patch form displayed the two-list requirement:

![Rendered Add patch form in disposable Home Assistant](images/yaml-directory-authorization.png)

The [first-patch tutorial](first-patch.md) was repeated end to end in the actual
browser UI. The picker selected `hapatchy_ui_demo/settings.txt`, whose starting
bytes were exactly `# HAPatchY example\ninterval = 30\n`. Pasting the documented
diff with automatic application off created the `UI interval` rule and an
`applicable` sensor without changing those bytes. **HAPatchY: Apply** changed
the file to `interval = 5`; **HAPatchY: Revert** restored `interval = 30`. Both
actions were invoked through Developer tools, and disk bytes were checked after
each action. A backup was present after Apply.

Reconfigure reopened the saved diff. Editing it to `+interval = 7` and enabling
automatic application saved a new immutable revision and changed the target to
`interval = 7`. Restoring the original target bytes triggered the watcher, which
reapplied `interval = 7`. A final Revert restored the original bytes. The rule
was then removed through the UI. Separately, uploading the documented
`interval.patch` filled the editor with those bytes, saved an `applicable` rule
without altering the target, and was removed through the UI.

![The current browser editor reopens the saved patch](images/first-patch-reconfigure.png)

The same browser flow rejected `https://127.0.0.1/patch` with the translated
network-destination error during final configuration. No rule was saved and the
target bytes remained unchanged. This confirms the visible error for a literal
loopback URL; isolated resolver/connector tests cover private, mixed and
non-global DNS answers without contacting those addresses.

![A loopback HTTPS source is rejected in the native form](images/https-source-denied.png)

An earlier native editor flow also created a managed patch for
`scripts/w003_authorization_demo.txt` with automatic application disabled. The
sensor became `applicable` while disk contained `value = old`. Apply changed
the file to `value = new`; Revert restored `value = old`. Each result was checked
against the target bytes, not inferred from the sensor alone. The native-flow
API refused a target in unlisted `www/` with `hapatchy_path_not_allowed` and
unchanged bytes. Changing `configuration.yaml` while HA was running caused
Apply to be refused without changing the target. Restoring the YAML and
restarting HA restored the loaded integration.

The separate CI smoke booted HA 2025.3.0/Python 3.13.12 and
HA 2026.9.0/Python 3.14.7 from pinned runtime inputs, each with a fresh
temporary configuration. In both processes it completed onboarding, created
a managed patch through HA's native API, checked bytes after Apply and Revert,
and confirmed that a target outside both grants was refused with unchanged
bytes. These smoke checks were run locally; GitHub-hosted execution is not
claimed in this record.

| Environment | Current revision checks |
| --- | --- |
| HA 2025.3.0 / Python 3.13.12 | 281 pytest tests, Ruff, mypy and 13 Dev Container unit tests passed |
| HA 2026.9.0 / Python 3.14.7 | Browser walkthrough above; 281 pytest tests, Ruff, mypy and 13 Dev Container unit tests passed |

The pinned hassfest image reported **0 invalid integrations** after the
translation changes. The pinned actionlint image accepted the workflow files.
The release archive builder completed on both test lanes. These checks were
run locally; GitHub-hosted execution is not claimed in this record.

The screenshots show rendered forms and statuses. Separate disk-byte checks
establish the specific writes above. The minimum HA lane was exercised by
automated tests and the functional API smoke, not by a separate browser session.
The HTTPS browser check used a denied loopback URL, not a live public HTTPS
service. This record does not represent a HACS installation, HACS update or a
public GitHub release.
