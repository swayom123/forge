"""HTTP request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from forge.core.state import TaskStatus, TaskType


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
