"""Path admission requires both operator grants and live HA permission."""

from types import SimpleNamespace

import pytest

from custom_components.hapatchy.models import PatchError
from custom_components.hapatchy.path_policy import PathPolicy


def _policy(root, *, ha_dirs=(), protected=(), changed=False):
    def current():
        if changed:
            from custom_components.hapatchy.models import Status

            raise PatchError("configuration_source_changed", Status.SECURITY_ERROR)

    return SimpleNamespace(
        hapatchy_directories=("scripts",),
        ha_explicit_directories=ha_dirs,
        graph=SimpleNamespace(protects=lambda path: path in protected),
        check_current=current,
    )


def test_implicit_ha_allowance_does_not_replace_explicit_grant(tmp_path):
    gate = PathPolicy(tmp_path, lambda _: True, _policy(tmp_path))

    with pytest.raises(PatchError, match="ha_path_not_allowed"):
        gate.check_path("scripts/a.py")


def test_included_source_is_protected_inside_granted_directory(tmp_path):
    gate = PathPolicy(
        tmp_path,
        lambda _: True,
        _policy(
            tmp_path,
            ha_dirs=(str(tmp_path / "scripts"),),
            protected=("scripts/source.yaml",),
        ),
    )

    with pytest.raises(PatchError, match="protected_path"):
        gate.check_path("scripts/source.yaml")
    gate.check_path("scripts/a.py")


def test_changed_configuration_denies_before_directory_reason(tmp_path):
    gate = PathPolicy(tmp_path, lambda _: True, _policy(tmp_path, changed=True))

    with pytest.raises(PatchError, match="configuration_source_changed"):
        gate.check_path("other/a.py")
