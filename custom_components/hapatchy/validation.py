"""Read-only configuration validation shared by native flows."""

from functools import partial
from pathlib import Path

from homeassistant.core import HomeAssistant

from .models import PatchDefinition, PatchError, PatchInspection, Status
from .patch_builder import MAX_EDITOR_BYTES, validate_editor_text
from .patch_engine import UnifiedDiffEngine
from .patch_source import PatchSourceClient
from .path_policy import PathPolicy
from .safe_io import GuardedFile, Snapshot, identity
from .yaml_policy import policy_for_hass


def read_editable_target(
    root: Path, definition: PatchDefinition, policy: PathPolicy
) -> Snapshot:
    """Read a bounded, authorized text snapshot off the HA event loop."""
    policy.check_definition(definition)
    with GuardedFile(root, definition.target_path) as target:
        snapshot = target.read(MAX_EDITOR_BYTES)
        validate_editor_text(snapshot.data)
        policy.check_definition(definition)
        target.verify_snapshot(snapshot)
        return snapshot


def verify_editable_snapshot(
    root: Path, definition: PatchDefinition, policy: PathPolicy, expected: Snapshot
) -> None:
    """Refuse publication if the authorized file changed while its editor was open."""
    try:
        current = read_editable_target(root, definition, policy)
    except PatchError:
        raise PatchError("editor_target_changed", Status.SECURITY_ERROR) from None
    if identity(current.info) != identity(expected.info) or current.sha256 != expected.sha256:
        raise PatchError("editor_target_changed", Status.SECURITY_ERROR)


def inspect_target(
    root: Path, definition: PatchDefinition, raw: bytes, policy: PathPolicy
) -> PatchInspection:
    policy.check_definition(definition)
    engine = UnifiedDiffEngine()
    parsed = engine.parse(raw, definition.target_path)
    try:
        with GuardedFile(root, definition.target_path) as target:
            result = engine.inspect(parsed, target.read().data)
            if result.status not in (Status.APPLICABLE, Status.APPLIED, Status.CONFLICT):
                raise PatchError(result.reason or "invalid_patch", result.status)
            return result
    except PatchError as error:
        if error.status == Status.MISSING_TARGET:
            return PatchInspection(Status.MISSING_TARGET, error.reason)
        raise


async def validate_definition(hass: HomeAssistant, definition: PatchDefinition) -> PatchInspection:
    root = Path(hass.config.config_dir)
    policy = policy_for_hass(hass)
    await hass.async_add_executor_job(policy.check_definition, definition)
    client = PatchSourceClient(root, hass.async_add_executor_job)
    raw = await client.load(definition)
    result = await hass.async_add_executor_job(
        partial(inspect_target, root, definition, raw, policy)
    )
    if result.status not in (
        Status.APPLICABLE,
        Status.APPLIED,
        Status.CONFLICT,
        Status.MISSING_TARGET,
    ):
        raise PatchError(result.reason or "invalid_patch", result.status)
    return result
