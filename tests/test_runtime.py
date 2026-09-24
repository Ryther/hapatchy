"""Native HA lifecycle with temporary configuration and real file transactions."""

import asyncio
import threading
from pathlib import Path

import pytest
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

DATA = {
    "name": "Example",
    "target_path": "scripts/a.py",
    "watch_root": "scripts",
    "source_type": "local",
    "source": "patches/a.patch",
    "reconcile_on_startup": False,
}
DIFF = b"--- a/scripts/a.py\n+++ b/scripts/a.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"


async def setup(hass, tmp_path, changes=None):
    assert Path("custom_components/hapatchy/coordinator.py").exists(), (
        "Runtime lifecycle is missing"
    )
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "patches").mkdir(exist_ok=True)
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\n")
    (tmp_path / "patches/a.patch").write_bytes(DIFF)
    entry = MockConfigEntry(
        domain="hapatchy",
        version=1,
        minor_version=1,
        data={},
        subentries_data=[
            {
                "subentry_type": "patch",
                "title": "Example",
                "unique_id": "scripts/a.py",
                "data": DATA | (changes or {}),
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry, entry.runtime_data, next(iter(entry.subentries))


async def test_sensor_is_bound_to_native_subentry(hass, tmp_path):
    entry, runtime, pid = await setup(hass, tmp_path)
    from homeassistant.helpers import entity_registry as er

    entities = [
        e for e in er.async_get(hass).entities.values() if e.config_entry_id == entry.entry_id
    ]
    assert len(entities) == 1
    assert entities[0].config_subentry_id == pid
    assert entities[0].device_id is None
    assert hass.states.get(entities[0].entity_id).state == "unknown"
    await runtime.async_action(pid, "apply")
    assert hass.states.get(entities[0].entity_id).state == "applied"
    assert runtime.states[pid].restart_may_be_required


async def test_startup_reconciles_only_when_requested(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path, {"reconcile_on_startup": True})
    assert runtime.states[pid].status == "applied"
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nnew\n"


async def test_disabled_patch_stays_visible_and_cannot_apply(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path, {"enabled": False, "reconcile_on_startup": True})
    assert runtime.states[pid].status == "disabled"
    with pytest.raises(ValueError, match="disabled_patch"):
        await runtime.async_action(pid, "apply")
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_revert_persists_auto_apply_false_even_when_not_applied(hass, tmp_path):
    entry, runtime, pid = await setup(hass, tmp_path)
    result = await runtime.async_action(pid, "revert")
    assert result.service_error == "not_applied"
    assert entry.subentries[pid].data["auto_apply"] is False
    assert runtime.definitions[pid].auto_apply is False
    await hass.async_block_till_done()
    assert entry.runtime_data is runtime
    await runtime.async_action(pid, "reconcile")
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_conflict_repair_clears_only_after_resolution(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path)
    (tmp_path / "scripts/a.py").write_bytes(b"context\nupstream\n")
    await runtime.async_action(pid, "reconcile")
    assert ir.async_get(hass).async_get_issue("hapatchy", f"patch_{pid}") is not None
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\n")
    await runtime.async_action(pid, "reconcile")
    assert ir.async_get(hass).async_get_issue("hapatchy", f"patch_{pid}") is None


async def test_source_failure_cannot_reuse_old_patch(hass, tmp_path):
    _, runtime, pid = await setup(hass, tmp_path, {"auto_apply": False})
    await runtime.async_action(pid, "reconcile")
    (tmp_path / "patches/a.patch").unlink()
    await runtime.async_action(pid, "apply")
    assert runtime.states[pid].status == "source_error"
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_unload_waits_for_admitted_executor_transaction(hass, tmp_path, monkeypatch):
    entry, runtime, pid = await setup(hass, tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = runtime.reconciler.run

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(runtime.reconciler, "run", blocked)
    task = asyncio.create_task(runtime.async_action(pid, "apply"))
    assert await asyncio.to_thread(entered.wait, 2)
    unload = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
    try:
        await asyncio.sleep(0.02)
        assert not unload.done()
        with pytest.raises(ValueError, match="runtime_closing"):
            await runtime.async_action(pid, "apply")
    finally:
        release.set()
    await task
    assert await unload
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nnew\n"


async def test_metadata_round_trip_and_redaction(hass, tmp_path, hass_storage):
    entry, runtime, pid = await setup(hass, tmp_path)
    await runtime.async_action(pid, "apply")
    saved = hass_storage[f"hapatchy.{entry.entry_id}"]["data"][pid]
    assert saved["last_applied_at"]
    assert len(saved["target_sha256"]) == 64
    assert "source" not in saved and "target_path" not in saved


async def test_future_major_config_is_not_rewritten(hass, tmp_path):
    assert Path("custom_components/hapatchy/coordinator.py").exists(), (
        "Runtime lifecycle is missing"
    )
    entry = MockConfigEntry(domain="hapatchy", version=99, data={"future": "preserve"})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.version == 99 and entry.data == {"future": "preserve"}


async def test_cancelled_caller_does_not_abandon_commit_result(hass, tmp_path, monkeypatch):
    _, runtime, pid = await setup(hass, tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = runtime.reconciler.run

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(runtime.reconciler, "run", blocked)
    caller = asyncio.create_task(runtime.async_action(pid, "apply"))
    assert await asyncio.to_thread(entered.wait, 2)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    closing = asyncio.create_task(runtime.async_close())
    try:
        await asyncio.sleep(0.01)
        assert not closing.done()
    finally:
        release.set()
    await closing
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nnew\n"
    assert runtime.states[pid].status == "applied"
    assert runtime.states[pid].last_applied_at


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_native_disable_closes_admission_before_reload_runs(hass, tmp_path):
    entry, runtime, pid = await setup(hass, tmp_path)
    hass.config_entries.async_update_subentry(
        entry, entry.subentries[pid], data=dict(entry.subentries[pid].data) | {"enabled": False}
    )
    with pytest.raises(ValueError, match="disabled_patch|runtime_closing"):
        await runtime.async_action(pid, "apply")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.states[pid].status == "disabled"
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_native_remove_closes_admission_and_preserves_files(hass, tmp_path):
    entry, runtime, pid = await setup(hass, tmp_path)
    hass.config_entries.async_remove_subentry(entry, pid)
    with pytest.raises(ValueError, match="unknown_patch|runtime_closing"):
        await runtime.async_action(pid, "apply")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert not entry.runtime_data.definitions
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_durability_flag_survives_reload(hass, tmp_path, monkeypatch, hass_storage):
    from custom_components.hapatchy.atomic_writer import CommitError

    entry, runtime, pid = await setup(hass, tmp_path, {"backup_before_apply": False})
    commit = runtime.reconciler.writer.commit

    def failed_after_replace(*args, **kwargs):
        commit(*args, **kwargs)
        raise CommitError("durability_unconfirmed", replaced=True)

    monkeypatch.setattr(runtime.reconciler.writer, "commit", failed_after_replace)
    result = await runtime.async_action(pid, "apply")
    assert result.inspection.status == "apply_error"
    assert (
        hass_storage[f"hapatchy.{entry.entry_id}"]["data"][pid]["last_error"]
        == "durability_unconfirmed"
    )
    inode = (tmp_path / "scripts/a.py").stat().st_ino
    assert await hass.config_entries.async_reload(entry.entry_id)
    runtime = entry.runtime_data
    assert runtime.states[pid].status == "apply_error"
    assert runtime.states[pid].last_error == "durability_unconfirmed"
    await runtime.async_action(pid, "reconcile")
    assert runtime.states[pid].status == "applied"
    assert (tmp_path / "scripts/a.py").stat().st_ino == inode


async def test_corrupt_metadata_rebuild_preserves_backups(hass, tmp_path, hass_storage, caplog):
    assert Path("custom_components/hapatchy/coordinator.py").exists()
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "patches").mkdir()
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\n")
    (tmp_path / "patches/a.patch").write_bytes(DIFF)
    sentinel = tmp_path / ".hapatchy/backups/unrelated/sentinel"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"keep")
    entry = MockConfigEntry(
        domain="hapatchy",
        version=1,
        minor_version=1,
        data={},
        subentries_data=[
            {
                "subentry_type": "patch",
                "title": "Example",
                "unique_id": "scripts/a.py",
                "data": DATA | {"reconcile_on_startup": True},
            }
        ],
    )
    entry.add_to_hass(hass)
    key = f"hapatchy.{entry.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": "do-not-log-secret"}
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    pid = next(iter(entry.subentries))
    assert entry.runtime_data.states[pid].status == "applied"
    assert sentinel.read_bytes() == b"keep"
    owned_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components.hapatchy")
    )
    assert "metadata_invalid" in owned_logs and "do-not-log-secret" not in owned_logs


async def test_failed_setup_releases_runtime_for_retry(hass, tmp_path, monkeypatch):
    from custom_components.hapatchy.coordinator import PatchManagerRuntime

    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain="hapatchy", version=1, data={})
    entry.add_to_hass(hass)
    started = []
    original = PatchManagerRuntime.async_start

    async def fail_once(runtime):
        started.append(runtime)
        raise OSError("injected start failure")

    monkeypatch.setattr(PatchManagerRuntime, "async_start", fail_once)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert started[0].closing
    assert "runtime" not in hass.data["hapatchy"]
    monkeypatch.setattr(PatchManagerRuntime, "async_start", original)
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.runtime_data is not started[0]


async def test_failed_platform_unload_leaves_runtime_usable(hass, tmp_path, monkeypatch):
    from custom_components.hapatchy import async_unload_entry

    entry, runtime, pid = await setup(hass, tmp_path)

    async def refuse(*args):
        return False

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", refuse)
    assert not await async_unload_entry(hass, entry)
    assert not runtime.closing
    assert runtime.watcher.observer.is_alive()
    await runtime.async_action(pid, "apply")
    assert runtime.states[pid].status == "applied"


@pytest.mark.parametrize("change", ["disable", "edit", "remove"])
async def test_queued_revert_cannot_overwrite_native_edit(hass, tmp_path, change):
    entry, runtime, pid = await setup(hass, tmp_path)
    await runtime._lock.acquire()
    pending = asyncio.create_task(runtime.async_action(pid, "revert"))
    await asyncio.sleep(0)
    edited = dict(entry.subentries[pid].data) | {"name": "New title"}
    if change == "disable":
        edited["enabled"] = False
    if change == "remove":
        hass.config_entries.async_remove_subentry(entry, pid)
    else:
        hass.config_entries.async_update_subentry(entry, entry.subentries[pid], data=edited)
    runtime._lock.release()
    with pytest.raises(ValueError, match="disabled_patch|runtime_reloading|unknown_patch"):
        await pending
    await hass.async_block_till_done(wait_background_tasks=True)
    if change == "remove":
        assert pid not in entry.subentries
    else:
        assert entry.subentries[pid].data == edited
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


@pytest.mark.parametrize("reload_during_save", [False, True])
async def test_reconfigure_save_excludes_old_definition_apply(
    hass, tmp_path, monkeypatch, reload_during_save
):
    """An action admitted while a revision is saved cannot write the old definition."""
    from custom_components.hapatchy.managed_source import ManagedPatchStore

    entry, runtime, pid = await setup(hass, tmp_path, {"auto_apply": False})
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "reconfigure", "subentry_id": pid}
    )
    fields = DATA | {"source_type": "managed"}
    fields.pop("source")
    fields.pop("reconcile_on_startup")
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], fields)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"patch_text": DIFF.decode().replace("+new", "+newer")}
    )
    entered, release = threading.Event(), threading.Event()
    original_save = ManagedPatchStore.save

    def blocked_save(store, data):
        entered.set()
        assert release.wait(5)
        return original_save(store, data)

    monkeypatch.setattr(ManagedPatchStore, "save", blocked_save)
    saving = asyncio.create_task(
        hass.config_entries.subentries.async_configure(
            result["flow_id"], {"auto_apply": False, "reconcile_on_startup": False}
        )
    )
    assert await asyncio.to_thread(entered.wait, 2)
    applying = asyncio.create_task(runtime.async_action(pid, "apply"))
    await asyncio.sleep(0)
    reloading = (
        asyncio.create_task(hass.config_entries.async_reload(entry.entry_id))
        if reload_during_save
        else None
    )
    try:
        await asyncio.sleep(0)
        assert not applying.done()
        if reloading:
            await asyncio.sleep(0)
            assert not reloading.done()
        assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
    finally:
        release.set()
    result = await saving
    if reloading:
        assert result["errors"] == {"base": "runtime_reloading"}
        await applying
        await reloading
        assert entry.subentries[pid].data["source_type"] == "local"
        return
    assert result["reason"] == "reconfigure_successful"
    with pytest.raises(ValueError, match="runtime_reloading|runtime_closing"):
        await applying
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
    assert entry.subentries[pid].data["source_type"] == "managed"
