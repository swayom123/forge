"""HTTP request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from forge.core.state import (
    ExecutionStatus,
    PatchOperation,
    TaskStatus,
    TaskType,
    VerificationStatus,
    WorkspaceStatus,
)


class RegisterRepositoryRequest(BaseModel):
    """Local path to a Git repository root."""

    path: str = Field(min_length=1)


class RepositoryResponse(BaseModel):
    """Registered repository identity."""

    id: str
    path: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateTaskRequest(BaseModel):
    """A new engineering request; Phase 1 queues it only."""

    repository_id: str
    objective: str = Field(min_length=1, max_length=20000)
    task_type: TaskType = TaskType.IMPLEMENT


class TaskResponse(BaseModel):
    """Persisted task and trace identity."""

    id: str
    repository_id: str
    objective: str
    task_type: TaskType
    status: TaskStatus
    trace_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RepositoryProfileResponse(BaseModel):
    """Detected repository technology and layout."""

    root: str
    name: str
    is_git_repository: bool
    languages: tuple[str, ...]
    frameworks: tuple[str, ...]
    package_managers: tuple[str, ...]
    test_frameworks: tuple[str, ...]
    lint_tools: tuple[str, ...]
    type_checkers: tuple[str, ...]
    build_commands: tuple[str, ...]
    test_commands: tuple[str, ...]
    source_directories: tuple[str, ...]
    test_directories: tuple[str, ...]
    entry_points: tuple[str, ...]
    ci_configuration: tuple[str, ...]
    architecture_summary: str


class IndexUpdateResponse(BaseModel):
    """Measured result of an incremental index operation."""

    indexed_files: int
    unchanged_files: int
    deleted_files: int
    parse_errors: int
    profile: RepositoryProfileResponse


class SymbolResponse(BaseModel):
    """An indexed symbol definition."""

    name: str
    qualified_name: str
    kind: str
    file_path: str
    line_start: int
    line_end: int
    signature: str

    model_config = {"from_attributes": True}


class TextMatchResponse(BaseModel):
    """One source line matching a text query."""

    file_path: str
    line: int
    text: str

    model_config = {"from_attributes": True}


class ImportResponse(BaseModel):
    """One indexed import statement target."""

    file_path: str
    module: str
    imported_name: str | None
    level: int
    line: int

    model_config = {"from_attributes": True}


class IssueUnderstandingResponse(BaseModel):
    """Normalized engineering request used by the planner."""

    summary: str
    task_type: str
    keywords: tuple[str, ...]
    explicit_paths: tuple[str, ...]
    constraints: tuple[str, ...]

    model_config = {"from_attributes": True}


class AffectedFileResponse(BaseModel):
    """An indexed file estimated to be relevant to a task."""

    path: str
    confidence: str
    reason: str
    evidence: tuple[str, ...]

    model_config = {"from_attributes": True}


class TaskPlanResponse(BaseModel):
    """A persisted, index-grounded task plan."""

    task_id: str
    issue: IssueUnderstandingResponse
    steps: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    affected_files: tuple[AffectedFileResponse, ...]
    validation_commands: tuple[tuple[str, ...], ...]
    context_fingerprint: str
    stale: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceResponse(BaseModel):
    """An isolated Git worktree allocated to a task."""

    id: str
    task_id: str
    path: str
    base_commit: str
    status: WorkspaceStatus
    created_at: datetime
    removed_at: datetime | None

    model_config = {"from_attributes": True}


class ApplyPatchRequest(BaseModel):
    """One optimistic text-file mutation inside a task workspace."""

    file_path: str = Field(min_length=1, max_length=1000)
    operation: PatchOperation
    before_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content: str | None = Field(default=None, max_length=1_000_000)
    reason: str = Field(min_length=1, max_length=2000)


class PatchResponse(BaseModel):
    """Immutable audit metadata for an applied workspace mutation."""

    id: str
    workspace_id: str
    file_path: str
    operation: PatchOperation
    before_hash: str | None
    after_hash: str | None
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RunCommandRequest(BaseModel):
    """One exact validation command selected from the persisted task plan."""

    argv: list[str] = Field(min_length=1, max_length=64)


class ExecutionResponse(BaseModel):
    """Persisted output and status of one sandbox command."""

    id: str
    task_id: str
    workspace_id: str
    argv: tuple[str, ...]
    status: ExecutionStatus
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int | None
    timed_out: bool
    output_truncated: bool
    started_at: datetime
    finished_at: datetime | None


class VerificationResponse(BaseModel):
    """One complete planned verification attempt and its command evidence."""

    id: str
    task_id: str
    workspace_id: str
    attempt_number: int
    status: VerificationStatus
    patch_fingerprint: str
    summary: str
    executions: tuple[ExecutionResponse, ...]
    failed_attempts: int
    failed_attempts_remaining: int
    started_at: datetime
    finished_at: datetime | None
