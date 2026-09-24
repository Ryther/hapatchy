"""Read-only configuration validation shared by native flows."""

from functools import partial
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .models import PatchDefinition, PatchError, PatchInspection, Status
from .patch_engine import UnifiedDiffEngine
from .patch_source import PatchSourceClient
from .safe_io import GuardedFile


def inspect_target(root: Path, definition: PatchDefinition, raw: bytes) -> PatchInspection:
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
    client = PatchSourceClient(root, async_get_clientsession(hass), hass.async_add_executor_job)
    raw = await client.load(definition)
    result = await hass.async_add_executor_job(partial(inspect_target, root, definition, raw))
    if result.status not in (
        Status.APPLICABLE,
        Status.APPLIED,
        Status.CONFLICT,
        Status.MISSING_TARGET,
    ):
        raise PatchError(result.reason or "invalid_patch", result.status)
    return result
