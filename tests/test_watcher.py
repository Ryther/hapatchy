"""Actual filesystem events plus deterministic debounce and recovery checks."""

import asyncio
import os
from pathlib import Path

import pytest

from tests.test_runtime import setup


async def ready(runtime, pid, status):
    for _ in range(80):
        if runtime.states[pid].status == status:
            return
        await asyncio.sleep(0.025)
    assert runtime.states[pid].status == status


def watcher(runtime):
    assert Path("custom_components/hapatchy/watcher.py").exists(), "Watch lifecycle is missing"
    return runtime.watcher


async def test_burst_debounce_and_own_event_converge(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    owner = watcher(runtime)
    for _ in range(5):
        owner.handle_event(str(tmp_path / "scripts/a.py"), "", False, "modified")
    await ready(runtime, pid, "applied")
    await asyncio.sleep(0.3)
    assert len(list((tmp_path / ".hapatchy/backups" / pid).iterdir())) == 1
    assert runtime.states[pid].watcher_available


async def test_unrelated_event_does_not_reconcile(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    owner = watcher(runtime)
    owner.handle_event(str(tmp_path / "scripts/other.py"), "", False, "modified")
    await asyncio.sleep(0.2)
    assert runtime.states[pid].status == "unknown"
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_real_move_over_replacement(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    watcher(runtime)
    await runtime.async_action(pid, "apply")
    temporary = tmp_path / "scripts/updater.tmp"
    temporary.write_bytes(b"context\nold\nupstream addition\n")
    os.replace(temporary, tmp_path / "scripts/a.py")
    for _ in range(80):
        if (tmp_path / "scripts/a.py").read_bytes() == b"context\nnew\nupstream addition\n":
            break
        await asyncio.sleep(0.025)
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nnew\nupstream addition\n"
    assert len(list((tmp_path / ".hapatchy/backups" / pid).iterdir())) == 2


async def test_missing_root_is_restored_without_broad_watch(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    owner = watcher(runtime)
    (tmp_path / "scripts/a.py").unlink()
    (tmp_path / "scripts").rmdir()
    await owner.async_refresh()
    assert not runtime.states[pid].watcher_available
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\n")
    await owner.async_refresh()
    await ready(runtime, pid, "applied")
    assert runtime.states[pid].watcher_available
    assert set(owner.roots) == {"scripts"}


async def test_unload_cancels_pending_debounce(hass, tmp_path):
    entry, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.2})
    owner = watcher(runtime)
    owner.handle_event(str(tmp_path / "scripts/a.py"), "", False, "modified")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await asyncio.sleep(0.25)
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
    assert not owner.observer.is_alive()


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_events_during_manual_commit_get_one_follow_up(hass, tmp_path, monkeypatch):
    import threading

    _, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    owner = watcher(runtime)
    entered, release = threading.Event(), threading.Event()
    calls = []
    original = runtime.reconciler.run

    def recorded(*args):
        calls.append(args[2])
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(runtime.reconciler, "run", recorded)
    task = asyncio.create_task(runtime.async_action(pid, "apply"))
    assert await asyncio.to_thread(entered.wait, 2)
    try:
        for _ in range(5):
            owner.handle_event(str(tmp_path / "scripts/a.py"), "", False, "modified")
    finally:
        release.set()
    await task
    await asyncio.sleep(0.4)
    assert calls == ["apply", "reconcile"]
    assert len(list((tmp_path / ".hapatchy/backups" / pid).iterdir())) == 1


async def test_two_roots_reload_and_reconcile_independently(hass, tmp_path):
    from types import MappingProxyType

    from homeassistant.config_entries import ConfigSubentry

    from tests.test_runtime import DATA, DIFF

    entry, old, first = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    watcher(old)
    (tmp_path / "other").mkdir()
    (tmp_path / "other/b.py").write_bytes(b"context\nold\n")
    (tmp_path / "patches/b.patch").write_bytes(DIFF.replace(b"scripts/a.py", b"other/b.py"))
    sub = ConfigSubentry(
        subentry_type="patch",
        title="Second",
        unique_id="other/b.py",
        data=MappingProxyType(
            DATA
            | {
                "target_path": "other/b.py",
                "watch_root": "other",
                "source": "patches/b.patch",
                "debounce_seconds": 0.1,
            }
        ),
    )
    hass.config_entries.async_add_subentry(entry, sub)
    await hass.async_block_till_done(wait_background_tasks=True)
    runtime = entry.runtime_data
    owner = watcher(runtime)
    assert runtime is not old and not old.watcher.observer.is_alive()
    assert owner.roots == {"scripts", "other"}
    assert len(owner.observer.emitters) == 2
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\nfirst suffix\n")
    (tmp_path / "other/b.py").write_bytes(b"context\nold\nsecond suffix\n")
    await ready(runtime, first, "applied")
    await ready(runtime, sub.subentry_id, "applied")
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nnew\nfirst suffix\n"
    assert (tmp_path / "other/b.py").read_bytes() == b"context\nnew\nsecond suffix\n"


async def test_periodic_recovery_after_root_event_is_lost(hass, tmp_path, monkeypatch):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    _, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    owner = watcher(runtime)
    # Simulate losing all observer events during an upstream directory replacement.
    monkeypatch.setattr(owner, "handle_event", lambda *args: None)
    (tmp_path / "scripts").rename(tmp_path / "old_scripts")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\n")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done(wait_background_tasks=True)
    await ready(runtime, pid, "applied")
    assert runtime.states[pid].watcher_available
    assert (tmp_path / "old_scripts/a.py").read_bytes() == b"context\nold\n"
