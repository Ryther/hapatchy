"""HAPatchY integration."""

from pathlib import Path

import voluptuous as vol

from .const import DOMAIN


def _grant_list(value):
    """Keep HA's YAML schema strict without loading files on the event loop."""
    from .yaml_policy import validate_hapatchy_directories

    try:
        return list(validate_hapatchy_directories({"allowed_directories": value}))
    except ValueError as error:
        raise vol.Invalid("invalid_allowed_directories") from error


CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {vol.Required("allowed_directories"): _grant_list},
            extra=vol.PREVENT_EXTRA,
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Freeze operator YAML grants independently of patch definitions."""
    from .models import PatchError
    from .yaml_policy import DeniedYamlPolicy, load_yaml_policy

    shared = hass.data.setdefault(DOMAIN, {"restart_required": set()})
    try:
        loaded = await hass.async_add_executor_job(
            load_yaml_policy, Path(hass.config.config_dir), config
        )
    except PatchError as error:
        loaded = DeniedYamlPolicy(error.reason)
    shared["yaml_policy"] = loaded
    return True


def _load_runtime_adapters():
    # Keep importing the pure engine independent of HA; load runtime adapters
    # off the event loop when HA actually sets up the integration.
    from .coordinator import PatchManagerRuntime
    from .services import async_register_services

    return PatchManagerRuntime, async_register_services


async def async_setup_entry(hass, entry):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform

    from .models import PatchError

    if entry.version != 1:
        return False
    shared = hass.data.setdefault(DOMAIN, {"restart_required": set()})
    if "runtime" in shared:
        return False
    runtime_class, register_services = await hass.async_add_executor_job(_load_runtime_adapters)
    try:
        runtime = runtime_class(hass, entry)
    except PatchError:
        return False
    entry.runtime_data = runtime
    shared["runtime"] = runtime
    try:
        await runtime.async_load()
        await hass.config_entries.async_forward_entry_setups(
            entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
        )
        await runtime.async_start()
    except BaseException:
        # Setup failures must not strand observers or block a later retry.
        try:
            await runtime.async_close()
            await hass.config_entries.async_unload_platforms(
                entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
            )
        finally:
            if shared.get("runtime") is runtime:
                shared.pop("runtime")
        raise

    async def updated(hass, updated_entry):
        if not runtime.closing and not runtime.matches_entry():
            await hass.config_entries.async_reload(updated_entry.entry_id)

    async def stopped(event):
        await runtime.async_close()

    entry.async_on_unload(entry.add_update_listener(updated))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stopped))
    register_services(hass)
    return True


async def async_unload_entry(hass, entry):
    from homeassistant.const import Platform

    runtime = entry.runtime_data
    # Pause admission first, but retain observer ownership until HA accepts unload.
    runtime.closing = True
    try:
        unloaded = await hass.config_entries.async_unload_platforms(
            entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
        )
    except BaseException:
        runtime.closing = False
        raise
    if not unloaded:
        runtime.closing = False
        for patch_id, definition in runtime.definitions.items():
            if definition.enabled:
                runtime.schedule(patch_id)
        return False
    await runtime.async_close()
    if hass.data[DOMAIN].get("runtime") is runtime:
        hass.data[DOMAIN].pop("runtime")
        from .services import async_remove_services

        async_remove_services(hass)
    return True


async def async_remove_entry(hass, entry):
    from homeassistant.helpers import issue_registry as ir

    for patch_id in entry.subentries:
        ir.async_delete_issue(hass, DOMAIN, f"patch_{patch_id}")
