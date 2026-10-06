"""Isolated Git workspaces and audited file mutations."""

from forge.workspaces.manager import (
    AuditedPatchManager,
    GitWorktreeManager,
    PatchConflictError,
    WorkspaceError,
)

__all__ = [
    "AuditedPatchManager",
    "GitWorktreeManager",
    "PatchConflictError",
    "WorkspaceError",
]
