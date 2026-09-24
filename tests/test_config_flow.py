"""Native entry, subentry and retention UI behavior."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.policy_helpers import grant_directories

DOMAIN = "hapatchy"
DATA = {
    "name": "Example",
    "target_path": "scripts/a.py",
    "watch_root": "scripts",
    "source_type": "local",
    "source": "patches/a.patch",
}
DIFF = b"--- a/scripts/a.py\n+++ b/scripts/a.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"


async def configure(hass, flow_id, data):
    """Drive the external-source step when configuring a definition."""
    if "target_path" in data:
        data = dict(data)
        source = data.pop("source", "")
        result = await hass.config_entries.subentries.async_configure(flow_id, data)
        if result.get("step_id") == "source":
            return await hass.config_entries.subentries.async_configure(flow_id, {"source": source})
        return result
    return await hass.config_entries.subentries.async_configure(flow_id, data)


def require_flow():
    assert Path("custom_components/hapatchy/config_flow.py").exists(), (
        "Native configuration flow is missing"
    )


@pytest.fixture
def files(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    grant_directories(tmp_path, hass=hass)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "patches").mkdir()
    (tmp_path / "scripts/a.py").write_bytes(b"context\nold\n")
    (tmp_path / "patches/a.patch").write_bytes(DIFF)
    return tmp_path


async def test_single_entry(hass):
    require_flow()
    with patch(
        "custom_components.hapatchy.async_setup_entry",
        new=AsyncMock(return_value=True),
        create=True,
    ):
        first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert first["type"] == FlowResultType.FORM
        done = await hass.config_entries.flow.async_configure(first["flow_id"], {})
        assert done["type"] == FlowResultType.CREATE_ENTRY
        assert done["result"].unique_id == DOMAIN
        again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert again["type"] == FlowResultType.ABORT
        assert again["reason"] == "single_instance_allowed"
        await hass.async_block_till_done()


async def test_add_native_patch_subentry(hass, files):
    require_flow()
    entry = MockConfigEntry(domain=DOMAIN, version=1, minor_version=1, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    assert result["step_id"] == "user"
    result = await configure(hass, result["flow_id"], DATA)
    assert result["step_id"] == "options"
    result = await configure(hass, result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data["auto_apply"] is True
    assert subentry.data["watch_pattern"] == "a.py"
    assert subentry.unique_id == "scripts/a.py"
    assert (files / "scripts/a.py").read_bytes() == b"context\nold\n"


@pytest.mark.parametrize(
    "extra", [{"target_path": "../outside"}, {"watch_root": "."}, {"source": "scripts/a.py"}]
)
async def test_flow_rejects_unsafe_definition(hass, files, extra):
    require_flow()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(hass, result["flow_id"], DATA | extra)
    if result["step_id"] == "options":
        result = await configure(hass, result["flow_id"], {})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["base"]
    assert not entry.subentries


async def test_missing_target_and_disabled_backup_require_confirmation(hass, files):
    require_flow()
    (files / "scripts/a.py").unlink()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(hass, result["flow_id"], DATA)
    result = await configure(hass, result["flow_id"], {"backup_before_apply": False})
    assert result["step_id"] == "confirm_missing_target"
    result = await configure(hass, result["flow_id"], {"confirm": True})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert next(iter(entry.subentries.values())).data["backup_before_apply"] is False


@pytest.mark.parametrize("retention", [1, 100])
async def test_options_retention(hass, retention):
    require_flow()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"backup_retention": retention}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["backup_retention"] == retention


async def test_duplicate_disabled_target_is_rejected(hass, files):
    require_flow()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            {
                "subentry_type": "patch",
                "title": "Existing",
                "unique_id": "scripts/a.py",
                "data": DATA | {"enabled": False},
            }
        ],
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(hass, result["flow_id"], DATA)
    result = await configure(hass, result["flow_id"], {})
    assert result["errors"] == {"base": "duplicate_target"}
    assert len(entry.subentries) == 1


async def test_native_reconfigure_preserves_identity(hass, files):
    require_flow()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            {
                "subentry_type": "patch",
                "title": "Existing",
                "unique_id": "scripts/a.py",
                "data": DATA,
            }
        ],
    )
    entry.add_to_hass(hass)
    original = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "reconfigure", "subentry_id": original}
    )
    result = await configure(hass, result["flow_id"], DATA | {"name": "Updated"})
    result = await configure(hass, result["flow_id"], {"auto_apply": False})
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert list(entry.subentries) == [original]
    assert entry.subentries[original].data["auto_apply"] is False
    assert entry.subentries[original].title == "Updated"


async def test_denied_legacy_url_requires_remove_and_safe_readd(hass, files):
    legacy = DATA | {"source_type": "url", "source": "https://127.0.0.1/patch"}
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            {
                "subentry_type": "patch",
                "title": "Legacy",
                "unique_id": "scripts/a.py",
                "data": legacy,
            }
        ],
    )
    entry.add_to_hass(hass)
    old_id = next(iter(entry.subentries))
    original_bytes = (files / "scripts/a.py").read_bytes()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "reconfigure", "subentry_id": old_id}
    )
    result = await configure(
        hass,
        result["flow_id"],
        DATA | {"source_type": "managed", "source": ""},
    )
    assert result["step_id"] == "editor"
    result = await configure(hass, result["flow_id"], {"patch_text": DIFF.decode()})
    assert result["errors"] == {"base": "source_network_denied"}
    assert entry.subentries[old_id].data["source"] == legacy["source"]
    assert (files / "scripts/a.py").read_bytes() == original_bytes

    hass.config_entries.async_remove_subentry(entry, old_id)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(
        hass,
        result["flow_id"],
        DATA | {"source_type": "managed", "source": ""},
    )
    result = await configure(hass, result["flow_id"], {"patch_text": DIFF.decode()})
    result = await configure(hass, result["flow_id"], {"auto_apply": False})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert old_id not in entry.subentries
    assert next(iter(entry.subentries.values())).data["source_type"] == "managed"
    assert (files / "scripts/a.py").read_bytes() == original_bytes


@pytest.mark.parametrize("retention", [0, 101, 1.5, True, "10"])
async def test_options_reject_invalid_retention(hass, retention):
    require_flow()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"backup_retention": retention}
        )
    assert not entry.options


async def test_remote_flow_validates_fetched_diff(hass, files):
    require_flow()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.hapatchy.patch_source.PatchSourceClient.load",
        new=AsyncMock(return_value=DIFF),
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, "patch"), context={"source": "user"}
        )
        result = await configure(
            hass,
            result["flow_id"],
            DATA
            | {"source_type": "url", "source": "https://raw.githubusercontent.com/example/patch"},
        )
        result = await configure(hass, result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_bad_basic_fields_remain_editable(hass, files):
    require_flow()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(hass, result["flow_id"], DATA | {"watch_root": "."})
    assert result["step_id"] == "user"
    assert result["errors"]["base"] == "unsafe_path"


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_retention_form_can_be_serialized_for_native_ui(hass):
    from homeassistant.helpers.data_entry_flow import FlowManagerIndexView

    entry = MockConfigEntry(domain="hapatchy", version=1, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = FlowManagerIndexView(hass.config_entries.options)._prepare_result_json(result)[
        "data_schema"
    ]
    assert fields[0]["type"] == "integer"


async def test_managed_editor_defers_disk_write_until_save(hass, files):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(
        hass, result["flow_id"], DATA | {"source_type": "managed", "source": ""}
    )
    assert result["step_id"] == "editor"
    result = await configure(hass, result["flow_id"], {"patch_text": DIFF.decode()})
    assert result["step_id"] == "options"
    assert not (files / ".hapatchy/patches").exists()
    result = await configure(hass, result["flow_id"], {"auto_apply": False})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    from custom_components.hapatchy.managed_source import ManagedPatchStore

    data = next(iter(entry.subentries.values())).data
    assert data["source_type"] == "managed"
    assert ManagedPatchStore(files).load(data["source"]) == DIFF
    assert "patch_text" not in data and "file" not in data
    assert (files / "scripts/a.py").read_bytes() == b"context\nold\n"


async def test_editor_rejects_bad_patch_without_writing(hass, files):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(
        hass, result["flow_id"], DATA | {"source_type": "managed", "source": ""}
    )
    result = await configure(hass, result["flow_id"], {"patch_text": "not a patch"})
    assert result["step_id"] == "editor" and result["errors"]
    assert not (files / ".hapatchy/patches").exists() and not entry.subentries


async def test_managed_reconfigure_prefills_editor_and_preserves_old_revision(hass, files):
    from custom_components.hapatchy.managed_source import ManagedPatchStore

    owned = ManagedPatchStore(files)
    revision = owned.save(DIFF)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            {
                "subentry_type": "patch",
                "title": "Example",
                "unique_id": "scripts/a.py",
                "data": DATA | {"source_type": "managed", "source": revision},
            }
        ],
    )
    entry.add_to_hass(hass)
    original = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "reconfigure", "subentry_id": original}
    )
    result = await configure(
        hass, result["flow_id"], DATA | {"source_type": "managed", "source": ""}
    )
    assert result["step_id"] == "editor"
    assert result["data_schema"]({})["patch_text"] == DIFF.decode()
    result = await configure(
        hass, result["flow_id"], {"patch_text": DIFF.decode().replace("+new", "+newer")}
    )
    result = await configure(hass, result["flow_id"], {"auto_apply": False})
    assert result["type"] == FlowResultType.ABORT
    assert list(entry.subentries) == [original]
    assert owned.load(revision) == DIFF
    assert owned.load(entry.subentries[original].data["source"]) == DIFF.replace(b"+new", b"+newer")


async def test_managed_edit_of_applied_patch_requires_revert(hass, files):
    from custom_components.hapatchy.managed_source import ManagedPatchStore

    revision = ManagedPatchStore(files).save(DIFF)
    (files / "scripts/a.py").write_bytes(b"context\nnew\n")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        subentries_data=[
            {
                "subentry_type": "patch",
                "title": "Example",
                "unique_id": "scripts/a.py",
                "data": DATA | {"source_type": "managed", "source": revision},
            }
        ],
    )
    entry.add_to_hass(hass)
    original = next(iter(entry.subentries))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "reconfigure", "subentry_id": original}
    )
    result = await configure(
        hass, result["flow_id"], DATA | {"source_type": "managed", "source": ""}
    )
    result = await configure(
        hass, result["flow_id"], {"patch_text": DIFF.decode().replace("+new", "+newer")}
    )
    assert result["errors"] == {"base": "revert_before_edit"}
    assert entry.subentries[original].data["source"] == revision


async def test_editor_rejects_ambiguous_direction(hass, files):
    (files / "scripts/a.py").write_bytes(b"context\nold\ncontext\nnew\n")
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(hass, result["flow_id"], DATA | {"source_type": "managed"})
    result = await configure(hass, result["flow_id"], {"patch_text": DIFF.decode()})
    assert result["step_id"] == "editor"
    assert result["errors"] == {"base": "ambiguous_direction"}
    assert not entry.subentries


async def test_upload_is_reviewed_before_persisting(hass, files):
    from uuid import uuid4

    from homeassistant.components.file_upload import FileUploadData

    file_id = uuid4().hex
    uploads = files / "uploads"
    (uploads / file_id).mkdir(parents=True)
    (uploads / file_id / "input.patch").write_bytes(DIFF)
    hass.data["file_upload"] = FileUploadData(uploads, {file_id: "input.patch"})
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(
        hass, result["flow_id"], DATA | {"source_type": "upload", "watch_root": ""}
    )
    assert result["step_id"] == "upload"
    result = await configure(hass, result["flow_id"], {"file": file_id})
    assert result["step_id"] == "editor"
    assert result["data_schema"]({})["patch_text"] == DIFF.decode()
    assert not entry.subentries and not (files / ".hapatchy/patches").exists()
    assert not (uploads / file_id).exists()
    result = await configure(hass, result["flow_id"], {"patch_text": DIFF.decode()})
    result = await configure(hass, result["flow_id"], {"auto_apply": False})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert next(iter(entry.subentries.values())).data["watch_root"] == "scripts"


async def test_store_failure_keeps_options_editable(hass, files):
    from custom_components.hapatchy.models import PatchError

    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await configure(hass, result["flow_id"], DATA | {"source_type": "managed"})
    result = await configure(hass, result["flow_id"], {"patch_text": DIFF.decode()})
    with patch(
        "custom_components.hapatchy.config_flow.ManagedPatchStore.save",
        side_effect=PatchError("managed_source_write_failed"),
    ):
        result = await configure(hass, result["flow_id"], {"auto_apply": False})
    assert result["errors"] == {"base": "managed_source_write_failed"}
    assert result["data_schema"]({})["auto_apply"] is False
    assert not entry.subentries
    result = await configure(hass, result["flow_id"], {"auto_apply": False})
    assert result["type"] == FlowResultType.CREATE_ENTRY
