"""Synchronous transaction orchestration, executed outside the HA event loop."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .atomic_writer import AtomicFileWriter, CommitError
from .backup import BackupManager
from .models import PatchDefinition, PatchError, PatchInspection, Status
from .patch_engine import UnifiedDiffEngine
from .path_policy import PathPolicy
from .safe_io import GuardedFile


@dataclass(frozen=True)
class ReconcileResult:
    inspection: PatchInspection
    source_sha256: str
    target_sha256: str | None = None
    mutated: bool = False
    service_error: str | None = None


class Reconciler:
    """Own one complete inspect/commit operation; the runtime owns serialization."""

    def __init__(self, root: Path, policy: PathPolicy):
        self.root = root
        self.policy = policy
        self.engine = UnifiedDiffEngine()
        self.writer = AtomicFileWriter()

    def run(
        self,
        definition: PatchDefinition,
        source: bytes,
        action: str,
        retention: int,
        pending_durability: bool,
    ) -> ReconcileResult:
        digest = hashlib.sha256(source).hexdigest()
        target_hash = None
        mutated = False
        if not definition.enabled:
            return ReconcileResult(
                PatchInspection(Status.DISABLED), digest, service_error="disabled_patch"
            )
        for attempt in range(3):
            try:
                self.policy.check_definition(definition)
                parsed = self.engine.parse(source, definition.target_path)
                with GuardedFile(self.root, definition.target_path) as target:
                    snapshot = target.read()
                    target_hash = snapshot.sha256
                    if pending_durability:
                        self.writer.confirm_durability(target, snapshot)
                        pending_durability = False
                    inspection = self.engine.inspect(parsed, snapshot.data)
                    output = None
                    if action == "revert":
                        if inspection.status == Status.APPLICABLE:
                            return ReconcileResult(
                                inspection, digest, target_hash, service_error="not_applied"
                            )
                        output = inspection.reverse_output
                    elif action == "apply" or (action == "reconcile" and definition.auto_apply):
                        output = inspection.forward_output
                    if output is None:
                        error = (
                            inspection.reason
                            if inspection.status not in (Status.APPLIED, Status.APPLICABLE)
                            else None
                        )
                        return ReconcileResult(inspection, digest, target_hash, service_error=error)
                    backups = BackupManager(self.root, definition.patch_id, retention)
                    backup_required = action == "revert" or definition.backup_before_apply

                    def backup():
                        return backups.create(
                            snapshot,
                            definition.target_path,
                            output,
                            digest,
                            "revert" if action == "revert" else "apply",
                        )

                    try:
                        self.writer.commit(
                            target,
                            snapshot,
                            output,
                            before_replace=backup if backup_required else None,
                            before_commit=lambda: self.policy.check_definition(definition),
                        )
                    except CommitError as error:
                        mutated = error.replaced
                        if mutated:
                            try:
                                target_hash = target.read().sha256
                            except PatchError:
                                target_hash = None
                        raise
                    mutated = True
                    current = target.read()
                    target_hash = current.sha256
                    inspection = self.engine.inspect(parsed, current.data)
                    backups.prune()
                    return ReconcileResult(
                        inspection,
                        digest,
                        target_hash,
                        mutated=True,
                        service_error=inspection.reason,
                    )
            except PatchError as error:
                if pending_durability and error.status != Status.SECURITY_ERROR:
                    return ReconcileResult(
                        PatchInspection(Status.APPLY_ERROR, "durability_unconfirmed"),
                        digest,
                        target_hash,
                        mutated,
                        "durability_unconfirmed",
                    )
                if error.reason == "target_changed" and not mutated and attempt < 2:
                    continue
                return ReconcileResult(
                    PatchInspection(error.status, error.reason),
                    digest,
                    target_hash,
                    mutated,
                    error.reason,
                )
            except OSError:
                return ReconcileResult(
                    PatchInspection(Status.APPLY_ERROR, "filesystem_error"),
                    digest,
                    target_hash,
                    mutated,
                    "filesystem_error",
                )
        raise AssertionError("Bounded retry loop must return")
