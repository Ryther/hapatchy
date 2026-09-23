"""Administrator-only native actions; callers supply IDs, never paths or code."""

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN
from .models import PatchError

ACTIONS = ("reconcile", "apply", "revert", "refresh_source")


def _validation_error(reason: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=reason)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def handle(call: ServiceCall):
        runtime = hass.data.get(DOMAIN, {}).get("runtime")
        if runtime is None or runtime.closing:
            raise _validation_error("runtime_closing")
        patch_id = call.data.get("patch_id")
        if call.service == "reconcile" and patch_id is None:
            for key, definition in runtime.definitions.items():
                if definition.enabled:
                    try:
                        await runtime.async_action(key, "reconcile")
                    except PatchError:
                        # Each result is already published to its own sensor/Repair.
                        continue
            return
        try:
            result = await runtime.async_action(patch_id, call.service)
        except PatchError as error:
            raise _validation_error(error.reason) from None
        if result.service_error:
            raise _validation_error(result.service_error)

    for action in ACTIONS:
        key = vol.Optional("patch_id") if action == "reconcile" else vol.Required("patch_id")
        schema = vol.Schema({key: vol.All(str, vol.Length(min=1, max=64))}, extra=vol.PREVENT_EXTRA)
        async_register_admin_service(hass, DOMAIN, action, handle, schema=schema)


@callback
def async_remove_services(hass: HomeAssistant) -> None:
    for action in ACTIONS:
        hass.services.async_remove(DOMAIN, action)
