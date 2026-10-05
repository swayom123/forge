"""Bounded, read-only traversal for untrusted repositories."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "venv",
    }
)


class ScanLimitError(ValueError):
    """Raised when a repository exceeds configured traversal limits."""


@dataclass(frozen=True)
class ScanPolicy:
    """Limits and exclusions applied during repository traversal."""

    max_files: int = 10_000
    max_file_bytes: int = 1_000_000
    ignored_directories: frozenset[str] = DEFAULT_IGNORED_DIRECTORIES


DEFAULT_SCAN_POLICY = ScanPolicy()


def configured_scan_policy() -> ScanPolicy:
    """Build traversal limits from process settings while retaining safe exclusions."""
    from forge.config import get_settings

    settings = get_settings()
    additions = frozenset(
        name.strip() for name in settings.repository_ignored_directories.split(",") if name.strip()
    )
    return ScanPolicy(
        max_files=settings.repository_max_files,
        max_file_bytes=settings.repository_max_file_bytes,
        ignored_directories=DEFAULT_IGNORED_DIRECTORIES | additions,
    )


@dataclass(frozen=True)
class SafeFile:
    """A regular, in-root, non-binary file safe to read within its limit."""

    relative_path: Path
    absolute_path: Path
    size_bytes: int

    def read_bytes(self) -> bytes:
        """Read the file after checking it has not become a symlink or grown."""
        try:
            descriptor = os.open(self.absolute_path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ValueError(f"Refusing changed file: {self.relative_path}") from exc
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != self.size_bytes:
                raise ValueError(f"File changed during scan: {self.relative_path}")
            data = stream.read(self.size_bytes + 1)
        if len(data) != self.size_bytes:
            raise ValueError(f"File changed during scan: {self.relative_path}")
        return data


def iter_safe_files(root: Path, policy: ScanPolicy = DEFAULT_SCAN_POLICY) -> tuple[SafeFile, ...]:
    """Return bounded files without following directory or file symlinks."""
    resolved_root = root.resolve(strict=True)
    discovered: list[SafeFile] = []
    pending = [resolved_root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in policy.ignored_directories:
                    pending.append(Path(entry.path))
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if len(discovered) >= policy.max_files:
                raise ScanLimitError(f"Repository exceeds {policy.max_files} files")
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            if size > policy.max_file_bytes:
                continue
            path = Path(entry.path)
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    prefix = stream.read(8192)
            except OSError:
                continue
            if b"\x00" in prefix:
                continue
            discovered.append(SafeFile(path.relative_to(resolved_root), path, size))
    return tuple(sorted(discovered, key=lambda item: item.relative_path.as_posix()))
