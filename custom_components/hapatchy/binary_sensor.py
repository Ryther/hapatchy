"""A small automatable problem indicator for each patch."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import callback

from .models import Status
from .patch_device import patch_device_info

ATTENTION_STATUSES = frozenset(
    {
        Status.CONFLICT,
        Status.MISSING_TARGET,
        Status.SOURCE_ERROR,
        Status.INVALID_PATCH,
        Status.SECURITY_ERROR,
        Status.APPLY_ERROR,
    }
)


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data
    for patch_id in runtime.definitions:
        async_add_entities([PatchAttentionSensor(runtime, patch_id)], config_subentry_id=patch_id)


class PatchAttentionSensor(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "patch_attention"

    def __init__(self, runtime, patch_id):
        self.runtime, self.patch_id = runtime, patch_id
        self._attr_unique_id = f"{runtime.entry.entry_id}_{patch_id}_attention"
        self._attr_name = "Patch health"
        self._attr_device_info = patch_device_info(runtime, patch_id)

    @property
    def is_on(self):
        state = self.runtime.states[self.patch_id]
        if not self.runtime.definitions[self.patch_id].enabled or state.status in (
            Status.UNKNOWN,
            Status.DISABLED,
        ):
            return None
        return state.status in ATTENTION_STATUSES or not state.watcher_available

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.subscribe(self.patch_id, self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()
