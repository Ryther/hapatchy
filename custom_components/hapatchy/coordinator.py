"""HA event-loop ownership: admission, serialized actions and drained teardown."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_RETENTION, DOMAIN
from .models import PatchDefinition, PatchError, PatchInspection, PatchRuntimeState, Status
from .patch_source import PatchSourceClient
from .reconciler import Reconciler, ReconcileResult
from .repairs import IssueManager
from .state_store import StateStore
from .watcher import PatchWatcher

_LOGGER = logging.getLogger(__name__)


class PatchManagerRuntime:
    def __init__(self, hass: HomeAssistant, entry):
        self.hass, self.entry = hass, entry
        self.definitions = {
            key: PatchDefinition.from_mapping(key, dict(sub.data))
            for key, sub in entry.subentries.items()
            if sub.subentry_type == "patch"
        }
        targets = [definition.target_path for definition in self.definitions.values()]
        if len(set(targets)) != len(targets):
            raise PatchError("duplicate_target")
        self.retention = entry.options.get("backup_retention", DEFAULT_RETENTION)
        if type(self.retention) is not int or not 1 <= self.retention <= 100:
            raise PatchError("invalid_retention")
        self.states = {
            key: PatchRuntimeState(status=Status.UNKNOWN if definition.enabled else Status.DISABLED)
            for key, definition in self.definitions.items()
        }
        self.store = StateStore(hass, entry.entry_id)
        self.issues = IssueManager(hass)
        self.reconciler = Reconciler(Path(hass.config.config_dir))
        self.source = PatchSourceClient(
            Path(hass.config.config_dir), async_get_clientsession(hass), self.run_io
        )
        self.closing = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._admitted: set[asyncio.Task] = set()
        self._workers: set[asyncio.Future] = set()
        self._background: set[asyncio.Task] = set()
        self._listeners: dict[str, set[Callable]] = {}
        self._busy: set[str] = set()
        self.watcher = PatchWatcher(self)

    async def run_io(self, function: Callable):
        future = self.hass.async_add_executor_job(function)
        self._workers.add(future)
        future.add_done_callback(self._workers.discard)
        return await asyncio.shield(future)

    async def async_load(self):
        await self.store.load(self.states)
        restart = self.hass.data[DOMAIN]["restart_required"]
        for key, state in self.states.items():
            state.restart_may_be_required = key in restart
            if state.last_error == "durability_unconfirmed" and self.definitions[key].enabled:
                state.status = Status.APPLY_ERROR
                self.issues.update(self.definitions[key], state)

    async def async_start(self):
        await self.watcher.async_start()
        for key, definition in self.definitions.items():
            if definition.enabled and definition.reconcile_on_startup:
                self.schedule(key)

    def schedule(self, patch_id: str):
        if self.closing:
            return
        task = self.hass.async_create_background_task(
            self.async_action(patch_id, "reconcile"), f"{DOMAIN} reconcile"
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def subscribe(self, patch_id: str, listener: Callable) -> Callable:
        listeners = self._listeners.setdefault(patch_id, set())
        listeners.add(listener)
        return lambda: listeners.discard(listener)

    def _publish(self, patch_id: str):
        self.issues.update(self.definitions[patch_id], self.states[patch_id])
        for listener in tuple(self._listeners.get(patch_id, ())):
            listener()

    def busy(self, patch_id: str) -> bool:
        return patch_id in self._busy

    def watch_available(self, patch_id: str, available: bool):
        self.states[patch_id].watcher_available = available
        self._publish(patch_id)

    def matches_entry(self) -> bool:
        try:
            definitions = {
                key: PatchDefinition.from_mapping(key, dict(sub.data))
                for key, sub in self.entry.subentries.items()
                if sub.subentry_type == "patch"
            }
        except PatchError:
            return False
        return (
            definitions == self.definitions
            and self.entry.options.get("backup_retention", DEFAULT_RETENTION) == self.retention
        )

    def _disable_auto_apply(self, patch_id: str):
        definition = replace(self.definitions[patch_id], auto_apply=False)
        self.definitions[patch_id] = definition
        data = asdict(definition)
        data.pop("patch_id")
        # Native config persistence, not an ephemeral runtime flag. The update
        # listener sees this synchronized definition and does not reload mid-action.
        self.hass.config_entries.async_update_subentry(
            self.entry, self.entry.subentries[patch_id], data=data
        )

    def _validate_current(self, patch_id: str):
        if patch_id not in self.definitions:
            raise PatchError("unknown_patch")
        current = self.entry.subentries.get(patch_id)
        if current is None:
            raise PatchError("unknown_patch")
        if current.data.get("enabled", True) is not True:
            raise PatchError("disabled_patch")
        if not self.matches_entry():
            raise PatchError("runtime_reloading")

    async def async_action(self, patch_id: str, action: str) -> ReconcileResult:
        if self.closing:
            raise PatchError("runtime_closing")
        self._validate_current(patch_id)
        task = self.hass.async_create_background_task(
            self._execute_action(patch_id, action), f"{DOMAIN} admitted action"
        )
        self._admitted.add(task)
        task.add_done_callback(self._admitted.discard)
        # A cancelled caller cannot abandon an in-flight commit or its state write.
        return await asyncio.shield(task)

    async def _execute_action(self, patch_id: str, action: str) -> ReconcileResult:
        task = asyncio.current_task()
        assert task is not None
        try:
            async with self._lock:
                # Configuration can change while admitted work waits its turn.
                self._validate_current(patch_id)
                self._busy.add(patch_id)
                if action == "revert":
                    self._disable_auto_apply(patch_id)
                definition, state = self.definitions[patch_id], self.states[patch_id]
                if not definition.enabled:
                    raise PatchError("disabled_patch")
                pending = state.last_error == "durability_unconfirmed"
                try:
                    source = await self.source.load(definition)
                    result = await self.run_io(
                        partial(
                            self.reconciler.run, definition, source, action, self.retention, pending
                        )
                    )
                except PatchError as error:
                    status, reason = (
                        (Status.APPLY_ERROR, "durability_unconfirmed")
                        if pending
                        else (error.status, error.reason)
                    )
                    result = ReconcileResult(
                        PatchInspection(status, reason), "", service_error=reason
                    )
                state.status = result.inspection.status
                state.last_error = result.inspection.reason
                state.last_checked_at = datetime.now(UTC).isoformat()
                state.target_sha256 = result.target_sha256
                state.patch_sha256 = result.source_sha256 or None
                if result.mutated:
                    if action != "revert":
                        state.last_applied_at = state.last_checked_at
                    if definition.target_path.endswith(".py"):
                        self.hass.data[DOMAIN]["restart_required"].add(patch_id)
                        state.restart_may_be_required = True
                    _LOGGER.info("patch_bytes_changed: %s", patch_id)
                elif result.service_error:
                    _LOGGER.warning("patch_check_failed: %s %s", patch_id, result.service_error)
                else:
                    _LOGGER.debug("patch_checked: %s %s", patch_id, state.status)
                await self.store.save(self.states)
                self._publish(patch_id)
                return result
        finally:
            self._admitted.discard(task)
            self._busy.discard(patch_id)
            self.watcher.action_complete(patch_id)

    async def async_close(self):
        self.closing = True
        async with self._close_lock:
            if self._closed:
                return
            await self.watcher.async_close()
            tasks = self._admitted | self._background
            if tasks:
                await asyncio.gather(
                    *(asyncio.shield(task) for task in tasks), return_exceptions=True
                )
            if self._workers:
                await asyncio.gather(
                    *(asyncio.shield(worker) for worker in self._workers), return_exceptions=True
                )
            await self.store.save(self.states)
            for key in self.definitions:
                subentry = self.entry.subentries.get(key)
                if subentry is None or not subentry.data.get("enabled", True):
                    self.issues.clear(key)
            self._closed = True
