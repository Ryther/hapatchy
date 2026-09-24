"""Deterministic, sanitized native Repair issues."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .models import PatchDefinition, PatchRuntimeState, Status

_ERRORS = {
    Status.CONFLICT,
    Status.MISSING_TARGET,
    Status.SOURCE_ERROR,
    Status.INVALID_PATCH,
    Status.SECURITY_ERROR,
    Status.APPLY_ERROR,
}


class IssueManager:
    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    def update(self, definition: PatchDefinition, state: PatchRuntimeState) -> None:
        if (state.status not in _ERRORS and state.watcher_available) or not definition.enabled:
            self.clear(definition.patch_id)
            return
        key = (
            "durability_unconfirmed"
            if state.last_error == "durability_unconfirmed"
            else state.status.value
        )
        if state.status not in _ERRORS:
            key = "watch_unavailable"
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"patch_{definition.patch_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
            translation_placeholders=(
                {}
                if state.status == Status.SECURITY_ERROR
                else {
                    "target": definition.target_path,
                    "target_sha256": state.target_sha256 or "unknown",
                    "patch_sha256": state.patch_sha256 or "unknown",
                }
            ),
        )

    def clear(self, patch_id: str) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, f"patch_{patch_id}")
