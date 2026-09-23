"""Narrow grouped watches, loop-owned debounce, root recovery and clean teardown."""

import asyncio
import os
from datetime import timedelta
from functools import partial
from pathlib import Path

from homeassistant.helpers.event import async_track_time_interval
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.utils.patterns import match_any_paths

from .models import PatchError, relative_parts
from .safe_io import GuardedDirectory


def _root_identity(config_dir: Path, root: str):
    try:
        with GuardedDirectory(config_dir, relative_parts(root)) as directory:
            info = os.fstat(directory.fd)
            return info.st_dev, info.st_ino
    except (OSError, PatchError):
        return None


class _Handler(FileSystemEventHandler):
    def __init__(self, owner):
        self.owner = owner

    def on_any_event(self, event):
        if event.event_type in {"created", "modified", "deleted", "closed", "moved"}:
            self.owner.runtime.hass.loop.call_soon_threadsafe(
                self.owner.handle_event,
                os.fsdecode(event.src_path),
                os.fsdecode(getattr(event, "dest_path", "")),
                event.is_directory,
                event.event_type,
            )


class PatchWatcher:
    def __init__(self, runtime):
        self.runtime = runtime
        self.config_dir = Path(runtime.hass.config.config_dir)
        self.roots = {
            definition.watch_root
            for definition in runtime.definitions.values()
            if definition.enabled
        }
        self.observer = Observer()
        self._handler = _Handler(self)
        self._watches = {}
        self._refresh_lock = asyncio.Lock()
        self._refresh_tasks: set[asyncio.Task] = set()
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._dirty: set[str] = set()
        self._closed = False
        self._cancel_interval = None

    async def async_start(self):
        if not self.roots:
            return
        await self.runtime.run_io(self.observer.start)
        await self.async_refresh(reconcile_recovered=False)
        self._cancel_interval = async_track_time_interval(
            self.runtime.hass, self._periodic_refresh, timedelta(seconds=60)
        )

    async def _periodic_refresh(self, _now):
        await self.async_refresh()

    async def async_refresh(self, *, reconcile_recovered: bool = True):
        async with self._refresh_lock:
            if self._closed:
                return
            for root in sorted(self.roots):
                identity = await self.runtime.run_io(partial(_root_identity, self.config_dir, root))
                previous = self._watches.get(root)
                if previous is not None and previous[1] == identity:
                    continue
                if previous is not None:
                    try:
                        await self.runtime.run_io(partial(self.observer.unschedule, previous[0]))
                    except KeyError:
                        pass
                    self._watches.pop(root, None)
                available = False
                if identity is not None:
                    try:
                        watch = await self.runtime.run_io(
                            partial(
                                self.observer.schedule,
                                self._handler,
                                str(self.config_dir / root),
                                recursive=True,
                            )
                        )
                    except OSError:
                        pass
                    else:
                        self._watches[root] = (watch, identity)
                        available = True
                for key, definition in self.runtime.definitions.items():
                    if definition.watch_root == root and definition.enabled:
                        self.runtime.watch_available(key, available)
                        if available and reconcile_recovered:
                            self._debounce(key)

    def _relative(self, value: str) -> str | None:
        if not value:
            return None
        try:
            return Path(value).relative_to(self.config_dir).as_posix()
        except ValueError:
            return None

    def handle_event(self, source: str, destination: str, is_directory: bool, event_type: str):
        """Called only on HA's loop; observer threads only enqueue immutable paths."""
        if self._closed or self.runtime.closing:
            return
        paths = {self._relative(source), self._relative(destination)} - {None}
        if is_directory:
            if event_type in {"created", "deleted", "moved"}:
                task = self.runtime.hass.async_create_background_task(
                    self.async_refresh(), "hapatchy watch roots"
                )
                self._refresh_tasks.add(task)
                task.add_done_callback(self._refresh_tasks.discard)
            return
        for key, definition in self.runtime.definitions.items():
            if not definition.enabled or definition.target_path not in paths:
                continue
            relative = definition.target_path[len(definition.watch_root) + 1 :]
            if match_any_paths(
                [relative], included_patterns=[definition.watch_pattern], case_sensitive=True
            ):
                self._debounce(key)

    def _debounce(self, patch_id: str):
        if self._closed:
            return
        if handle := self._pending.pop(patch_id, None):
            handle.cancel()
        if patch_id in self._running or self.runtime.busy(patch_id):
            self._dirty.add(patch_id)
            return
        delay = self.runtime.definitions[patch_id].debounce_seconds
        self._pending[patch_id] = self.runtime.hass.loop.call_later(delay, self._fire, patch_id)

    def _fire(self, patch_id: str):
        self._pending.pop(patch_id, None)
        if self._closed or self.runtime.closing:
            return
        if self.runtime.busy(patch_id):
            self._dirty.add(patch_id)
            return
        task = self.runtime.hass.async_create_background_task(
            self._check(patch_id), "hapatchy watched patch"
        )
        self._running[patch_id] = task

    async def _check(self, patch_id: str):
        try:
            await self.runtime.async_action(patch_id, "reconcile")
        except PatchError as error:
            if error.reason not in {
                "unknown_patch",
                "disabled_patch",
                "runtime_closing",
                "runtime_reloading",
            }:
                raise
        finally:
            self._running.pop(patch_id, None)
            self.action_complete(patch_id)

    def action_complete(self, patch_id: str):
        if patch_id not in self._running and patch_id in self._dirty:
            self._dirty.discard(patch_id)
            self._debounce(patch_id)

    async def async_close(self):
        self._closed = True
        if self._cancel_interval:
            self._cancel_interval()
            self._cancel_interval = None
        for handle in self._pending.values():
            handle.cancel()
        self._pending.clear()
        self._dirty.clear()
        async with self._refresh_lock:
            if self.observer.is_alive():
                await self.runtime.run_io(self.observer.stop)
                await self.runtime.run_io(self.observer.join)
            self._watches.clear()
        tasks = set(self._running.values()) | self._refresh_tasks
        if tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)
