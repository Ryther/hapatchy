# HAPatchY documentation

![HAPatchY — Home Assistant Patch Manager](images/hapatchy-banner.png)

HAPatchY keeps a deliberate change to one Home Assistant configuration file
when an update replaces that file. It applies a patch only when the surrounding
text still matches unambiguously. Start with an unused text file before changing
an integration or executable configuration.

## What do you want to do?

- **[Install HAPatchY](installation.md):** Choose HACS or manual installation,
  then add the integration.
- **[Make your first patch](first-patch.md):** Edit an unused file and check
  Apply, backup and Revert.
- **[Authorize a folder](directory-permissions.md):** Configure both YAML
  grants and restart HA.
- **[Configure a patch or use an action](reference.md):** Look up exact fields,
  states, limits and administrator actions.
- **[Fix a problem or remove a patch](troubleshooting.md):** Diagnose status
  and Repairs, then recover safely.

HAPatchY changes files in your HA configuration. Keep an independent backup
and authorize only directories whose contents may be read and changed through
the HA administrator API. Read the [product limits](https://github.com/Ryther/hapatchy#before-using-it)
and [directory-grant rules](directory-permissions.md) before patching a real file.

## Contribute or understand the design

- [Architecture](architecture.md) explains the patch engine, filesystem safety
  and Home Assistant lifecycle.
- [Contribution rules](https://github.com/Ryther/hapatchy/blob/main/CONTRIBUTING.md) cover the Dev Container, tests and
  review expectations.
- [Releasing](releasing.md) describes version proposals and publication.

For a quick overview of the integration, return to the [repository README](https://github.com/Ryther/hapatchy#readme).
