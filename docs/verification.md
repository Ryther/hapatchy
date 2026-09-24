# Verification of this revision

[← Documentation home](../README.md) · [Directory permissions](directory-permissions.md)

On **24 September 2026**, this revision ran in the Dev Container's disposable
**Home Assistant 2026.9.0 / Python 3.14.7**. The operator YAML contained explicit
`homeassistant.allowlist_external_dirs` and `hapatchy.allowed_directories` entries
for two test directories. After restarting HA, the integration loaded and the
current Add patch form displayed the two-list requirement:

![Rendered Add patch form in disposable Home Assistant](images/yaml-directory-authorization.png)

The native editor flow created a managed patch for
`scripts/w003_authorization_demo.txt` with automatic application disabled. The
sensor became `applicable` while disk contained `value = old`. Apply changed
the file to `value = new`; Revert restored `value = old`. Each result was checked
against the target bytes, not inferred from the sensor alone.

The native-flow API refused a target in the unlisted `www/` directory with
`hapatchy_path_not_allowed`; its bytes remained unchanged. Changing
`configuration.yaml` while HA was running caused Apply to be refused, again
without changing the target. Restoring the YAML and restarting HA restored the
loaded integration.

Automated checks ran on both pinned environments:

| Environment | Result |
| --- | --- |
| HA 2025.3.0 / Python 3.13.12 | 247 pytest tests, Ruff, mypy and 13 Dev Container unit tests passed |
| HA 2026.9.0 / Python 3.14.7 | The same checks passed; pinned hassfest found no invalid integration metadata or translations |

The separate startup smoke booted HA 2026.9.0 from the complete Dev Container
runtime lock using a fresh temporary configuration. It observed HAPatchY setup
completion and HTTP readiness, then confirmed that the synthetic target still
contained its original bytes. The pinned actionlint image accepted all four
workflow files. These checks were run locally; GitHub-hosted execution is not
claimed in this record.

The browser capture proves the displayed form; tests and byte checks establish
the specific behavior above. The minimum HA lane was exercised by automated
tests, not by a separate browser session. This record does not represent a
HACS installation or a public GitHub release.
