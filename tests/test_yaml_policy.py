"""Operator YAML grants are loaded once and checked against HA's boot config."""

import pytest

from custom_components.hapatchy.models import PatchError


def _write_config(root, text):
    (root / "configuration.yaml").write_text(text)


def test_main_yaml_grants_match_boot_configuration(tmp_path):
    from custom_components.hapatchy.yaml_policy import load_yaml_policy

    explicit = str(tmp_path / "scripts")
    _write_config(
        tmp_path,
        f"homeassistant:\n  allowlist_external_dirs:\n    - {explicit}\n"
        "hapatchy:\n  allowed_directories:\n    - scripts\n",
    )
    boot = {
        "homeassistant": {"allowlist_external_dirs": [explicit]},
        "hapatchy": {"allowed_directories": ["scripts"]},
    }

    policy = load_yaml_policy(tmp_path, boot)

    assert policy.hapatchy_directories == ("scripts",)
    assert policy.ha_explicit_directories == (explicit,)
    assert policy.graph.protects("configuration.yaml")


def test_package_grant_denied_even_when_equal_to_main(tmp_path):
    from custom_components.hapatchy.yaml_policy import load_yaml_policy

    explicit = str(tmp_path / "scripts")
    _write_config(
        tmp_path,
        f"homeassistant:\n  allowlist_external_dirs:\n    - {explicit}\n"
        "  packages:\n    example:\n      hapatchy:\n        allowed_directories:\n          - scripts\n"
        "hapatchy:\n  allowed_directories:\n    - scripts\n",
    )
    boot = {
        "homeassistant": {
            "allowlist_external_dirs": [explicit],
            "packages": {"example": {"hapatchy": {"allowed_directories": ["scripts"]}}},
        },
        "hapatchy": {"allowed_directories": ["scripts"]},
    }

    with pytest.raises(PatchError, match="hapatchy_package_forbidden"):
        load_yaml_policy(tmp_path, boot)


def test_implicit_ha_directory_is_not_an_explicit_grant(tmp_path):
    from custom_components.hapatchy.yaml_policy import load_yaml_policy

    _write_config(tmp_path, "hapatchy:\n  allowed_directories:\n    - www\n")
    boot = {"hapatchy": {"allowed_directories": ["www"]}}

    policy = load_yaml_policy(tmp_path, boot)

    assert policy.hapatchy_directories == ("www",)
    assert policy.ha_explicit_directories == ()


def test_falsey_main_section_is_not_treated_as_an_absent_grant(tmp_path):
    from custom_components.hapatchy.yaml_policy import load_yaml_policy

    _write_config(tmp_path, "hapatchy: null\n")

    with pytest.raises(PatchError, match="hapatchy_yaml_invalid") as error:
        load_yaml_policy(tmp_path, {"hapatchy": {}})

    assert error.value.status.value == "security_error"


def test_raw_and_boot_grants_must_match(tmp_path):
    from custom_components.hapatchy.yaml_policy import load_yaml_policy

    _write_config(tmp_path, "hapatchy:\n  allowed_directories:\n    - scripts\n")

    with pytest.raises(PatchError, match="configuration_mismatch"):
        load_yaml_policy(tmp_path, {"hapatchy": {"allowed_directories": ["www"]}})


def test_source_graph_change_denies_without_reloading_grants(tmp_path):
    from custom_components.hapatchy.yaml_policy import load_yaml_policy

    _write_config(tmp_path, "hapatchy:\n  allowed_directories:\n    - scripts\n")
    policy = load_yaml_policy(tmp_path, {"hapatchy": {"allowed_directories": ["scripts"]}})

    (tmp_path / "configuration.yaml").write_text(
        "hapatchy:\n  allowed_directories:\n    - www\n"
    )

    with pytest.raises(PatchError, match="configuration_source_changed"):
        policy.check_current()

    assert policy.hapatchy_directories == ("scripts",)


def test_schema_validator_returns_immutable_validated_directories():
    from custom_components.hapatchy.yaml_policy import validate_hapatchy_directories

    assert validate_hapatchy_directories({"allowed_directories": ["scripts"]}) == ("scripts",)

    with pytest.raises(PatchError, match="hapatchy_yaml_invalid"):
        validate_hapatchy_directories({"allowed_directories": ["."]})


def test_direct_policy_include_rejects_dynamic_grant_value(tmp_path, monkeypatch):
    from custom_components.hapatchy.yaml_policy import load_yaml_policy

    monkeypatch.setenv("HAPATCHY_TEST_DIRECTORY", "scripts")
    _write_config(tmp_path, "hapatchy: !include policy.yaml\n")
    (tmp_path / "policy.yaml").write_text(
        "allowed_directories:\n  - !env_var HAPATCHY_TEST_DIRECTORY\n"
    )

    with pytest.raises(PatchError, match="hapatchy_yaml_invalid"):
        load_yaml_policy(tmp_path, {"hapatchy": {"allowed_directories": ["scripts"]}})


def test_post_schema_yaml_load_failure_has_controlled_denial(tmp_path, monkeypatch):
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.hapatchy import yaml_policy

    _write_config(tmp_path, "hapatchy:\n  allowed_directories:\n    - scripts\n")

    def fail_load(*args, **kwargs):
        raise HomeAssistantError("untrusted source detail")

    monkeypatch.setattr(yaml_policy, "load_yaml_config_file", fail_load)
    with pytest.raises(PatchError, match="hapatchy_yaml_invalid"):
        yaml_policy.load_yaml_policy(
            tmp_path, {"hapatchy": {"allowed_directories": ["scripts"]}}
        )
