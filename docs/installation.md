# Install HAPatchY

[← Documentation home](../README.md) · [Next: your first patch →](first-patch.md)

## What you need

- Home Assistant **2025.3.0 or newer** and an administrator account.
- A backup of your HA configuration and a separate copy of any file you plan to
  change. HAPatchY's per-file backups are not a replacement for a full HA backup.
- A way to edit files in the **HA configuration directory**. Use an editor or file
  share you already trust. This guide does not require terminal access.

The configuration directory is the folder containing `configuration.yaml`.
For HA OS and common container setups it is exposed inside HA as `/config`;
your editor or host may display a different location. Use the actual configuration
folder, not a folder that merely happens to have the same name on your computer.

HAPatchY paths are relative to this folder. If a file is
`/config/python_scripts/example.py`, enter `python_scripts/example.py`, without
`/config/` and without a leading slash. Do not edit HA's `.storage` files.

## HACS availability

A HACS installation/update has **not been exercised for this revision**. Manual
installation from the published v0.2.0 archive has been exercised in disposable
HA, including Apply, Revert and a denied destination.

## Manual installation

This path was exercised with integration source and the published v0.2.0
archive in separate HA 2026.9.0 configurations. The source path was also
checked in the browser UI. Both used the existing development Python
environment; dependency downloads on a fresh HA OS installation remain
unverified. See [the verification record](verification.md).

1. Download [the v0.2.0 archive](https://github.com/Ryther/hapatchy/releases/tag/v0.2.0)
   from GitHub Releases. The repository source is also available for development
   testing.
2. Locate `custom_components/hapatchy` inside the download.
3. Copy that **entire `hapatchy` folder** into your HA configuration's
   `custom_components` directory. Create `custom_components` if necessary.
4. Check the final layout:

   ```text
   configuration.yaml
   custom_components/
     hapatchy/
       __init__.py
       manifest.json
       config_flow.py
       ...the other integration files...
   ```

   Avoid an extra directory such as `custom_components/hapatchy/hapatchy`.
   Do not copy the development environment, tests or repository root over your HA
   configuration. From the release ZIP, extract only the integration folder.
5. Restart Home Assistant.

Before creating a patch, add the target subdirectory to both YAML directory
lists and restart again. Follow [Allow a directory for HAPatchY](directory-permissions.md)
for a complete example. Installing the integration alone grants no patch targets.

HA installs the integration's declared Python dependencies using its own runtime.
You do not need to install Python, run `pip`, or create a venv inside your HA
installation. Internet access may be required for dependency installation.

## Add the integration

1. Sign in as an administrator.
2. Open **Settings → Devices & services → Add integration**.
3. Search for **HAPatchY**, select it, submit the confirmation form and select **Finish**.
4. Open the HAPatchY integration page. You should see **Add patch**.

Create HAPatchY only once. Multiple patches live inside that one integration.
No sensor appears until you add a patch. Continue with
[Your first patch](first-patch.md) before configuring an important file.

If HAPatchY is missing from the search, check the folder layout, restart HA and
read **Settings → System → Logs**. A custom-integration warning is normal; an
import or dependency error needs investigation. See
[troubleshooting](troubleshooting.md#hapatchy-does-not-appear-or-fails-to-load).

## Updates

The current verification covers source installation and patch operations, not a
HACS update or replacement with a newer released HAPatchY version. Keep a full
HA backup before updating an installed integration.
