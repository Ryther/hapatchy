"""Operational metadata only; patch definitions belong to native HA subentries."""

import logging
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .models import PatchRuntimeState

_LOGGER = logging.getLogger(__name__)
_FIELDS = ("last_checked_at", "last_applied_at", "target_sha256", "patch_sha256", "last_error")


class StateStore:
    def __init__(self, hass: HomeAssistant, entry_id: str):
        self.store: Store[dict[str, dict[str, str | None]]] = Store(hass, 1, f"{DOMAIN}.{entry_id}")

    async def load(self, states: dict[str, PatchRuntimeState]) -> None:
        try:
            data = await self.store.async_load()
        except (ValueError, OSError):
            _LOGGER.warning("metadata_load_failed")
            return
        if data is None:
            return
        if not isinstance(data, dict):
            _LOGGER.warning("metadata_invalid")
            return
        for patch_id, state in states.items():
            item = data.get(patch_id, {})
            if not isinstance(item, dict):
                _LOGGER.warning("metadata_invalid")
                continue
            for field in ("target_sha256", "patch_sha256"):
                value = item.get(field)
                if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
                    setattr(state, field, value)
            for field in ("last_checked_at", "last_applied_at"):
                value = item.get(field)
                if isinstance(value, str) and re.fullmatch(r"[0-9T:.+Z-]{10,40}", value):
                    setattr(state, field, value)
            # These failures remain safety gates across reloads.
            if item.get("last_error") in (
                "durability_unconfirmed",
                "revert_metadata_unavailable",
            ):
                state.last_error = item["last_error"]

    async def save(self, states: dict[str, PatchRuntimeState]) -> None:
        await self.store.async_save(
            {
                patch_id: {field: getattr(state, field) for field in _FIELDS}
                for patch_id, state in states.items()
            }
        )
