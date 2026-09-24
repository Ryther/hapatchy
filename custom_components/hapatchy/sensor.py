"""One status sensor per native patch subentry, without a fictitious device."""

from dataclasses import asdict

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback

from .models import Status


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = entry.runtime_data
    for patch_id in runtime.definitions:
        async_add_entities([PatchStatusSensor(runtime, patch_id)], config_subentry_id=patch_id)


class PatchStatusSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [status.value for status in Status]
    _attr_translation_key = "patch_status"

    def __init__(self, runtime, patch_id):
        self.runtime, self.patch_id = runtime, patch_id
        self._attr_unique_id = f"{runtime.entry.entry_id}_{patch_id}_status"
        self._attr_name = f"{runtime.definitions[patch_id].name} status"

    @property
    def native_value(self):
        return self.runtime.states[self.patch_id].status.value

    @property
    def extra_state_attributes(self):
        state = asdict(self.runtime.states[self.patch_id])
        state.pop("status")
        if self.runtime.states[self.patch_id].status == Status.SECURITY_ERROR:
            state.pop("target_sha256", None)
            state.pop("patch_sha256", None)
            return state
        state["target_path"] = self.runtime.definitions[self.patch_id].target_path
        state["patch_id"] = self.patch_id
        return state

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.subscribe(self.patch_id, self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()
