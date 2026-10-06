"""Forge FastAPI service."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from forge.apps.schemas import (
    ApplyPatchRequest,
    CreateTaskRequest,
    ExecutionResponse,
    ImportResponse,
    IndexUpdateResponse,
    PatchResponse,
    RegisterRepositoryRequest,
    RepositoryProfileResponse,
    RepositoryResponse,
    RunCommandRequest,
    SymbolResponse,
    TaskPlanResponse,
    TaskResponse,
    TextMatchResponse,
    VerificationResponse,
    WorkspaceResponse,
)
from forge.config import get_settings
from forge.core.contracts import ExecutionResult, Patch, RepositoryProfile
from forge.core.database import get_session, init_db
from forge.core.models import (
    EngineeringTask,
    ExecutionRecord,
    PatchRecord,
    Repository,
    RepositoryProfileRecord,
    TaskPlanRecord,
    TaskWorkspaceRecord,
    VerificationAttemptRecord,
    VerificationExecutionRecord,
    new_id,
)
from forge.core.state import (
    ExecutionStatus,
    TaskStatus,
    TaskType,
    VerificationStatus,
    WorkspaceStatus,
)
from forge.logging import configure_logging
from forge.planning import (
    IndexGroundedTaskPlanner,
    current_index_fingerprint,
    plan_from_json,
    plan_to_json,
)
from forge.repository.files import configured_scan_policy
from forge.repository.indexer import SqlRepositoryIndexer, profile_from_json
from forge.repository.scanner import LocalRepositoryScanner
from forge.repository.search import ImportMatch, RepositorySearch, SymbolMatch, TextMatch
from forge.sandbox import BubblewrapSandboxExecutor, SandboxError
from forge.verification import GateVerifier, workspace_patch_fingerprint
from forge.workspaces import (
    AuditedPatchManager,
    GitWorktreeManager,
    PatchConflictError,
    WorkspaceError,
)

logger = logging.getLogger("forge.api")
SessionDependency = Annotated[Session, Depends(get_session)]


def get_worktree_manager() -> GitWorktreeManager:
    """Build the configured isolated-worktree service."""
    settings = get_settings()
    return GitWorktreeManager(
        settings.worktree_root,
        max_files=settings.worktree_max_files,
        max_bytes=settings.worktree_max_bytes,
    )


WorktreeDependency = Annotated[GitWorktreeManager, Depends(get_worktree_manager)]


def get_sandbox_executor() -> BubblewrapSandboxExecutor:
    """Build the configured fail-closed sandbox service."""
    settings = get_settings()
    return BubblewrapSandboxExecutor(
        bwrap_path=settings.sandbox_bwrap_path,
        prlimit_path=settings.sandbox_prlimit_path,
        timeout_seconds=settings.sandbox_timeout_seconds,
        cpu_seconds=settings.sandbox_cpu_seconds,
        memory_bytes=settings.sandbox_memory_bytes,
        file_bytes=settings.sandbox_file_bytes,
        output_bytes=settings.sandbox_output_bytes,
        max_processes=settings.sandbox_max_processes,
        max_open_files=settings.sandbox_max_open_files,
    )


SandboxDependency = Annotated[BubblewrapSandboxExecutor, Depends(get_sandbox_executor)]


def profile_response(profile: RepositoryProfile) -> RepositoryProfileResponse:
    """Convert the internal Path-bearing profile into its HTTP representation."""
    data = dict(vars(profile))
    data["root"] = str(data["root"])
    return RepositoryProfileResponse(**data)


def task_plan_response(
    record: TaskPlanRecord, repository_id: str, session: Session
) -> TaskPlanResponse:
    """Convert a persisted plan and report whether its index context has changed."""
    plan = plan_from_json(record.plan_json)
    if plan.issue is None:  # pragma: no cover - persisted Phase 3 plans always include it
        raise ValueError("Persisted task plan has no issue understanding")
    return TaskPlanResponse.model_validate(
        {
            "task_id": record.task_id,
            "issue": plan.issue,
            "steps": plan.steps,
            "acceptance_criteria": plan.acceptance_criteria,
            "affected_files": plan.affected_files,
            "validation_commands": plan.validation_commands,
            "context_fingerprint": plan.context_fingerprint,
            "stale": current_index_fingerprint(session, repository_id) != record.index_fingerprint,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
    )


def execution_response(record: ExecutionRecord) -> ExecutionResponse:
    """Convert persisted JSON argv into the public execution representation."""
    return ExecutionResponse(
        id=record.id,
        task_id=record.task_id,
        workspace_id=record.workspace_id,
        argv=tuple(json.loads(record.argv_json)),
        status=ExecutionStatus(record.status),
        exit_code=record.exit_code,
        stdout=record.stdout,
        stderr=record.stderr,
        duration_ms=record.duration_ms,
        timed_out=record.timed_out,
        output_truncated=record.output_truncated,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def verification_response(
    record: VerificationAttemptRecord, session: Session, max_failed_attempts: int
) -> VerificationResponse:
    """Build a verification response with ordered command evidence and retry budget."""
    links = session.scalars(
        select(VerificationExecutionRecord)
        .where(VerificationExecutionRecord.verification_id == record.id)
        .order_by(VerificationExecutionRecord.position)
    )
    executions = tuple(execution_response(link.execution) for link in links)
    failed_attempts = len(
        tuple(
            session.scalars(
                select(VerificationAttemptRecord.id).where(
                    VerificationAttemptRecord.task_id == record.task_id,
                    VerificationAttemptRecord.status == VerificationStatus.FAILED.value,
                )
            )
        )
    )
    return VerificationResponse(
        id=record.id,
        task_id=record.task_id,
        workspace_id=record.workspace_id,
        attempt_number=record.attempt_number,
        status=VerificationStatus(record.status),
        patch_fingerprint=record.patch_fingerprint,
        summary=record.summary,
        executions=executions,
        failed_attempts=failed_attempts,
        failed_attempts_remaining=max(0, max_failed_attempts - failed_attempts),
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize storage before serving requests."""
    configure_logging(get_settings().log_level)
    init_db()
    yield


app = FastAPI(title="Forge", version="0.6.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Return service liveness."""
    return {"status": "ok"}


@app.post(
    "/repositories/register", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED
)
def register_repository(body: RegisterRepositoryRequest, session: SessionDependency) -> Repository:
    """Record the identity of a local Git repository."""
    try:
        profile = LocalRepositoryScanner().scan(Path(body.path))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = session.scalar(select(Repository).where(Repository.path == str(profile.root)))
    if existing is not None:
        return existing
    repository = Repository(path=str(profile.root), name=profile.name)
    session.add(repository)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Repository was registered concurrently"
        ) from None
    session.refresh(repository)
    logger.info("repository registered", extra={"repository_id": repository.id})
    return repository


@app.get("/repositories/{repository_id}", response_model=RepositoryResponse)
def get_repository(repository_id: str, session: SessionDependency) -> Repository:
    """Fetch a registered repository."""
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repository


@app.post("/repositories/{repository_id}/index", response_model=IndexUpdateResponse)
def index_repository(repository_id: str, session: SessionDependency) -> IndexUpdateResponse:
    """Profile and incrementally index a registered repository."""
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        result = SqlRepositoryIndexer(session, configured_scan_policy()).update(
            repository.id, Path(repository.path)
        )
    except (OSError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = session.get(RepositoryProfileRecord, repository_id)
    if record is None:  # pragma: no cover - guarded by the transactional indexer
        raise HTTPException(status_code=500, detail="Profile was not persisted")
    profile = profile_from_json(record.profile_json)
    logger.info("repository indexed", extra={"repository_id": repository.id})
    return IndexUpdateResponse(**result.__dict__, profile=profile_response(profile))


@app.get("/repositories/{repository_id}/profile", response_model=RepositoryProfileResponse)
def get_repository_profile(
    repository_id: str, session: SessionDependency
) -> RepositoryProfileResponse:
    """Return the latest persisted repository profile."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    record = session.get(RepositoryProfileRecord, repository_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Repository has not been indexed")
    return profile_response(profile_from_json(record.profile_json))


@app.get("/repositories/{repository_id}/symbols", response_model=list[SymbolResponse])
def search_symbols(
    repository_id: str,
    session: SessionDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> tuple[SymbolMatch, ...]:
    """Search indexed definitions by symbol name."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).symbols(repository_id, query, limit)


@app.get("/repositories/{repository_id}/search", response_model=list[TextMatchResponse])
def search_source(
    repository_id: str,
    session: SessionDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> tuple[TextMatch, ...]:
    """Search lines from files admitted to the current source index."""
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).text(repository_id, Path(repository.path), query, limit)


@app.get("/repositories/{repository_id}/dependents", response_model=list[str])
def find_dependents(
    repository_id: str,
    session: SessionDependency,
    module: Annotated[str, Query(min_length=1, max_length=500)],
) -> tuple[str, ...]:
    """Return indexed files importing the requested module."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).dependents(repository_id, module)


@app.get("/repositories/{repository_id}/imports", response_model=list[ImportResponse])
def search_imports(
    repository_id: str,
    session: SessionDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> tuple[ImportMatch, ...]:
    """Search indexed imports by module or imported name."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).imports(repository_id, query, limit)


@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(body: CreateTaskRequest, session: SessionDependency) -> EngineeringTask:
    """Persist a pending task. No model or shell execution occurs."""
    if session.get(Repository, body.repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    task = EngineeringTask(
        repository_id=body.repository_id,
        objective=body.objective,
        task_type=body.task_type.value,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info("task created", extra={"task_id": task.id, "trace_id": task.trace_id})
    return task


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, session: SessionDependency) -> EngineeringTask:
    """Fetch a persisted task."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/tasks/{task_id}/plan", response_model=TaskPlanResponse)
def plan_task(task_id: str, session: SessionDependency) -> TaskPlanResponse:
    """Create or refresh a deterministic plan from the current repository index."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    profile_record = session.get(RepositoryProfileRecord, task.repository_id)
    if profile_record is None:
        raise HTTPException(status_code=409, detail="Repository must be indexed before planning")
    if task.status not in {TaskStatus.PENDING.value, TaskStatus.READY.value}:
        raise HTTPException(
            status_code=409, detail=f"Task in {task.status} state cannot be planned"
        )

    profile = profile_from_json(profile_record.profile_json)
    plan = IndexGroundedTaskPlanner(session).plan(
        task.repository_id, task.objective, task.task_type, profile
    )
    record = session.get(TaskPlanRecord, task.id)
    now = datetime.now(UTC)
    if record is None:
        record = TaskPlanRecord(
            task_id=task.id,
            plan_json=plan_to_json(plan),
            index_fingerprint=plan.context_fingerprint,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
    else:
        record.plan_json = plan_to_json(plan)
        record.index_fingerprint = plan.context_fingerprint
        record.updated_at = now
    task.status = TaskStatus.READY.value
    session.commit()
    session.refresh(record)
    logger.info("task planned", extra={"task_id": task.id, "trace_id": task.trace_id})
    return task_plan_response(record, task.repository_id, session)


@app.get("/tasks/{task_id}/plan", response_model=TaskPlanResponse)
def get_task_plan(task_id: str, session: SessionDependency) -> TaskPlanResponse:
    """Return a persisted plan and its freshness against the current index."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    record = session.get(TaskPlanRecord, task.id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task has not been planned")
    return task_plan_response(record, task.repository_id, session)


_EDIT_TASK_TYPES = {
    TaskType.IMPLEMENT.value,
    TaskType.DEBUG.value,
    TaskType.TEST.value,
    TaskType.DOCUMENT.value,
}


@app.post(
    "/tasks/{task_id}/workspace",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_workspace(
    task_id: str, session: SessionDependency, manager: WorktreeDependency
) -> TaskWorkspaceRecord:
    """Allocate an isolated worktree for a current, editable task plan."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.READY.value or task.task_type not in _EDIT_TASK_TYPES:
        raise HTTPException(status_code=409, detail="Task is not ready for an editable workspace")
    plan_record = session.get(TaskPlanRecord, task.id)
    if plan_record is None:
        raise HTTPException(
            status_code=409, detail="Task must be planned before workspace creation"
        )
    if current_index_fingerprint(session, task.repository_id) != plan_record.index_fingerprint:
        raise HTTPException(status_code=409, detail="Task plan is stale and must be refreshed")
    existing = session.scalar(
        select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task.id)
    )
    if existing is not None:
        if existing.status == WorkspaceStatus.ACTIVE.value:
            return existing
        raise HTTPException(status_code=409, detail="Task workspace has already been removed")
    repository = session.get(Repository, task.repository_id)
    if repository is None:  # pragma: no cover - protected by the task foreign key
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        index_is_current = SqlRepositoryIndexer(session, configured_scan_policy()).is_current(
            repository.id, Path(repository.path)
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not index_is_current:
        raise HTTPException(
            status_code=409, detail="Repository index is stale and must be refreshed"
        )

    workspace_id = new_id()
    try:
        workspace = manager.create(Path(repository.path), workspace_id)
    except WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = TaskWorkspaceRecord(
        id=workspace_id,
        task_id=task.id,
        path=str(workspace.path),
        base_commit=workspace.base_commit,
        status=WorkspaceStatus.ACTIVE.value,
    )
    session.add(record)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        manager.remove(Path(repository.path), workspace.path)
        raise
    session.refresh(record)
    logger.info("task workspace created", extra={"task_id": task.id, "trace_id": task.trace_id})
    return record


@app.get("/tasks/{task_id}/workspace", response_model=WorkspaceResponse)
def get_task_workspace(task_id: str, session: SessionDependency) -> TaskWorkspaceRecord:
    """Return the workspace allocated to a task."""
    if session.get(EngineeringTask, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    record = session.scalar(
        select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Task has no workspace")
    return record


@app.post(
    "/tasks/{task_id}/patches",
    response_model=PatchResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_task_patch(
    task_id: str,
    body: ApplyPatchRequest,
    session: SessionDependency,
    manager: WorktreeDependency,
) -> PatchRecord:
    """Apply one bounded, optimistic text-file mutation and record its hashes."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.READY.value:
        raise HTTPException(status_code=409, detail="Task is not ready for patching")
    workspace_record = session.scalar(
        select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
    )
    if workspace_record is None or workspace_record.status != WorkspaceStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Task has no active workspace")
    try:
        workspace_path = manager.validate(Path(workspace_record.path))
        applied = AuditedPatchManager(get_settings().patch_max_bytes).apply(
            workspace_path,
            Patch(
                file_path=Path(body.file_path),
                operation=body.operation.value,
                before_hash=body.before_hash,
                reason=body.reason,
                content=body.content.encode() if body.content is not None else None,
            ),
        )
    except PatchConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = PatchRecord(
        workspace_id=workspace_record.id,
        file_path=applied.file_path.as_posix(),
        operation=applied.operation,
        before_hash=applied.before_hash,
        after_hash=applied.after_hash,
        reason=applied.reason,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    logger.info(
        "task patch applied",
        extra={"task_id": task.id, "trace_id": task.trace_id, "patch_id": record.id},
    )
    return record


@app.get("/tasks/{task_id}/patches", response_model=list[PatchResponse])
def list_task_patches(task_id: str, session: SessionDependency) -> tuple[PatchRecord, ...]:
    """Return immutable patch audit records in application order."""
    if session.get(EngineeringTask, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    workspace = session.scalar(
        select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
    )
    if workspace is None:
        return ()
    return tuple(
        session.scalars(
            select(PatchRecord)
            .where(PatchRecord.workspace_id == workspace.id)
            .order_by(PatchRecord.created_at, PatchRecord.id)
        )
    )


@app.delete("/tasks/{task_id}/workspace", response_model=WorkspaceResponse)
def remove_task_workspace(
    task_id: str, session: SessionDependency, manager: WorktreeDependency
) -> TaskWorkspaceRecord:
    """Remove an active task workspace while retaining its audit records."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status == TaskStatus.RUNNING.value:
        raise HTTPException(status_code=409, detail="Cannot remove a running task workspace")
    workspace = session.scalar(
        select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Task has no workspace")
    if workspace.status == WorkspaceStatus.REMOVED.value:
        return workspace
    repository = session.get(Repository, task.repository_id)
    if repository is None:  # pragma: no cover - protected by the task foreign key
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        manager.remove(Path(repository.path), Path(workspace.path))
    except WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    workspace.status = WorkspaceStatus.REMOVED.value
    workspace.removed_at = datetime.now(UTC)
    session.commit()
    session.refresh(workspace)
    logger.info("task workspace removed", extra={"task_id": task.id, "trace_id": task.trace_id})
    return workspace


@app.post(
    "/tasks/{task_id}/executions",
    response_model=ExecutionResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_task_command(
    task_id: str,
    body: RunCommandRequest,
    session: SessionDependency,
    manager: WorktreeDependency,
    executor: SandboxDependency,
) -> ExecutionResponse:
    """Run one exact planned validation command in the ephemeral sandbox."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.READY.value:
        raise HTTPException(status_code=409, detail="Task is not ready for validation")
    workspace = session.scalar(
        select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
    )
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Task has no active workspace")
    plan_record = session.get(TaskPlanRecord, task_id)
    if plan_record is None:
        raise HTTPException(status_code=409, detail="Task has no persisted plan")
    plan = plan_from_json(plan_record.plan_json)
    argv = tuple(body.argv)
    if argv not in plan.validation_commands:
        raise HTTPException(status_code=403, detail="Command is not in the task verification plan")
    try:
        workspace_path = manager.validate(Path(workspace.path))
    except WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record = ExecutionRecord(
        task_id=task.id,
        workspace_id=workspace.id,
        argv_json=json.dumps(argv),
        status=ExecutionStatus.RUNNING.value,
        started_at=datetime.now(UTC),
    )
    task.status = TaskStatus.RUNNING.value
    session.add(record)
    session.commit()
    session.refresh(record)
    try:
        result = executor.run(workspace_path, argv)
    except SandboxError as exc:
        record.status = ExecutionStatus.ERROR.value
        record.stderr = str(exc)
        record.finished_at = datetime.now(UTC)
        task.status = TaskStatus.READY.value
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    record.status = (
        ExecutionStatus.TIMED_OUT.value if result.timed_out else ExecutionStatus.FINISHED.value
    )
    record.exit_code = result.exit_code
    record.stdout = result.stdout
    record.stderr = result.stderr
    record.duration_ms = result.duration_ms
    record.timed_out = result.timed_out
    record.output_truncated = result.output_truncated
    record.finished_at = datetime.now(UTC)
    task.status = TaskStatus.READY.value
    session.commit()
    session.refresh(record)
    logger.info(
        "task command executed",
        extra={"task_id": task.id, "trace_id": task.trace_id, "execution_id": record.id},
    )
    return execution_response(record)


@app.get("/tasks/{task_id}/executions", response_model=list[ExecutionResponse])
def list_task_executions(task_id: str, session: SessionDependency) -> list[ExecutionResponse]:
    """Return sandbox execution records in start order."""
    if session.get(EngineeringTask, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    records = session.scalars(
        select(ExecutionRecord)
        .where(ExecutionRecord.task_id == task_id)
        .order_by(ExecutionRecord.started_at, ExecutionRecord.id)
    )
    return [execution_response(record) for record in records]


@app.post(
    "/tasks/{task_id}/verify",
    response_model=VerificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def verify_task(
    task_id: str,
    session: SessionDependency,
    manager: WorktreeDependency,
    executor: SandboxDependency,
) -> VerificationResponse:
    """Run every planned command and advance the bounded repair lifecycle."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.READY.value:
        raise HTTPException(status_code=409, detail="Task is not ready for verification")
    workspace = session.scalar(
        select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
    )
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Task has no active workspace")
    plan_record = session.get(TaskPlanRecord, task_id)
    if plan_record is None:
        raise HTTPException(status_code=409, detail="Task has no persisted plan")
    plan = plan_from_json(plan_record.plan_json)
    if not plan.validation_commands:
        raise HTTPException(status_code=409, detail="Task plan has no automated verification gates")
    try:
        workspace_path = manager.validate(Path(workspace.path))
    except WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    max_failures = get_settings().verification_max_failed_attempts
    if max_failures < 1:
        raise HTTPException(status_code=500, detail="Verification failure limit must be positive")
    attempts = tuple(
        session.scalars(
            select(VerificationAttemptRecord)
            .where(VerificationAttemptRecord.task_id == task_id)
            .order_by(VerificationAttemptRecord.attempt_number)
        )
    )
    failed_attempts = sum(attempt.status == VerificationStatus.FAILED.value for attempt in attempts)
    if failed_attempts >= max_failures:
        task.status = TaskStatus.BLOCKED.value
        session.commit()
        raise HTTPException(status_code=409, detail="Verification failure limit is exhausted")
    patch_fingerprint = workspace_patch_fingerprint(session, workspace)
    if (
        attempts
        and attempts[-1].status == VerificationStatus.FAILED.value
        and attempts[-1].patch_fingerprint == patch_fingerprint
    ):
        raise HTTPException(
            status_code=409,
            detail="Apply a new audited patch before retrying failed verification",
        )

    attempt = VerificationAttemptRecord(
        task_id=task.id,
        workspace_id=workspace.id,
        attempt_number=(attempts[-1].attempt_number + 1) if attempts else 1,
        status=VerificationStatus.RUNNING.value,
        patch_fingerprint=patch_fingerprint,
        started_at=datetime.now(UTC),
    )
    task.status = TaskStatus.RUNNING.value
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    results: list[ExecutionResult] = []
    infrastructure_error: str | None = None
    for position, argv in enumerate(plan.validation_commands):
        execution = ExecutionRecord(
            task_id=task.id,
            workspace_id=workspace.id,
            argv_json=json.dumps(argv),
            status=ExecutionStatus.RUNNING.value,
            started_at=datetime.now(UTC),
        )
        session.add(execution)
        session.flush()
        session.add(
            VerificationExecutionRecord(
                verification_id=attempt.id,
                execution_id=execution.id,
                position=position,
            )
        )
        session.commit()
        try:
            result = executor.run(workspace_path, argv)
        except SandboxError as exc:
            infrastructure_error = str(exc)
            execution.status = ExecutionStatus.ERROR.value
            execution.stderr = infrastructure_error
            execution.finished_at = datetime.now(UTC)
            session.commit()
            break
        execution.status = (
            ExecutionStatus.TIMED_OUT.value if result.timed_out else ExecutionStatus.FINISHED.value
        )
        execution.exit_code = result.exit_code
        execution.stdout = result.stdout
        execution.stderr = result.stderr
        execution.duration_ms = result.duration_ms
        execution.timed_out = result.timed_out
        execution.output_truncated = result.output_truncated
        execution.finished_at = datetime.now(UTC)
        results.append(result)
        session.commit()

    verifier = GateVerifier()
    if infrastructure_error is not None:
        attempt.status = VerificationStatus.ERROR.value
        attempt.summary = f"Sandbox infrastructure error: {infrastructure_error[:500]}"
        task.status = TaskStatus.READY.value
    elif verifier.verify(plan, tuple(results)):
        attempt.status = VerificationStatus.PASSED.value
        attempt.summary = verifier.summary(plan, tuple(results))
        task.status = TaskStatus.VERIFIED.value
    else:
        attempt.status = VerificationStatus.FAILED.value
        attempt.summary = verifier.summary(plan, tuple(results))
        failed_attempts += 1
        task.status = (
            TaskStatus.BLOCKED.value if failed_attempts >= max_failures else TaskStatus.READY.value
        )
    attempt.finished_at = datetime.now(UTC)
    session.commit()
    session.refresh(attempt)
    logger.info(
        "task verification finished",
        extra={
            "task_id": task.id,
            "trace_id": task.trace_id,
            "verification_id": attempt.id,
            "verification_status": attempt.status,
        },
    )
    return verification_response(attempt, session, max_failures)


@app.get("/tasks/{task_id}/verifications", response_model=list[VerificationResponse])
def list_task_verifications(task_id: str, session: SessionDependency) -> list[VerificationResponse]:
    """Return complete verification attempts and ordered command evidence."""
    if session.get(EngineeringTask, task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    max_failures = max(1, get_settings().verification_max_failed_attempts)
    attempts = session.scalars(
        select(VerificationAttemptRecord)
        .where(VerificationAttemptRecord.task_id == task_id)
        .order_by(VerificationAttemptRecord.attempt_number)
    )
    return [verification_response(attempt, session, max_failures) for attempt in attempts]
