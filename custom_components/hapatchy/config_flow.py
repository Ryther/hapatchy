"""Native single-entry, patch subentry and global retention forms."""

from dataclasses import asdict
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DEFAULT_RETENTION, DOMAIN
from .models import PatchDefinition, PatchError, Status
from .validation import validate_definition


class HAPatchYConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="HAPatchY", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {"patch": PatchSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RetentionOptionsFlow()


class _RetentionRange(vol.Range):
    """A serializable numeric range that also rejects bool/coercion at the boundary."""

    def __call__(self, value):
        if type(value) is not int:
            raise vol.Invalid("invalid_retention")
        return super().__call__(value)


_RETENTION = vol.All(int, _RetentionRange(min=1, max=100))


class RetentionOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                value = _RETENTION(user_input.get("backup_retention"))
            except vol.Invalid:
                errors["base"] = "invalid_retention"
            else:
                return self.async_create_entry(title="", data={"backup_retention": value})
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "backup_retention",
                        default=self.config_entry.options.get(
                            "backup_retention", DEFAULT_RETENTION
                        ),
                    ): _RETENTION,
                }
            ),
        )


class PatchSubentryFlow(config_entries.ConfigSubentryFlow):
    def __init__(self):
        self._data: dict[str, Any] = {}
        self._warning = ""

    def _entry(self):
        return self.hass.config_entries.async_get_known_entry(self.handler[0])

    async def async_step_reconfigure(self, user_input=None):
        if not self._data:
            self._data = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            try:
                PatchDefinition.from_mapping("pending", self._data)
            except PatchError as error:
                errors["base"] = error.reason
            else:
                return await self.async_step_options()
        fields: dict[Any, Any] = {
            vol.Required(name, default=self._data.get(name, "")): str
            for name in ("name", "target_path", "watch_root", "source")
        }
        fields[vol.Required("source_type", default=self._data.get("source_type", "local"))] = (
            vol.In(["local", "url"])
        )
        fields[vol.Optional("watch_pattern", default=self._data.get("watch_pattern", ""))] = str
        return self.async_show_form(step_id="user", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_options(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            try:
                definition = PatchDefinition.from_mapping("pending", self._data)
                own_id = self.context.get("subentry_id")
                if any(
                    subentry.subentry_id != own_id
                    and subentry.data.get("target_path") == definition.target_path
                    for subentry in self._entry().subentries.values()
                ):
                    raise PatchError("duplicate_target")
                result = await validate_definition(self.hass, definition)
            except PatchError as error:
                errors["base"] = error.reason
            else:
                self._data = asdict(definition)
                self._data.pop("patch_id")
                if not definition.backup_before_apply or result.status in (
                    Status.CONFLICT,
                    Status.MISSING_TARGET,
                ):
                    self._warning = (
                        result.status.value
                        if result.status in (Status.CONFLICT, Status.MISSING_TARGET)
                        else "backup_disabled"
                    )
                    return await self.async_step_confirm()
                return self._save()
        fields: dict[Any, Any] = {
            vol.Optional(name, default=self._data.get(name, True)): bool
            for name in ("enabled", "auto_apply", "reconcile_on_startup", "backup_before_apply")
        }
        fields[vol.Optional("source_sha256", default=self._data.get("source_sha256") or "")] = str
        fields[
            vol.Optional("debounce_seconds", default=self._data.get("debounce_seconds", 1.5))
        ] = vol.All(vol.Coerce(float), vol.Range(min=0.1, max=60))
        return self.async_show_form(
            step_id="options", data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_confirm(self, user_input=None):
        if user_input and user_input.get("confirm") is True:
            return self._save()
        return self.async_show_form(
            step_id=f"confirm_{self._warning}",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
        )

    async def async_step_confirm_backup_disabled(self, user_input=None):
        return await self.async_step_confirm(user_input)

    async def async_step_confirm_conflict(self, user_input=None):
        return await self.async_step_confirm(user_input)

    async def async_step_confirm_missing_target(self, user_input=None):
        return await self.async_step_confirm(user_input)

    @callback
    def _save(self):
        if self.source == config_entries.SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._entry(),
                self._get_reconfigure_subentry(),
                title=self._data["name"],
                unique_id=self._data["target_path"],
                data=self._data,
            )
        return self.async_create_entry(
            title=self._data["name"], unique_id=self._data["target_path"], data=self._data
        )
