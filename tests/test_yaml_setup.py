"""HA setup freezes operator YAML grants without exposing a grant-writing flow."""

import pytest
import voluptuous as vol

from custom_components.hapatchy.const import DOMAIN


def test_config_schema_accepts_literal_yaml_grants():
    from custom_components.hapatchy import CONFIG_SCHEMA

    assert CONFIG_SCHEMA({"hapatchy": {"allowed_directories": ["scripts"]}})[DOMAIN] == {
        "allowed_directories": ["scripts"]
    }


@pytest.mark.parametrize("section", [None, {}, {"allowed_directories": "scripts"}, {"allowed_directories": ["scripts"], "bypass": True}])
def test_config_schema_rejects_invalid_present_section(section):
    from custom_components.hapatchy import CONFIG_SCHEMA

    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA({DOMAIN: section})


async def test_async_setup_loads_yaml_grants_once(hass, tmp_path):
    from custom_components.hapatchy import async_setup

    hass.config.config_dir = str(tmp_path)
    explicit = str(tmp_path / "scripts")
    (tmp_path / "configuration.yaml").write_text(
        f"homeassistant:\n  allowlist_external_dirs:\n    - {explicit}\n"
        "hapatchy:\n  allowed_directories:\n    - scripts\n"
    )
    boot = {
        "homeassistant": {"allowlist_external_dirs": [explicit]},
        "hapatchy": {"allowed_directories": ["scripts"]},
    }

    assert await async_setup(hass, boot)
    assert hass.data[DOMAIN]["yaml_policy"].hapatchy_directories == ("scripts",)


async def test_async_setup_without_yaml_grants_denies_all(hass, tmp_path):
    from custom_components.hapatchy import async_setup

    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text("homeassistant: {}\n")

    assert await async_setup(hass, {"homeassistant": {}})
    assert hass.data[DOMAIN]["yaml_policy"].hapatchy_directories == ()


async def test_post_schema_mismatch_publishes_deny_all(hass, tmp_path):
    from custom_components.hapatchy import async_setup
    from custom_components.hapatchy.models import PatchError

    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text(
        "hapatchy:\n  allowed_directories:\n    - scripts\n"
    )
    assert await async_setup(hass, {"hapatchy": {"allowed_directories": ["www"]}})
    grants = hass.data[DOMAIN]["yaml_policy"]
    assert grants.hapatchy_directories == ()
    with pytest.raises(PatchError, match="configuration_mismatch"):
        grants.check_current()
