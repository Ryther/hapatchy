"""Native single-entry, patch subentry and global retention forms."""

import asyncio
import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DEFAULT_RETENTION, DOMAIN
from .managed_source import ManagedPatchStore, validate_content
from .models import PatchDefinition, PatchError, Status
from .source_upload import read_upload
from .target_picker import list_targets
from .validation import inspect_target, validate_definition


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
        self._draft: bytes | None = None
        self._original: PatchDefinition | None = None
        self._targets: list[str] | None = None

    def _entry(self):
        return self.hass.config_entries.async_get_known_entry(self.handler[0])

    @property
    def _root(self):
        return Path(self.hass.config.config_dir)

    async def async_step_reconfigure(self, user_input=None):
        if not self._data:
            subentry = self._get_reconfigure_subentry()
            self._data = dict(subentry.data)
            self._original = PatchDefinition.from_mapping(subentry.subentry_id, self._data)
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            method = self._data["source_type"]
            if method in ("managed", "upload"):
                self._data["source_type"] = "managed"
            self._data["watch_root"] = (
                self._data.get("watch_root") or self._data["target_path"].rpartition("/")[0]
            )
            try:
                # Source bytes/address are requested in the following step.
                placeholder = (
                    "0" * 64
                    if method in ("managed", "upload")
                    else (
                        "https://example.invalid/patch"
                        if method == "url"
                        else self._data["target_path"] + ".patch-source"
                    )
                )
                PatchDefinition.from_mapping("pending", self._data | {"source": placeholder})
            except PatchError as error:
                errors["base"] = error.reason
            else:
                if method == "upload":
                    return await self.async_step_upload()
                if method == "managed":
                    return await self.async_step_editor()
                return await self.async_step_source()
        if self._targets is None:
            self._targets = await self.hass.async_add_executor_job(list_targets, self._root)
        fields = {
            vol.Required("name", default=self._data.get("name", "")): str,
            vol.Required(
                "target_path", default=self._data.get("target_path", "")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=self._targets,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "source_type", default=self._data.get("source_type", "managed")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["managed", "upload", "local", "url"], translation_key="source_type"
                )
            ),
            vol.Optional("watch_root", default=self._data.get("watch_root", "")): str,
            vol.Optional("watch_pattern", default=self._data.get("watch_pattern", "")): str,
        }
        return self.async_show_form(step_id="user", data_schema=vol.Schema(fields), errors=errors)

    async def async_step_source(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            try:
                PatchDefinition.from_mapping("pending", self._data)
            except PatchError as error:
                errors["base"] = error.reason
            else:
                return await self.async_step_options()
        initial = self._data.get("source", "")
        if self._original and self._original.source_type != self._data["source_type"]:
            initial = ""
        return self.async_show_form(
            step_id="source",
            errors=errors,
            data_schema=vol.Schema({vol.Required("source", default=initial): str}),
        )

    async def async_step_upload(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._draft = await self.hass.async_add_executor_job(
                    read_upload, self.hass, user_input["file"]
                )
            except PatchError as error:
                errors["base"] = error.reason
            else:
                return await self.async_step_editor()
        return self.async_show_form(
            step_id="upload",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("file"): selector.FileSelector(
                        selector.FileSelectorConfig(accept=".patch,.diff,.txt,text/plain")
                    )
                }
            ),
        )

    async def _check_source_change(self, definition: PatchDefinition):
        if self._original is None:
            return
        changed = (definition.source_type, definition.source, definition.target_path) != (
            self._original.source_type,
            self._original.source,
            self._original.target_path,
        )
        if not changed:
            return
        previous = await validate_definition(self.hass, self._original)
        if previous.status == Status.APPLIED:
            raise PatchError("revert_before_edit")

    async def async_step_editor(self, user_input=None):
        errors = {}
        if self._draft is None and self._original and self._original.source_type == "managed":
            try:
                self._draft = await self.hass.async_add_executor_job(
                    ManagedPatchStore(self._root).load, self._original.source
                )
            except PatchError:
                # A missing source can be restored by supplying the exact original contents.
                errors["base"] = "managed_source_unavailable"
        if user_input is not None:
            self._draft = user_input.get("patch_text", "").encode("utf-8")
            try:
                validate_content(self._draft)
                self._data["source"] = hashlib.sha256(self._draft).hexdigest()
                definition = PatchDefinition.from_mapping("pending", self._data)
                await self.hass.async_add_executor_job(
                    inspect_target, self._root, definition, self._draft
                )
                await self._check_source_change(definition)
            except PatchError as error:
                errors["base"] = error.reason
            else:
                return await self.async_step_options()
        return self.async_show_form(
            step_id="editor",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "patch_text", default=(self._draft or b"").decode("utf-8")
                    ): selector.TextSelector(selector.TextSelectorConfig(multiline=True))
                }
            ),
        )

    async def async_step_options(self, user_input=None, *, save_error=None):
        errors = {"base": save_error} if save_error else {}
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
                if definition.source_type == "managed":
                    if self._draft is None:
                        raise PatchError("empty_patch")
                    if (
                        definition.source_sha256
                        and hashlib.sha256(self._draft).hexdigest() != definition.source_sha256
                    ):
                        raise PatchError("source_hash_mismatch")
                    result = await self.hass.async_add_executor_job(
                        inspect_target, self._root, definition, self._draft
                    )
                else:
                    result = await validate_definition(self.hass, definition)
                await self._check_source_change(definition)
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
                return await self._save()
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
            return await self._save()
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

    async def _save(self):
        shared = self.hass.data.setdefault(DOMAIN, {"restart_required": set()})
        lock = shared.setdefault("operation_lock", asyncio.Lock())
        runtime = shared.get("runtime")
        guard = runtime.configuration_guard() if runtime else lock
        try:
            async with guard:
                if self._original is not None:
                    current = self._entry().subentries.get(self._original.patch_id)
                    if (
                        current is None
                        or PatchDefinition.from_mapping(current.subentry_id, dict(current.data))
                        != self._original
                    ):
                        raise PatchError("configuration_changed")
                definition = PatchDefinition.from_mapping("pending", self._data)
                if any(
                    sub.subentry_id != self.context.get("subentry_id")
                    and sub.data.get("target_path") == definition.target_path
                    for sub in self._entry().subentries.values()
                ):
                    raise PatchError("duplicate_target")
                await self._check_source_change(definition)
                if definition.source_type == "managed":
                    assert self._draft is not None
                    self._data["source"] = await self.hass.async_add_executor_job(
                        ManagedPatchStore(self._root).save, self._draft
                    )
                if runtime and runtime.closing:
                    raise PatchError("runtime_reloading")
                return self._commit()
        except PatchError as error:
            return await self.async_step_options(save_error=error.reason)

    def _commit(self):
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
