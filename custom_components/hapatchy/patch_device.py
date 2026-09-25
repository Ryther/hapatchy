"""Stable Home Assistant device identity for one patch subentry."""

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


def patch_device_info(runtime, patch_id: str) -> DeviceInfo:
    """Group a patch's entities without making its target a hardware device."""
    return DeviceInfo(
        identifiers={(DOMAIN, patch_id)},
        name=runtime.definitions[patch_id].name,
        manufacturer="HAPatchY",
        model="Patch rule",
    )
