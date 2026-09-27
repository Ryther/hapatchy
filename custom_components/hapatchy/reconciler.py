"""Synchronous transaction orchestration, executed outside the HA event loop."""

import hashlib
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from .atomic_writer import AtomicFileWriter, CommitError
from .backup import BackupManager
from .models import PatchDefinition, PatchError, PatchInspection, Status
from .patch_engine import ParsedPatch, UnifiedDiffEngine
from .path_policy import PathPolicy
from .safe_io import GuardedFile, Snapshot


@dataclass(frozen=True)
class ReconcileResult:
    inspection: PatchInspection
    source_sha256: str
    target_sha256: str | None = None
    mutated: bool = False
    service_error: str | None = None


@dataclass
class _Progress:
    """Retain observed mutation and durability state even when an attempt raises."""

    source_sha256: str
    pending_durability: bool
    target_sha256: str | None = None
    mutated: bool = False

    def result(self, inspection: PatchInspection, error: str | None = None) -> ReconcileResult:
        return ReconcileResult(
            inspection, self.source_sha256, self.target_sha256, self.mutated, error
        )


def _output_for_action(
    definition: PatchDefinition, inspection: PatchInspection, action: str
) -> bytes | None:
    if action == "revert":
        return inspection.reverse_output
    if action == "apply" or (action == "reconcile" and definition.auto_apply):
        return inspection.forward_output
    return None


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
        progress = _Progress(hashlib.sha256(source).hexdigest(), pending_durability)
        if not definition.enabled:
            return progress.result(PatchInspection(Status.DISABLED), "disabled_patch")
        for attempt in range(3):
            try:
                return self._attempt(definition, source, action, retention, progress)
            except PatchError as error:
                if progress.pending_durability and error.status != Status.SECURITY_ERROR:
                    return progress.result(
                        PatchInspection(Status.APPLY_ERROR, "durability_unconfirmed"),
                        "durability_unconfirmed",
                    )
                if error.reason == "target_changed" and not progress.mutated and attempt < 2:
                    continue
                return progress.result(PatchInspection(error.status, error.reason), error.reason)
            except OSError:
                return progress.result(
                    PatchInspection(Status.APPLY_ERROR, "filesystem_error"), "filesystem_error"
                )
        raise AssertionError("Bounded retry loop must return")

    def _attempt(
        self,
        definition: PatchDefinition,
        source: bytes,
        action: str,
        retention: int,
        progress: _Progress,
    ) -> ReconcileResult:
        self.policy.check_definition(definition)
        parsed = self.engine.parse(source, definition.target_path)
        with GuardedFile(self.root, definition.target_path) as target:
            snapshot = target.read()
            progress.target_sha256 = snapshot.sha256
            if progress.pending_durability:
                self.writer.confirm_durability(target, snapshot)
                progress.pending_durability = False
            inspection = self.engine.inspect(parsed, snapshot.data)
            if action == "revert" and inspection.status == Status.APPLICABLE:
                return progress.result(inspection, "not_applied")
            output = _output_for_action(definition, inspection, action)
            if output is None:
                error = (
                    inspection.reason
                    if inspection.status not in (Status.APPLIED, Status.APPLICABLE)
                    else None
                )
                return progress.result(inspection, error)
            return self._replace(
                definition, parsed, target, snapshot, output, action, retention, progress
            )

    def _replace(
        self,
        definition: PatchDefinition,
        parsed: ParsedPatch,
        target: GuardedFile,
        snapshot: Snapshot,
        output: bytes,
        action: str,
        retention: int,
        progress: _Progress,
    ) -> ReconcileResult:
        backups = BackupManager(self.root, definition.patch_id, retention)
        backup_required = action == "revert" or definition.backup_before_apply
        backup = partial(
            backups.create,
            snapshot,
            definition.target_path,
            output,
            progress.source_sha256,
            "revert" if action == "revert" else "apply",
        )
        try:
            self.writer.commit(
                target,
                snapshot,
                output,
                before_replace=backup if backup_required else None,
                before_commit=partial(self.policy.check_definition, definition),
            )
        except CommitError as error:
            progress.mutated = error.replaced
            if progress.mutated:
                self._observe_replaced_target(target, progress)
            raise
        progress.mutated = True
        current = target.read()
        progress.target_sha256 = current.sha256
        inspection = self.engine.inspect(parsed, current.data)
        backups.prune()
        return progress.result(inspection, inspection.reason)

    @staticmethod
    def _observe_replaced_target(target: GuardedFile, progress: _Progress) -> None:
        try:
            progress.target_sha256 = target.read().sha256
        except PatchError:
            progress.target_sha256 = None
