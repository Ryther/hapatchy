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
from .patch_builder import MAX_EDITOR_BYTES, build_patch
from .safe_io import Snapshot
from .source_upload import read_upload
from .target_picker import list_targets
from .validation import (
    inspect_target,
    read_editable_target,
    validate_definition,
    verify_editable_snapshot,
)
from .yaml_policy import policy_for_hass


def _editor_error_reason(error: PatchError) -> str:
    if error.reason == "size_limit":
        return "editor_size_limit"
    if error.reason == "unsupported_encoding":
        return "editor_text_format"
    return error.reason


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
        self._edit_snapshot: Snapshot | None = None
        self._editing_file = False
        self._selected_source_type: str | None = None

    def _entry(self):
        return self.hass.config_entries.async_get_known_entry(self.handler[0])

    @property
    def _root(self):
        return Path(self.hass.config.config_dir)

    @property
    def _policy(self):
        return policy_for_hass(self.hass)

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
            self._selected_source_type = method
            if method in ("managed", "upload", "edit_file"):
                self._data["source_type"] = "managed"
            self._data["watch_root"] = (
                self._data.get("watch_root") or self._data["target_path"].rpartition("/")[0]
            )
            try:
                # Source bytes/address are requested in the following step.
                placeholder = (
                    "0" * 64
                    if method in ("managed", "upload", "edit_file")
                    else (
                        "https://example.invalid/patch"
                        if method == "url"
                        else self._data["target_path"] + ".patch-source"
                    )
                )
                definition = PatchDefinition.from_mapping(
                    "pending", self._data | {"source": placeholder}
                )
                await self.hass.async_add_executor_job(self._policy.check_definition, definition)
            except PatchError as error:
                errors["base"] = error.reason
            else:
                if method == "edit_file":
                    if self._original is not None:
                        return self.async_abort(reason="editor_new_patch_only")
                    try:
                        self._edit_snapshot = await self.hass.async_add_executor_job(
                            read_editable_target, self._root, definition, self._policy
                        )
                    except PatchError as error:
                        errors["base"] = _editor_error_reason(error)
                    else:
                        self._data["source"] = placeholder
                        self._editing_file = True
                        return await self.async_step_edit_file()
                if method == "upload":
                    return await self.async_step_upload()
                if method == "managed":
                    return await self.async_step_editor()
                return await self.async_step_source()
        try:
            self._targets = await self.hass.async_add_executor_job(
                list_targets, self._root, self._policy
            )
        except PatchError as error:
            self._targets = []
            errors.setdefault("base", error.reason)
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
                "source_type",
                default=self._selected_source_type
                or self._data.get("source_type", "managed" if self._original else "edit_file"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=([] if self._original else ["edit_file"])
                    + ["managed", "upload", "local", "url"],
                    translation_key="source_type",
                )
            ),
            vol.Optional("watch_root", default=self._data.get("watch_root", "")): str,
            vol.Optional("watch_pattern", default=self._data.get("watch_pattern", "")): str,
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"policy_path": "configuration.yaml"},
        )

    async def async_step_edit_file(self, user_input=None, *, save_error=None):
        """Edit a captured target; only the generated managed diff is persisted."""
        snapshot = self._edit_snapshot
        if not self._editing_file or snapshot is None:
            return self.async_abort(reason="editor_session_expired")
        errors = {"base": save_error} if save_error else {}
        if user_input is not None:
            edited_text = user_input.get("edited_text")
            if not isinstance(edited_text, str):
                errors["base"] = "editor_text_format"
            else:
                edited = edited_text.encode("utf-8") if len(edited_text) <= MAX_EDITOR_BYTES else b""
                if len(edited_text) > MAX_EDITOR_BYTES or len(edited) > MAX_EDITOR_BYTES:
                    errors["base"] = "editor_size_limit"
                else:
                    definition = PatchDefinition.from_mapping("pending", self._data)
                    try:
                        self._draft = await self.hass.async_add_executor_job(
                            build_patch, snapshot.data, edited, definition.target_path
                        )
                        await self.hass.async_add_executor_job(
                            verify_editable_snapshot,
                            self._root,
                            definition,
                            self._policy,
                            snapshot,
                        )
                    except PatchError as error:
                        if error.reason == "editor_target_changed":
                            return self.async_abort(reason="editor_target_changed")
                        errors["base"] = _editor_error_reason(error)
                    else:
                        digest = hashlib.sha256(self._draft).hexdigest()
                        self._data.update(
                            source=digest,
                            source_sha256=digest,
                            enabled=True,
                            auto_apply=True,
                            reconcile_on_startup=True,
                            backup_before_apply=True,
                        )
                        self._data = asdict(PatchDefinition.from_mapping("pending", self._data))
                        self._data.pop("patch_id")
                        return await self._save()
        return self.async_show_form(
            step_id="edit_file",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("edited_text", default=snapshot.data.decode("utf-8")):
                    selector.TextSelector(selector.TextSelectorConfig(multiline=True))
                }
            ),
        )

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
                    inspect_target, self._root, definition, self._draft, self._policy
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
                        inspect_target, self._root, definition, self._draft, self._policy
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
                if self._editing_file:
                    assert self._edit_snapshot is not None
                    await self.hass.async_add_executor_job(
                        verify_editable_snapshot,
                        self._root,
                        definition,
                        self._policy,
                        self._edit_snapshot,
                    )
                else:
                    await self.hass.async_add_executor_job(
                        self._policy.check_definition, definition
                    )
                if definition.source_type == "managed":
                    assert self._draft is not None
                    self._data["source"] = await self.hass.async_add_executor_job(
                        ManagedPatchStore(self._root).save, self._draft
                    )
                if self._editing_file:
                    assert self._edit_snapshot is not None
                    await self.hass.async_add_executor_job(
                        verify_editable_snapshot,
                        self._root,
                        definition,
                        self._policy,
                        self._edit_snapshot,
                    )
                else:
                    await self.hass.async_add_executor_job(
                        self._policy.check_definition, definition
                    )
                if runtime and runtime.closing:
                    raise PatchError("runtime_reloading")
                return self._commit()
        except PatchError as error:
            if self._editing_file:
                if error.reason == "editor_target_changed":
                    return self.async_abort(reason="editor_target_changed")
                return await self.async_step_edit_file(save_error=error.reason)
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
