"""Use the schema implementation that the installed Home Assistant expects."""

from typing import Any

from homeassistant import config_entries

# HA 2026.10 moved native forms and services to probatio. Older supported HA
# releases use voluptuous. Both expose the validators used by HAPatchY.
# The module is selected from HA's own flow implementation so import order
# cannot leave us holding a pre-shim voluptuous module on newer releases.
vol: Any = getattr(config_entries, "probatio", None) or getattr(config_entries, "vol", None)
if vol is None:
    raise RuntimeError("Home Assistant does not expose a supported schema module")
