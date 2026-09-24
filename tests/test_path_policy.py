"""Frozen YAML grants remain mandatory at every backend entry point."""

import pytest

from custom_components.hapatchy.models import PatchError
from tests.policy_helpers import grant_directories

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def test_frozen_grants_intersect_live_ha_permission(hass, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/file.py").write_text("original")
    gate = grant_directories(tmp_path, hass=hass)
    gate.check_path("scripts/file.py")
    hass.config.allowlist_external_dirs = set()
    with pytest.raises(PatchError, match="ha_path_not_allowed"):
        gate.check_path("scripts/file.py")


def test_missing_boot_policy_denies_direct_calls(hass, tmp_path):
    from custom_components.hapatchy.yaml_policy import policy_for_hass

    hass.config.config_dir = str(tmp_path)
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    with pytest.raises(PatchError, match="configuration_source_unavailable"):
        policy_for_hass(hass).check_path("scripts/file.py")


@pytest.mark.parametrize("grant", [".", "", "/config", "../outside", "scripts/../other", "scripts/", "scripts/*", ".storage", ".hapatchy", "custom_components/hapatchy"])
def test_bad_yaml_grants_fail_closed(tmp_path, grant):
    from custom_components.hapatchy.yaml_policy import validate_hapatchy_directories

    with pytest.raises(PatchError, match="hapatchy_yaml_invalid"):
        validate_hapatchy_directories({"allowed_directories": [grant]})


def test_component_prefix_and_watch_scope(hass, tmp_path):
    from tests.test_sources import definition

    gate = grant_directories(tmp_path, ("scripts/nested", "custom_components"), hass=hass)
    gate.check_path("scripts/nested/missing.py")
    with pytest.raises(PatchError, match="hapatchy_path_not_allowed"):
        gate.check_path("scripts_other/file.py")
    with pytest.raises(PatchError, match="protected_path"):
        gate.check_path("custom_components/hapatchy/config_flow.py")
    with pytest.raises(PatchError, match="hapatchy_path_not_allowed"):
        gate.check_definition(definition(target_path="scripts/nested/file.py", watch_root="scripts"))


@pytest.mark.parametrize("action", ["apply", "revert", "reconcile", "refresh_source"])
@pytest.mark.parametrize("deny", ["ha", "changed", "missing"])
async def test_runtime_refuses_revoked_permission(hass, tmp_path, action, deny):
    from homeassistant.core import Context
    from homeassistant.exceptions import ServiceValidationError

    from tests.test_runtime import setup

    entry, runtime, pid = await setup(hass, tmp_path)
    if action == "revert":
        await runtime.async_action(pid, "apply")
    before = (tmp_path / "scripts/a.py").read_bytes()
    if deny == "ha":
        hass.config.allowlist_external_dirs = set()
    elif deny == "changed":
        (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")
    else:
        (tmp_path / "configuration.yaml").unlink()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "hapatchy", action, {"patch_id": pid}, blocking=True, context=Context()
        )
    assert runtime.states[pid].status == "security_error"
    assert (tmp_path / "scripts/a.py").read_bytes() == before
    if action == "revert":
        assert entry.subentries[pid].data.get("auto_apply", True) is True
        assert runtime.definitions[pid].auto_apply is True
    await runtime.watcher.async_refresh()
    assert not runtime.states[pid].watcher_available


async def test_watch_event_checks_source_snapshot(hass, tmp_path):
    from tests.test_runtime import setup
    from tests.test_watcher import ready

    _, runtime, pid = await setup(hass, tmp_path, {"debounce_seconds": 0.1})
    (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")
    runtime.watcher.handle_event(str(tmp_path / "scripts/a.py"), "", False, "modified")
    await ready(runtime, pid, "security_error")
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


def test_source_change_during_backup_blocks_replace(hass, tmp_path, monkeypatch):
    from custom_components.hapatchy.backup import BackupManager
    from custom_components.hapatchy.reconciler import Reconciler
    from tests.test_reconciler import DIFF, definition

    (tmp_path / "scripts").mkdir()
    target = tmp_path / "scripts/a.py"
    target.write_bytes(b"context\nold\n")
    gate = grant_directories(tmp_path, hass=hass)
    original = BackupManager.create

    def change_source(*args, **kwargs):
        result = original(*args, **kwargs)
        (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")
        return result

    monkeypatch.setattr(BackupManager, "create", change_source)
    result = Reconciler(tmp_path, gate).run(definition(), DIFF, "apply", 10, False)
    assert result.inspection.status == "security_error"
    assert not result.mutated and target.read_bytes() == b"context\nold\n"


async def test_late_denied_revert_keeps_target_and_auto_apply(hass, tmp_path, monkeypatch):
    from custom_components.hapatchy.backup import BackupManager
    from tests.test_runtime import setup

    entry, runtime, pid = await setup(hass, tmp_path)
    assert (await runtime.async_action(pid, "apply")).mutated
    target = tmp_path / "scripts/a.py"
    backup_root = tmp_path / ".hapatchy/backups" / pid
    prior_backups = {path.relative_to(backup_root): path.read_bytes() for path in backup_root.rglob("*") if path.is_file()}
    original = BackupManager.create

    def change_source(*args, **kwargs):
        result = original(*args, **kwargs)
        (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")
        return result

    monkeypatch.setattr(BackupManager, "create", change_source)
    result = await runtime.async_action(pid, "revert")
    assert result.inspection.status == "security_error"
    assert not result.mutated and target.read_bytes() == b"context\nnew\n"
    assert all((backup_root / name).read_bytes() == data for name, data in prior_backups.items())
    assert entry.subentries[pid].data.get("auto_apply", True) is True
    assert runtime.definitions[pid].auto_apply is True


async def test_denial_precedes_https_fetch(hass, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from tests.test_runtime import setup

    _, runtime, pid = await setup(
        hass, tmp_path, {"source_type": "url", "source": "https://example.test/patch"}
    )
    fetch = AsyncMock()
    monkeypatch.setattr(runtime.source, "load", fetch)
    (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")
    result = await runtime.async_action(pid, "apply")
    assert result.inspection.status == "security_error"
    fetch.assert_not_called()


def test_picker_intersects_both_allowlists(hass, tmp_path):
    from custom_components.hapatchy.target_picker import list_targets

    for name in ["scripts/allowed/a.py", "scripts/blocked/b.py", "other/c.py"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("text")
    gate = grant_directories(tmp_path, ("scripts",), hass=hass)
    hass.config.allowlist_external_dirs = {str(tmp_path / "scripts/allowed")}
    assert list_targets(tmp_path, gate) == ["scripts/allowed/a.py"]


@pytest.mark.parametrize("target", [".storage/auth", "configuration.yaml", "custom_components/hapatchy/manifest.json"])
def test_policy_cannot_authorize_protected_targets(hass, tmp_path, target):
    gate = grant_directories(tmp_path, ("custom_components", "scripts"), hass=hass)
    with pytest.raises(PatchError, match="protected_path"):
        gate.check_path(target)


async def test_security_denial_redacts_diagnostics_repairs_and_sensor(hass, tmp_path):
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import issue_registry as ir

    from custom_components.hapatchy.diagnostics import async_get_config_entry_diagnostics
    from tests.test_runtime import setup

    entry, runtime, pid = await setup(hass, tmp_path)
    (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")
    await runtime.async_action(pid, "apply")
    report = await async_get_config_entry_diagnostics(hass, entry)
    patch = report["patches"][0]
    assert patch["definition"] == {"source_type": "local", "enabled": True}
    assert "target_sha256" not in patch["state"]
    issue = ir.async_get(hass).async_get_issue("hapatchy", f"patch_{pid}")
    assert issue is not None
    assert not issue.translation_placeholders
    entity = next(e for e in er.async_get(hass).entities.values() if e.config_subentry_id == pid)
    attributes = hass.states.get(entity.entity_id).attributes
    assert "target_path" not in attributes and "target_sha256" not in attributes


async def test_revert_metadata_failure_suppresses_watcher_reapply(hass, tmp_path, monkeypatch):
    from tests.test_runtime import setup

    entry, runtime, pid = await setup(hass, tmp_path)
    assert (await runtime.async_action(pid, "apply")).mutated
    update_subentry = hass.config_entries.async_update_subentry

    def fail_persistence(*args, **kwargs):
        raise OSError("simulated persistence failure")

    monkeypatch.setattr(hass.config_entries, "async_update_subentry", fail_persistence)
    result = await runtime.async_action(pid, "revert")
    assert result.inspection.status == "apply_error"
    assert result.service_error == "revert_metadata_unavailable"
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
    runtime.watcher.handle_event(str(tmp_path / "scripts/a.py"), "", False, "modified")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert pid not in runtime.watcher._pending
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
    monkeypatch.setattr(hass.config_entries, "async_update_subentry", update_subentry)
    assert await hass.config_entries.async_reload(entry.entry_id)
    runtime = entry.runtime_data
    assert pid in runtime._suppress_reapply
    with pytest.raises(PatchError, match="revert_metadata_unavailable"):
        await runtime.async_action(pid, "reconcile")
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
