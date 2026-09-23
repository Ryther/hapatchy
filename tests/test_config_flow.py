"""Native entry, subentry and retention UI behavior."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "hapatchy"
DATA = {
    "name": "Example",
    "target_path": "scripts/a.py",
    "watch_root": "scripts",
    "source_type": "local",
    "source": "patches/a.patch",
}
DIFF = b"--- a/scripts/a.py\n+++ b/scripts/a.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n"


def require_flow():
    assert Path("custom_components/hapatchy/config_flow.py").exists(), (
        "Native configuration flow is missing"
    )


@pytest.fixture
def files(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
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
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], DATA)
    assert result["step_id"] == "options"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
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
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], DATA | extra)
    if result["step_id"] == "options":
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
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
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], DATA)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"backup_before_apply": False}
    )
    assert result["step_id"] == "confirm_missing_target"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"confirm": True}
    )
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
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], DATA)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
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
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], DATA | {"name": "Updated"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"auto_apply": False}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert list(entry.subentries) == [original]
    assert entry.subentries[original].data["auto_apply"] is False
    assert entry.subentries[original].title == "Updated"


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
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            DATA
            | {"source_type": "url", "source": "https://raw.githubusercontent.com/example/patch"},
        )
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["type"] == FlowResultType.CREATE_ENTRY


async def test_bad_basic_fields_remain_editable(hass, files):
    require_flow()
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "patch"), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], DATA | {"watch_root": "."}
    )
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
