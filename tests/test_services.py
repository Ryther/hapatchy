"""Service permissions, strict payloads, durable configuration and redaction."""

import json
from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.core import Context
from homeassistant.exceptions import ServiceValidationError, Unauthorized

from tests.test_runtime import setup

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def require_services():
    assert Path("custom_components/hapatchy/services.py").exists(), "Native services are missing"


async def call(hass, pid, action="apply", **kwargs):
    return await hass.services.async_call(
        "hapatchy", action, {"patch_id": pid}, blocking=True, **kwargs
    )


async def test_admin_apply_and_persistent_revert(hass, tmp_path, hass_admin_user):
    require_services()
    entry, runtime, pid = await setup(hass, tmp_path)
    context = Context(user_id=hass_admin_user.id)
    await call(hass, pid, context=context)
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nnew\n"
    applied_at = runtime.states[pid].last_applied_at
    await call(hass, pid, "revert", context=context)
    assert runtime.states[pid].last_applied_at == applied_at
    assert entry.subentries[pid].data["auto_apply"] is False
    await call(hass, pid, "reconcile", context=context)
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
    assert len(list((tmp_path / ".hapatchy/backups" / pid).iterdir())) == 2


async def test_non_admin_cannot_mutate(hass, tmp_path, hass_read_only_user):
    require_services()
    _, _, pid = await setup(hass, tmp_path)
    with pytest.raises(Unauthorized):
        await call(hass, pid, context=Context(user_id=hass_read_only_user.id))
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_admin_reads_current_diff_only_on_request(hass, tmp_path, hass_admin_user):
    _, _, pid = await setup(hass, tmp_path)
    before = (tmp_path / "scripts/a.py").read_bytes()
    response = await hass.services.async_call(
        "hapatchy", "get_patch", {"patch_id": pid}, blocking=True,
        return_response=True, context=Context(user_id=hass_admin_user.id),
    )
    assert response == {"patch_id": pid, "patch": "--- a/scripts/a.py\n+++ b/scripts/a.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"}
    assert (tmp_path / "scripts/a.py").read_bytes() == before
    assert all("--- a/scripts/a.py" not in str(state) for state in hass.states.async_all())


async def test_trusted_internal_context_can_read_current_diff(hass, tmp_path):
    _, _, pid = await setup(hass, tmp_path)
    response = await hass.services.async_call(
        "hapatchy", "get_patch", {"patch_id": pid}, blocking=True,
        return_response=True, context=Context(),
    )
    assert response["patch_id"] == pid
    assert response["patch"].startswith("--- a/scripts/a.py\n")


async def test_patch_read_refuses_non_admin_and_revoked_grants(
    hass, tmp_path, hass_read_only_user, hass_admin_user
):
    _, _, pid = await setup(hass, tmp_path)
    request = {"patch_id": pid}
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "hapatchy", "get_patch", request, blocking=True, return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    hass.config.allowlist_external_dirs = set()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "hapatchy", "get_patch", request, blocking=True, return_response=True,
            context=Context(user_id=hass_admin_user.id),
        )


async def test_patch_read_refuses_source_that_stopped_being_a_patch(
    hass, tmp_path, hass_admin_user
):
    _, _, pid = await setup(hass, tmp_path)
    (tmp_path / "patches/a.patch").write_text("private content, not a diff\n")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "hapatchy", "get_patch", {"patch_id": pid}, blocking=True,
            return_response=True, context=Context(user_id=hass_admin_user.id),
        )
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_service_rejects_injected_source_and_unknown_patch(hass, tmp_path):
    require_services()
    _, _, pid = await setup(hass, tmp_path)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            "hapatchy",
            "apply",
            {"patch_id": pid, "source": "https://example.test/evil"},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await call(hass, "unknown")
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_refresh_source_never_applies(hass, tmp_path):
    require_services()
    _, runtime, pid = await setup(hass, tmp_path)
    await call(hass, pid, "refresh_source")
    assert runtime.states[pid].status == "applicable"
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_failed_revert_still_disables_auto_apply(hass, tmp_path):
    require_services()
    entry, _, pid = await setup(hass, tmp_path)
    with pytest.raises(ServiceValidationError):
        await call(hass, pid, "revert")
    assert entry.subentries[pid].data["auto_apply"] is False


async def test_services_removed_on_unload(hass, tmp_path):
    require_services()
    entry, _, _ = await setup(hass, tmp_path)
    assert hass.services.has_service("hapatchy", "apply")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service("hapatchy", "apply")


async def test_diagnostics_exclude_raw_source_and_patch(hass, tmp_path):
    assert Path("custom_components/hapatchy/diagnostics.py").exists(), "Diagnostics are missing"
    from custom_components.hapatchy.diagnostics import async_get_config_entry_diagnostics

    entry, _, _ = await setup(
        hass,
        tmp_path,
        {"source_type": "url", "source": "https://example.test/private.patch?token=private-secret"},
    )
    result = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(result)
    assert "example.test" in serialized
    assert "private-secret" not in serialized and "private.patch" not in serialized
    assert "https://" not in serialized and "context" not in serialized


async def test_batch_failure_does_not_prevent_other_patch(hass, tmp_path):
    from types import MappingProxyType

    from homeassistant.config_entries import ConfigSubentry

    from tests.test_runtime import DATA, DIFF

    require_services()
    entry, _, first = await setup(hass, tmp_path)
    (tmp_path / "scripts/b.py").write_bytes(b"context\nold\n")
    (tmp_path / "patches/b.patch").write_bytes(DIFF.replace(b"scripts/a.py", b"scripts/b.py"))
    sub = ConfigSubentry(
        subentry_type="patch",
        title="Second",
        unique_id="scripts/b.py",
        data=MappingProxyType(DATA | {"target_path": "scripts/b.py", "source": "patches/b.patch"}),
    )
    hass.config_entries.async_add_subentry(entry, sub)
    await hass.async_block_till_done(wait_background_tasks=True)
    (tmp_path / "patches/a.patch").unlink()
    await hass.services.async_call("hapatchy", "reconcile", {}, blocking=True)
    assert entry.runtime_data.states[first].status == "source_error"
    assert entry.runtime_data.states[sub.subentry_id].status == "applied"
    assert len(entry.runtime_data.watcher.observer.emitters) == 1
    assert (tmp_path / "scripts/a.py").read_bytes() == b"context\nold\n"
    assert (tmp_path / "scripts/b.py").read_bytes() == b"context\nnew\n"
