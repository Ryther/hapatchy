"""Administrator-only native actions; callers supply IDs, never paths or code."""

from functools import partial

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError, Unauthorized, UnknownUser
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN
from .models import PatchError

ADMIN_ACTIONS = ("reconcile", "apply", "revert", "refresh_source")
READ_ACTION = "get_patch"
ACTIONS = (*ADMIN_ACTIONS, READ_ACTION)


def _validation_error(reason: str) -> ServiceValidationError:
    return ServiceValidationError(translation_domain=DOMAIN, translation_key=reason)


async def _handle_action(hass: HomeAssistant, call: ServiceCall):
    runtime = hass.data.get(DOMAIN, {}).get("runtime")
    if runtime is None or runtime.closing:
        raise _validation_error("runtime_closing")
    patch_id = call.data.get("patch_id")
    if call.service == "reconcile" and patch_id is None:
        await _reconcile_all(runtime)
        return
    try:
        result = await runtime.async_action(patch_id, call.service)
    except PatchError as error:
        raise _validation_error(error.reason) from None
    if result.service_error:
        raise _validation_error(result.service_error)


async def _handle_read(hass: HomeAssistant, call: ServiceCall):
    # Preserve an explicit user check before reading any patch bytes.
    if call.context.user_id:
        user = await hass.auth.async_get_user(call.context.user_id)
        if user is None:
            raise UnknownUser(context=call.context)
        if not user.is_admin:
            raise Unauthorized(context=call.context)
    runtime = hass.data.get(DOMAIN, {}).get("runtime")
    if runtime is None or runtime.closing:
        raise _validation_error("runtime_closing")
    patch_id = call.data["patch_id"]
    try:
        patch = await runtime.async_read_patch(patch_id)
    except PatchError as error:
        raise _validation_error(error.reason) from None
    return {"patch_id": patch_id, "patch": patch}


async def _reconcile_all(runtime) -> None:
    for key, definition in runtime.definitions.items():
        if definition.enabled:
            try:
                await runtime.async_action(key, "reconcile")
            except PatchError:
                # Each result is already published to its own sensor/Repair.
                continue


@callback
def async_register_services(hass: HomeAssistant) -> None:
    for action in ADMIN_ACTIONS:
        key = vol.Optional("patch_id") if action == "reconcile" else vol.Required("patch_id")
        schema = vol.Schema({key: vol.All(str, vol.Length(min=1, max=64))}, extra=vol.PREVENT_EXTRA)
        async_register_admin_service(
            hass, DOMAIN, action, partial(_handle_action, hass), schema=schema
        )
    hass.services.async_register(
        DOMAIN,
        READ_ACTION,
        partial(_handle_read, hass),
        schema=vol.Schema(
            {vol.Required("patch_id"): vol.All(str, vol.Length(min=1, max=64))},
            extra=vol.PREVENT_EXTRA,
        ),
        supports_response=SupportsResponse.ONLY,
    )


@callback
def async_remove_services(hass: HomeAssistant) -> None:
    for action in ACTIONS:
        hass.services.async_remove(DOMAIN, action)
