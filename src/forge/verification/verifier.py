"""Deterministic evaluation of complete planned validation runs."""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from forge.core.contracts import ExecutionResult, Plan
from forge.core.models import PatchRecord, TaskWorkspaceRecord


class GateVerifier:
    """Require one successful, non-timeout result for every planned command."""

    def verify(self, plan: Plan, results: tuple[ExecutionResult, ...]) -> bool:
        """Return true only when the complete validation command set passed."""
        return len(results) == len(plan.validation_commands) and all(
            result.exit_code == 0 and not result.timed_out for result in results
        )

    @staticmethod
    def summary(plan: Plan, results: tuple[ExecutionResult, ...]) -> str:
        """Create a bounded deterministic failure or success summary."""
        if len(results) != len(plan.validation_commands):
            return (
                f"Infrastructure error after {len(results)} of "
                f"{len(plan.validation_commands)} verification commands."
            )
        failures = [
            index
            for index, result in enumerate(results)
            if result.exit_code != 0 or result.timed_out
        ]
        if not failures:
            return f"All {len(results)} verification commands passed."
        positions = ", ".join(str(index) for index in failures)
        return f"Verification commands failed at zero-based positions: {positions}."


def workspace_patch_fingerprint(session: Session, workspace: TaskWorkspaceRecord) -> str:
    """Hash the base commit and ordered immutable patch audit chain."""
    digest = hashlib.sha256(workspace.base_commit.encode())
    records = session.scalars(
        select(PatchRecord)
        .where(PatchRecord.workspace_id == workspace.id)
        .order_by(PatchRecord.created_at, PatchRecord.id)
    )
    for record in records:
        for value in (
            record.id,
            record.file_path,
            record.operation,
            record.before_hash or "",
            record.after_hash or "",
        ):
            digest.update(b"\0")
            digest.update(value.encode())
    return digest.hexdigest()
