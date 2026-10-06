"""Safe worktree lifecycle and optimistic file mutation services."""

import hashlib
import hmac
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from forge.core.contracts import Patch, Workspace
from forge.core.state import PatchOperation


class WorkspaceError(ValueError):
    """Raised when an isolated workspace cannot be safely managed."""


class PatchConflictError(WorkspaceError):
    """Raised when a file no longer has the caller's expected content hash."""


def _git(repository: Path, *arguments: str) -> bytes:
    """Run a non-interactive Git builtin with hooks and global configuration disabled."""
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    command = (
        "git",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "credential.helper=",
        "-C",
        str(repository),
        *arguments,
    )
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=30,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"Git operation failed: {type(exc).__name__}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:1000]
        raise WorkspaceError(f"Git operation failed: {detail or 'unknown error'}")
    return result.stdout


def _safe_relative_path(value: Path) -> Path:
    if value.is_absolute() or not value.parts or value == Path("."):
        raise WorkspaceError("File path must be a non-empty relative path")
    if any(part in {"", ".", "..", ".git"} for part in value.parts):
        raise WorkspaceError("File path contains a forbidden component")
    return value


class GitWorktreeManager:
    """Create worktrees without invoking checkout hooks or content filters."""

    def __init__(
        self,
        root: Path,
        max_files: int = 20_000,
        max_bytes: int = 500_000_000,
    ) -> None:
        self.root = root
        self.max_files = max_files
        self.max_bytes = max_bytes

    def create(self, repository: Path, workspace_id: str) -> Workspace:
        """Create and safely materialize a detached worktree at committed HEAD."""
        source = repository.resolve(strict=True)
        if self.root.exists() and self.root.is_symlink():
            raise WorkspaceError("Worktree root must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = self.root.resolve(strict=True)
        target = root / workspace_id
        try:
            target.relative_to(source)
        except ValueError:
            pass
        else:
            raise WorkspaceError("Worktrees must be stored outside the source repository")
        if target.exists() or target.is_symlink():
            raise WorkspaceError("Workspace path already exists")

        base_commit = _git(source, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        if _git(source, "status", "--porcelain=v1", "--untracked-files=normal"):
            raise WorkspaceError("Source repository must be clean before workspace creation")
        try:
            _git(source, "worktree", "add", "--detach", "--no-checkout", str(target), base_commit)
            _git(target, "read-tree", base_commit)
            self._materialize(source, target, base_commit)
        except Exception:
            self._cleanup_failed_create(source, target)
            raise
        return Workspace(path=target, base_commit=base_commit)

    def remove(self, repository: Path, workspace: Path) -> None:
        """Remove a managed worktree and all uncommitted files in it."""
        source = repository.resolve(strict=True)
        target = self.validate(workspace)
        _git(source, "worktree", "remove", "--force", str(target))

    def validate(self, workspace: Path) -> Path:
        """Resolve a workspace and prove it belongs to this manager's root."""
        try:
            root = self.root.resolve(strict=True)
            target = workspace.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceError("Managed workspace does not exist") from exc
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise WorkspaceError("Workspace path is outside the configured root") from exc
        if target == root:
            raise WorkspaceError("Workspace path cannot be the configured root")
        return target

    def _materialize(self, source: Path, target: Path, commit: str) -> None:
        listing = _git(source, "ls-tree", "-rz", "--full-tree", commit)
        entries = [entry for entry in listing.split(b"\0") if entry]
        if len(entries) > self.max_files:
            raise WorkspaceError(f"Commit exceeds the {self.max_files} file workspace limit")
        total = 0
        for entry in entries:
            try:
                metadata, raw_path = entry.split(b"\t", 1)
                mode, object_type, object_id = metadata.split(b" ", 2)
                relative = _safe_relative_path(Path(raw_path.decode("utf-8")))
            except (UnicodeDecodeError, ValueError) as exc:
                raise WorkspaceError("Commit contains an unsupported tree entry") from exc
            if object_type != b"blob" or mode not in {b"100644", b"100755"}:
                raise WorkspaceError(f"Unsupported tree entry: {relative.as_posix()}")
            size = int(_git(source, "cat-file", "-s", object_id.decode()).decode())
            total += size
            if total > self.max_bytes:
                raise WorkspaceError(f"Commit exceeds the {self.max_bytes} byte workspace limit")
            content = _git(source, "cat-file", "blob", object_id.decode())
            if len(content) != size:
                raise WorkspaceError(f"Git returned an inconsistent blob: {relative.as_posix()}")
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            descriptor = os.open(destination, flags, 0o755 if mode == b"100755" else 0o644)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)

    @staticmethod
    def _cleanup_failed_create(source: Path, target: Path) -> None:
        try:
            _git(source, "worktree", "remove", "--force", str(target))
        except WorkspaceError:
            if target.exists() and not target.is_symlink():
                shutil.rmtree(target)


class AuditedPatchManager:
    """Apply bounded file changes with optimistic hash checks."""

    def __init__(self, max_bytes: int = 1_000_000) -> None:
        self.max_bytes = max_bytes

    def apply(self, root: Path, patch: Patch) -> Patch:
        """Apply one create, update, or delete and return its measured hashes."""
        workspace = root.resolve(strict=True)
        relative = _safe_relative_path(patch.file_path)
        candidate = workspace / relative
        parent = candidate.parent.resolve(strict=False)
        try:
            parent.relative_to(workspace)
        except ValueError as exc:
            raise WorkspaceError("File path escapes the workspace") from exc
        if candidate.is_symlink():
            raise WorkspaceError("Refusing to mutate a symlink")
        operation = PatchOperation(patch.operation)
        exists = candidate.exists()
        if exists and not candidate.is_file():
            raise WorkspaceError("Patch target is not a regular file")
        before_hash = self._hash_file(candidate) if exists else None

        if operation is PatchOperation.CREATE:
            if exists or patch.before_hash is not None:
                raise PatchConflictError("CREATE requires an absent file and no before hash")
            content = self._required_content(patch)
            self._write(candidate, content, create=True)
            after_hash = hashlib.sha256(content).hexdigest()
        elif operation is PatchOperation.UPDATE:
            self._require_matching_hash(patch.before_hash, before_hash)
            content = self._required_content(patch)
            if hashlib.sha256(content).hexdigest() == before_hash:
                raise WorkspaceError("UPDATE must change the file content")
            self._write(candidate, content, create=False)
            after_hash = hashlib.sha256(content).hexdigest()
        else:
            self._require_matching_hash(patch.before_hash, before_hash)
            if patch.content is not None:
                raise WorkspaceError("DELETE must not include content")
            candidate.unlink()
            after_hash = None
        return Patch(
            file_path=relative,
            operation=operation.value,
            before_hash=before_hash,
            reason=patch.reason,
            after_hash=after_hash,
        )

    def _required_content(self, patch: Patch) -> bytes:
        if patch.content is None:
            raise WorkspaceError(f"{patch.operation} requires content")
        if len(patch.content) > self.max_bytes:
            raise WorkspaceError(f"Patch content exceeds the {self.max_bytes} byte limit")
        return patch.content

    @staticmethod
    def _require_matching_hash(expected: str | None, actual: str | None) -> None:
        if expected is None:
            raise PatchConflictError("Operation requires a before hash")
        if actual is None or not hmac.compare_digest(expected, actual):
            raise PatchConflictError("File content does not match the expected before hash")

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise WorkspaceError("Patch target is not a regular file")
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write(path: Path, content: bytes, create: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o644 if create else stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".forge-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, mode)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if create and path.exists():
                raise PatchConflictError("File appeared while applying CREATE")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
