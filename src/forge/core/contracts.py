"""Contracts for later phases; implementations must report real work."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RepositoryProfile:
    """Detected repository identity, tooling, and layout."""

    root: Path
    name: str
    is_git_repository: bool
    languages: tuple[str, ...] = ()
    frameworks: tuple[str, ...] = ()
    package_managers: tuple[str, ...] = ()
    test_frameworks: tuple[str, ...] = ()
    lint_tools: tuple[str, ...] = ()
    type_checkers: tuple[str, ...] = ()
    build_commands: tuple[str, ...] = ()
    test_commands: tuple[str, ...] = ()
    source_directories: tuple[str, ...] = ()
    test_directories: tuple[str, ...] = ()
    entry_points: tuple[str, ...] = ()
    ci_configuration: tuple[str, ...] = ()
    architecture_summary: str = ""


@dataclass(frozen=True)
class IssueUnderstanding:
    """Normalized request details that can be traced back to the objective."""

    summary: str
    task_type: str
    keywords: tuple[str, ...]
    explicit_paths: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class AffectedFile:
    """An indexed file estimated to be relevant, with ranking evidence."""

    path: str
    confidence: str
    reason: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    """Explicit proposed steps and verification commands."""

    steps: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    validation_commands: tuple[tuple[str, ...], ...]
    issue: IssueUnderstanding | None = None
    affected_files: tuple[AffectedFile, ...] = ()
    context_fingerprint: str = ""


@dataclass(frozen=True)
class Patch:
    """A proposed file change and its resulting audit hashes."""

    file_path: Path
    operation: str
    before_hash: str | None
    reason: str
    content: bytes | None = None
    after_hash: str | None = None


@dataclass(frozen=True)
class Workspace:
    """An isolated Git worktree pinned to a base commit."""

    path: Path
    base_commit: str


@dataclass(frozen=True)
class ExecutionResult:
    """Captured command result from an isolated executor."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int = 0
    timed_out: bool = False
    output_truncated: bool = False


class RepositoryScanner(Protocol):
    """Inspect a repository without executing its contents."""

    def scan(self, root: Path) -> RepositoryProfile: ...


class RepositoryIndexer(Protocol):
    """Build and update a searchable repository index."""

    def update(self, repository_id: str, root: Path) -> "IndexUpdate": ...


@dataclass(frozen=True)
class IndexUpdate:
    """Measured result of one incremental index update."""

    indexed_files: int
    unchanged_files: int
    deleted_files: int
    parse_errors: int


class TaskPlanner(Protocol):
    """Turn a request and retrieved repository context into an actionable plan."""

    def plan(
        self,
        repository_id: str,
        objective: str,
        task_type: str,
        profile: RepositoryProfile,
    ) -> Plan: ...


class PatchManager(Protocol):
    """Apply an audited patch in an isolated worktree."""

    def apply(self, root: Path, patch: Patch) -> Patch: ...


class SandboxExecutor(Protocol):
    """Execute validated arguments inside a constrained sandbox."""

    def run(self, root: Path, argv: tuple[str, ...]) -> ExecutionResult: ...


class Verifier(Protocol):
    """Check acceptance criteria and project validation results."""

    def verify(self, plan: Plan, results: tuple[ExecutionResult, ...]) -> bool: ...
