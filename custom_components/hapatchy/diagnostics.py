"""Deliberately constructed diagnostics: no raw config, URLs or file contents."""

from dataclasses import asdict
from urllib.parse import urlsplit


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"entry_id": entry.entry_id, "loaded": False}
    patches = []
    for key, definition in runtime.definitions.items():
        patches.append(
            {
                "patch_id": key,
                "definition": {
                    "target_path": definition.target_path,
                    "watch_root": definition.watch_root,
                    "watch_pattern": definition.watch_pattern,
                    "source_type": definition.source_type,
                    "source_hostname": urlsplit(definition.source).hostname
                    if definition.source_type == "url"
                    else None,
                    "source_sha256": definition.source_sha256,
                    "enabled": definition.enabled,
                    "auto_apply": definition.auto_apply,
                    "reconcile_on_startup": definition.reconcile_on_startup,
                    "backup_before_apply": definition.backup_before_apply,
                    "debounce_seconds": definition.debounce_seconds,
                },
                "state": asdict(runtime.states[key]),
            }
        )
    return {
        "entry_id": entry.entry_id,
        "loaded": not runtime.closing,
        "backup_retention": runtime.retention,
        "patches": patches,
    }
