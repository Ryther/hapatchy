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

## Option A: HACS custom repository

Use this path when the repository has a published version available to HACS.
HACS itself must already be installed; follow its
[official getting-started guide](https://www.hacs.xyz/docs/use/) if needed.

1. Open **HACS** in Home Assistant.
2. Open its menu and choose **Custom repositories**.
3. Enter `https://github.com/Ryther/hapatchy`, select **Integration**, and add it.
4. Find **HAPatchY** in HACS and download the version you want to test.
5. **Restart Home Assistant**, not just the browser. Downloading custom integration
   files does not load the integration into an already running HA process.
6. Continue with **Add the integration** below.

HACS menu names can vary by version. If it cannot find the repository or a release,
check the [repository](https://github.com/Ryther/hapatchy) and
[Releases page](https://github.com/Ryther/hapatchy/releases). A repository URL in a
README is not evidence that a release has been published. Do not substitute an
unrelated similarly named project.

## Option B: manual installation

1. Download the versioned HAPatchY archive from GitHub Releases. For unreleased
   development testing, download/clone the repository instead.
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

HA installs the integration's declared Python dependencies using its own runtime.
You do not need to install Python, run `pip`, or create a venv inside your HA
installation. Internet access may be required for dependency installation.

## Add the integration

1. Sign in as an administrator.
2. Open **Settings → Devices & services → Add integration**.
3. Search for **HAPatchY**, select it and submit the confirmation form.
4. Open the HAPatchY integration page. You should see **Add patch**.

Create HAPatchY only once. Multiple patches live inside that one integration.
No sensor appears until you add a patch. Continue with
[Your first patch](first-patch.md) before configuring an important file.

If HAPatchY is missing from the search, check the folder layout, restart HA and
read **Settings → System → Logs**. A custom-integration warning is normal; an
import or dependency error needs investigation. See
[troubleshooting](troubleshooting.md#hapatchy-does-not-appear-or-fails-to-load).

## Updating later

Read release notes before updating. Update through HACS, or replace the integration
folder with the new version for a manual installation, then restart HA. Keep your
patch definitions, patch source files and backups. An update to HAPatchY is distinct
from an update to the third-party file you are patching: inspect that patch's status
after either update. Never assume an `applied` disk state proves Python code has
been reloaded into memory.
