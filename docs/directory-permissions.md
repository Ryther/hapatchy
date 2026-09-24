# Allow a directory for HAPatchY

[← Installation](installation.md) · [First patch →](first-patch.md)

HAPatchY starts with **no permitted patch destinations**. The Home Assistant
operator must name each permitted subdirectory in two settings in
`configuration.yaml`. HAPatchY's forms and API cannot add these grants.

For the [first-patch tutorial](first-patch.md), add the following entries to your
existing `configuration.yaml`:

```yaml
homeassistant:
  allowlist_external_dirs:
    - /config/hapatchy_ui_demo

hapatchy:
  allowed_directories:
    - hapatchy_ui_demo
```

Keep your other `homeassistant:` settings in the **same** section; do not create
a second `homeassistant:` key. If you already have `allowlist_external_dirs`, add
the directory to that list. `/config` is HA's common *internal* configuration
path; installations using another path must use their actual path in HA's list.
The HAPatchY entry is always relative to the directory containing
`configuration.yaml`, with no leading slash. The example authorizes files below
`hapatchy_ui_demo/`; it does not authorize the configuration root or a sibling
such as `hapatchy_ui_demo_other/`.

Create the directory and target file, save the YAML, then **restart Home
Assistant**. HAPatchY verifies the grants at startup and keeps that snapshot
until the next restart. Editing, deleting or replacing a configuration source
while HA is running blocks patch operations until a restart; reloading only the
HAPatchY integration does not approve a new grant. A missing or malformed section
grants nothing, and malformed YAML can prevent HA itself from starting. Keep a
backup before editing the configuration.

The Add patch form then lists eligible files and explains both requirements:

![The Add patch form explains both directory lists in disposable Home Assistant](images/yaml-directory-authorization.png)

This screenshot was captured on HA 2026.9.0 after a real restart with the YAML
above adapted to the Dev Container path. The same disposable instance accepted a
managed patch in an authorized `scripts/` directory, applied and reverted it,
and its target bytes were checked. A direct native-flow API attempt against an
unlisted `www/` target was refused with its bytes unchanged.

Only explicit, existing directories are accepted. Do not use `.` (the whole
configuration), absolute paths, `..`, wildcards, symlinks, or protected locations
such as `.storage`, `.hapatchy`, and HAPatchY's own integration code. A target's
watch directory must also be within a grant. The target selector is a convenience;
typing a path manually or using HA's API receives the same backend checks.
Home Assistant's live path-permission check still applies after the YAML checks.

Grant only folders whose **future contents** you are willing to let the API
agent alter. A directory grant does not review an individual diff. Patching
Python or other executable configuration can change what HA later runs. An agent
that can edit `configuration.yaml`, invoke another unrestricted file-writing API,
or obtain filesystem access is outside this API-only boundary. Review the patch
contents and API permissions before granting code directories.
