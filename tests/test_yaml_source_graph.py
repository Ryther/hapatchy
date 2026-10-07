"""The configuration source graph is protected without constructing HA tags."""

import os
from time import perf_counter

import pytest
import yaml

from custom_components.hapatchy.models import PatchError


def test_large_include_graph_uses_accelerated_yaml_parser(tmp_path):
    """Source verification must not reparse large HA includes at Python speed."""
    if not hasattr(yaml, "CLoader"):
        pytest.skip("PyYAML CLoader is unavailable")
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    included = tmp_path / "included"
    included.mkdir()
    (tmp_path / "configuration.yaml").write_text(
        "sensor: !include_dir_merge_list included\n"
    )
    payload = (("- " + "x" * 100 + "\n") * 900).encode()
    for index in range(17):
        (included / f"{index:02}.yaml").write_bytes(payload)

    start = perf_counter()
    graph = scan_source_graph(tmp_path)
    scan_seconds = perf_counter() - start
    start = perf_counter()
    for _ in range(17):
        for _event in yaml.parse(payload, Loader=yaml.Loader):
            pass
        yaml.compose(payload, Loader=yaml.Loader)
    pure_python_seconds = perf_counter() - start

    assert len(graph.sources) == 18
    assert scan_seconds < pure_python_seconds / 2


def test_recursive_include_sources_and_future_files_are_protected(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text(
        "homeassistant:\n  packages: !include_dir_named packages\n"
        "hapatchy: !include policy.yaml\nsensor: !secret token\n"
    )
    (tmp_path / "policy.yaml").write_text("allowed_directories:\n  - scripts\n")
    nested = tmp_path / "packages" / "nested"
    nested.mkdir(parents=True)
    (nested / "example.yaml").write_text("sensor: []\n")
    graph = scan_source_graph(tmp_path)

    assert graph.protects("configuration.yaml")
    assert graph.protects("policy.yaml")
    assert graph.protects("packages/nested/example.yaml")
    assert graph.protects("packages/nested/future.yaml")
    assert graph.protects("secrets.yaml")
    assert not graph.protects("scripts/example.py")

    (nested / "future.yaml").write_text("sensor: []\n")
    assert scan_source_graph(tmp_path) != graph


def test_authority_comparison_ignores_only_unrelated_content(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text(
        "hapatchy: !include grants.yaml\nautomation: !include automations.yaml\n"
    )
    (tmp_path / "grants.yaml").write_text("allowed_directories:\n  - scripts\n")
    automations = tmp_path / "automations.yaml"
    automations.write_text("[]\n")
    original = scan_source_graph(tmp_path)

    automations.write_text("- alias: Example\n  trigger: []\n")
    changed = scan_source_graph(tmp_path)
    assert changed.same_authority_as(original)
    assert changed.protects("automations.yaml")

    (tmp_path / "grants.yaml").write_text("allowed_directories:\n  - www\n")
    assert not scan_source_graph(tmp_path).same_authority_as(original)


def test_replaced_unrelated_include_is_allowed_but_shared_grant_source_is_not(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text(
        "homeassistant:\n  customize: !include customize.yaml\n"
        "hapatchy: !include shared.yaml\nsensor: !include shared.yaml\n"
    )
    customize = tmp_path / "customize.yaml"
    customize.write_text("{}\n")
    shared = tmp_path / "shared.yaml"
    shared.write_text("allowed_directories:\n  - scripts\n")
    original = scan_source_graph(tmp_path)

    replacement = tmp_path / "replacement.tmp"
    replacement.write_text("sensor.example:\n  friendly_name: Changed\n")
    os.replace(replacement, customize)
    assert scan_source_graph(tmp_path).same_authority_as(original)

    shared.write_text("allowed_directories:\n  - www\n")
    assert not scan_source_graph(tmp_path).same_authority_as(original)


def test_repeated_include_directory_scans_close_descriptors(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text(
        "homeassistant:\n  packages: !include_dir_named packages\n"
    )
    nested = tmp_path / "packages" / "nested"
    nested.mkdir(parents=True)
    (nested / "example.yaml").write_text("sensor: []\n")

    before = len(os.listdir("/proc/self/fd"))
    for _ in range(20):
        assert scan_source_graph(tmp_path).protects("packages/nested/example.yaml")
    assert len(os.listdir("/proc/self/fd")) == before


@pytest.mark.parametrize("source", ["sensor: !unexpected x\n", "sensor: !include ../outside.yaml\n"])
def test_unsupported_or_escaping_source_denies(tmp_path, source):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text(source)
    with pytest.raises(PatchError, match="configuration_source_unavailable"):
        scan_source_graph(tmp_path)


def test_secret_candidates_from_nested_include_are_protected(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text("sensor: !include nested/value.yaml\n")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "value.yaml").write_text("token: !secret api_token\n")
    (tmp_path / "secrets.yaml").write_text("api_token: value\n")

    graph = scan_source_graph(tmp_path)

    assert graph.protects("nested/secrets.yaml")
    assert graph.protects("secrets.yaml")


@pytest.mark.parametrize("tag", ["!env_var", "!input"])
def test_opaque_tag_operands_do_not_use_include_path_grammar(tmp_path, tag):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text(f"value: {tag} 'FOO/../bar'\n")

    assert scan_source_graph(tmp_path).protects("configuration.yaml")


def test_cyclic_include_is_denied(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text("sensor: !include nested.yaml\n")
    (tmp_path / "nested.yaml").write_text("sensor: !include configuration.yaml\n")

    with pytest.raises(PatchError, match="configuration_source_unavailable"):
        scan_source_graph(tmp_path)


@pytest.mark.parametrize("unsafe_entry", ["symlink", "hardlink"])
def test_include_directory_rejects_links(tmp_path, unsafe_entry):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text(
        "sensor: !include_dir_merge_list included\n"
    )
    included = tmp_path / "included"
    included.mkdir()
    original = tmp_path / "original.yaml"
    original.write_text("- sensor.example\n")
    entry = included / "linked.yaml"
    if unsafe_entry == "symlink":
        entry.symlink_to(original)
    else:
        os.link(original, entry)

    with pytest.raises(PatchError, match="configuration_source_unavailable"):
        scan_source_graph(tmp_path)
    assert original.read_text() == "- sensor.example\n"


def test_duplicate_keys_in_included_source_are_denied(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text("sensor: !include nested.yaml\n")
    (tmp_path / "nested.yaml").write_text("sensor: []\nsensor: []\n")

    with pytest.raises(PatchError, match="configuration_source_unavailable"):
        scan_source_graph(tmp_path)


def test_invalid_protected_path_is_not_treated_as_a_source(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text("sensor: []\n")

    graph = scan_source_graph(tmp_path)

    assert not graph.protects("../configuration.yaml")
    assert not graph.protects("/configuration.yaml")


def test_oversized_included_source_is_denied(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text("sensor: !include nested.yaml\n")
    (tmp_path / "nested.yaml").write_bytes(b"#" + b"x" * (512 * 1024))

    with pytest.raises(PatchError, match="configuration_source_unavailable"):
        scan_source_graph(tmp_path)


def test_excessively_nested_includes_are_denied(tmp_path):
    from custom_components.hapatchy.yaml_source_graph import scan_source_graph

    (tmp_path / "configuration.yaml").write_text("sensor: !include 0.yaml\n")
    for index in range(17):
        (tmp_path / f"{index}.yaml").write_text(
            f"sensor: !include {index + 1}.yaml\n"
        )

    with pytest.raises(PatchError, match="configuration_source_unavailable"):
        scan_source_graph(tmp_path)
