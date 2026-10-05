"""Read-only local repository identity scanner."""

from pathlib import Path

from forge.core.contracts import RepositoryProfile


class LocalRepositoryScanner:
    """Check local Git identity without executing repository code or hooks."""

    def scan(self, root: Path) -> RepositoryProfile:
        """Resolve root and validate that its Git metadata is present."""
        resolved = root.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("Repository path must be a directory")
        marker = resolved / ".git"
        if not marker.is_dir() and not marker.is_file():
            raise ValueError("Path is not a Git repository root")
        return RepositoryProfile(root=resolved, name=resolved.name, is_git_repository=True)
