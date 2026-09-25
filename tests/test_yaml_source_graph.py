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
