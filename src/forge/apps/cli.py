"""Local Forge command line interface."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from forge.config import get_settings
from forge.core.contracts import Patch
from forge.core.database import SessionLocal, init_db
from forge.core.models import (
    EngineeringTask,
    ExecutionRecord,
    PatchRecord,
    Repository,
    RepositoryProfileRecord,
    TaskPlanRecord,
    TaskWorkspaceRecord,
    new_id,
)
from forge.core.state import (
    ExecutionStatus,
    PatchOperation,
    TaskStatus,
    TaskType,
    WorkspaceStatus,
)
from forge.planning import (
    IndexGroundedTaskPlanner,
    current_index_fingerprint,
    plan_from_json,
    plan_to_json,
)
from forge.repository.files import configured_scan_policy
from forge.repository.indexer import SqlRepositoryIndexer, profile_from_json
from forge.repository.profiler import RepositoryProfiler
from forge.repository.scanner import LocalRepositoryScanner
from forge.repository.search import RepositorySearch
from forge.sandbox import BubblewrapSandboxExecutor, SandboxError
from forge.workspaces import AuditedPatchManager, GitWorktreeManager, WorkspaceError

app = typer.Typer(help="Forge repository intelligence and task CLI.")


def _worktree_manager() -> GitWorktreeManager:
    settings = get_settings()
    return GitWorktreeManager(
        settings.worktree_root,
        max_files=settings.worktree_max_files,
        max_bytes=settings.worktree_max_bytes,
    )


def _sandbox_executor() -> BubblewrapSandboxExecutor:
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


@app.command()
def inspect(path: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Profile a local Git repository without running its code."""
    try:
        profile = RepositoryProfiler(configured_scan_policy()).profile(path)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            {
                **profile.__dict__,
                "root": str(profile.root),
            },
            indent=2,
        )
    )


@app.command()
def register(path: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Register a local Git repository."""
    try:
        profile = LocalRepositoryScanner().scan(path)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    init_db()
    with SessionLocal() as session:
        repository = session.scalar(select(Repository).where(Repository.path == str(profile.root)))
        if repository is None:
            repository = Repository(path=str(profile.root), name=profile.name)
            session.add(repository)
            session.commit()
            session.refresh(repository)
        typer.echo(f"Repository ID: {repository.id}")


@app.command()
def task(repository_id: str, objective: str, task_type: TaskType = TaskType.IMPLEMENT) -> None:
    """Record a pending engineering task."""
    init_db()
    with SessionLocal() as session:
        if session.get(Repository, repository_id) is None:
            raise typer.BadParameter("Repository ID does not exist")
        record = EngineeringTask(
            repository_id=repository_id,
            objective=objective,
            task_type=task_type.value,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        typer.echo(f"Task ID: {record.id}\nStatus: {record.status}\nTrace ID: {record.trace_id}")


@app.command()
def status(task_id: str) -> None:
    """Show the persisted state of a task."""
    init_db()
    with SessionLocal() as session:
        record = session.get(EngineeringTask, task_id)
        if record is None:
            raise typer.BadParameter("Task ID does not exist")
        typer.echo(f"Task: {record.id}\nStatus: {record.status}\nObjective: {record.objective}")


@app.command("index")
def index_repository(repository_id: str) -> None:
    """Profile and incrementally index a registered repository."""
    init_db()
    with SessionLocal() as session:
        repository = session.get(Repository, repository_id)
        if repository is None:
            raise typer.BadParameter("Repository ID does not exist")
        try:
            result = SqlRepositoryIndexer(session, configured_scan_policy()).update(
                repository.id, Path(repository.path)
            )
        except (OSError, ValueError) as exc:
            session.rollback()
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(json.dumps(result.__dict__, indent=2))


@app.command()
def search(repository_id: str, query: str, limit: int = 50) -> None:
    """Search indexed symbol definitions."""
    if limit < 1 or limit > 200:
        raise typer.BadParameter("Limit must be between 1 and 200")
    init_db()
    with SessionLocal() as session:
        if session.get(Repository, repository_id) is None:
            raise typer.BadParameter("Repository ID does not exist")
        matches = RepositorySearch(session).symbols(repository_id, query, limit)
        typer.echo(json.dumps([match.__dict__ for match in matches], indent=2))


@app.command("plan")
def plan_task(task_id: str) -> None:
    """Create or refresh an index-grounded plan for a pending task."""
    init_db()
    with SessionLocal() as session:
        task_record = session.get(EngineeringTask, task_id)
        if task_record is None:
            raise typer.BadParameter("Task ID does not exist")
        profile_record = session.get(RepositoryProfileRecord, task_record.repository_id)
        if profile_record is None:
            raise typer.BadParameter("Repository must be indexed before planning")
        if task_record.status not in {TaskStatus.PENDING.value, TaskStatus.READY.value}:
            raise typer.BadParameter(f"Task in {task_record.status} state cannot be planned")
        profile = profile_from_json(profile_record.profile_json)
        result = IndexGroundedTaskPlanner(session).plan(
            task_record.repository_id,
            task_record.objective,
            task_record.task_type,
            profile,
        )
        record = session.get(TaskPlanRecord, task_id)
        now = datetime.now(UTC)
        if record is None:
            record = TaskPlanRecord(
                task_id=task_id,
                plan_json=plan_to_json(result),
                index_fingerprint=result.context_fingerprint,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.plan_json = plan_to_json(result)
            record.index_fingerprint = result.context_fingerprint
            record.updated_at = now
        task_record.status = TaskStatus.READY.value
        session.commit()
        typer.echo(json.dumps(asdict(result), indent=2))


@app.command("show-plan")
def show_plan(task_id: str) -> None:
    """Show a task's persisted plan."""
    init_db()
    with SessionLocal() as session:
        if session.get(EngineeringTask, task_id) is None:
            raise typer.BadParameter("Task ID does not exist")
        record = session.get(TaskPlanRecord, task_id)
        if record is None:
            raise typer.BadParameter("Task has not been planned")
        typer.echo(json.dumps(asdict(plan_from_json(record.plan_json)), indent=2))


@app.command("workspace")
def create_workspace(task_id: str) -> None:
    """Create an isolated worktree for a current editable plan."""
    init_db()
    with SessionLocal() as session:
        task_record = session.get(EngineeringTask, task_id)
        if task_record is None:
            raise typer.BadParameter("Task ID does not exist")
        if task_record.status != TaskStatus.READY.value or task_record.task_type not in {
            TaskType.IMPLEMENT.value,
            TaskType.DEBUG.value,
            TaskType.TEST.value,
            TaskType.DOCUMENT.value,
        }:
            raise typer.BadParameter("Task is not ready for an editable workspace")
        plan_record = session.get(TaskPlanRecord, task_id)
        if plan_record is None:
            raise typer.BadParameter("Task must be planned before workspace creation")
        if (
            current_index_fingerprint(session, task_record.repository_id)
            != plan_record.index_fingerprint
        ):
            raise typer.BadParameter("Task plan is stale and must be refreshed")
        existing = session.scalar(
            select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
        )
        if existing is not None:
            typer.echo(json.dumps({"id": existing.id, "path": existing.path}, indent=2))
            return
        repository = session.get(Repository, task_record.repository_id)
        if repository is None:
            raise typer.BadParameter("Repository ID does not exist")
        try:
            index_is_current = SqlRepositoryIndexer(session, configured_scan_policy()).is_current(
                repository.id, Path(repository.path)
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        if not index_is_current:
            raise typer.BadParameter("Repository index is stale and must be refreshed")
        workspace_id = new_id()
        try:
            workspace = _worktree_manager().create(Path(repository.path), workspace_id)
        except WorkspaceError as exc:
            raise typer.BadParameter(str(exc)) from exc
        record = TaskWorkspaceRecord(
            id=workspace_id,
            task_id=task_id,
            path=str(workspace.path),
            base_commit=workspace.base_commit,
            status=WorkspaceStatus.ACTIVE.value,
        )
        session.add(record)
        session.commit()
        typer.echo(
            json.dumps(
                {"id": record.id, "path": record.path, "base_commit": record.base_commit},
                indent=2,
            )
        )


@app.command("apply-patch")
def apply_patch(
    task_id: str,
    file_path: Path,
    operation: PatchOperation,
    reason: Annotated[str, typer.Option("--reason")],
    before_hash: Annotated[str | None, typer.Option("--before-hash")] = None,
    content_file: Annotated[Path | None, typer.Option("--content-file")] = None,
) -> None:
    """Apply one audited file mutation to an active task workspace."""
    init_db()
    with SessionLocal() as session:
        task_record = session.get(EngineeringTask, task_id)
        if task_record is None or task_record.status != TaskStatus.READY.value:
            raise typer.BadParameter("Task is not ready for patching")
        workspace = session.scalar(
            select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
        )
        if workspace is None or workspace.status != WorkspaceStatus.ACTIVE.value:
            raise typer.BadParameter("Task has no active workspace")
        try:
            content = content_file.read_bytes() if content_file is not None else None
            workspace_path = _worktree_manager().validate(Path(workspace.path))
            applied = AuditedPatchManager(get_settings().patch_max_bytes).apply(
                workspace_path,
                Patch(file_path, operation.value, before_hash, reason, content),
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        record = PatchRecord(
            workspace_id=workspace.id,
            file_path=applied.file_path.as_posix(),
            operation=applied.operation,
            before_hash=applied.before_hash,
            after_hash=applied.after_hash,
            reason=applied.reason,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        typer.echo(json.dumps({"patch_id": record.id, **asdict(applied)}, indent=2, default=str))


@app.command("remove-workspace")
def remove_workspace(task_id: str) -> None:
    """Remove a task worktree while retaining its patch audit records."""
    init_db()
    with SessionLocal() as session:
        task_record = session.get(EngineeringTask, task_id)
        workspace = session.scalar(
            select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
        )
        if task_record is None or workspace is None:
            raise typer.BadParameter("Task has no workspace")
        if task_record.status == TaskStatus.RUNNING.value:
            raise typer.BadParameter("Cannot remove a running task workspace")
        if workspace.status == WorkspaceStatus.REMOVED.value:
            typer.echo("Workspace already removed")
            return
        repository = session.get(Repository, task_record.repository_id)
        if repository is None:
            raise typer.BadParameter("Repository ID does not exist")
        try:
            _worktree_manager().remove(Path(repository.path), Path(workspace.path))
        except WorkspaceError as exc:
            raise typer.BadParameter(str(exc)) from exc
        workspace.status = WorkspaceStatus.REMOVED.value
        workspace.removed_at = datetime.now(UTC)
        session.commit()
        typer.echo("Workspace removed")


@app.command("execute")
def execute_validation(task_id: str, command_index: int = 0) -> None:
    """Execute one saved verification command by its zero-based plan index."""
    init_db()
    with SessionLocal() as session:
        task_record = session.get(EngineeringTask, task_id)
        if task_record is None or task_record.status != TaskStatus.READY.value:
            raise typer.BadParameter("Task is not ready for validation")
        workspace = session.scalar(
            select(TaskWorkspaceRecord).where(TaskWorkspaceRecord.task_id == task_id)
        )
        if workspace is None or workspace.status != WorkspaceStatus.ACTIVE.value:
            raise typer.BadParameter("Task has no active workspace")
        plan_record = session.get(TaskPlanRecord, task_id)
        if plan_record is None:
            raise typer.BadParameter("Task has no persisted plan")
        commands = plan_from_json(plan_record.plan_json).validation_commands
        if command_index < 0 or command_index >= len(commands):
            raise typer.BadParameter("Verification command index is out of range")
        argv = commands[command_index]
        try:
            workspace_path = _worktree_manager().validate(Path(workspace.path))
        except WorkspaceError as exc:
            raise typer.BadParameter(str(exc)) from exc
        record = ExecutionRecord(
            task_id=task_id,
            workspace_id=workspace.id,
            argv_json=json.dumps(argv),
            status=ExecutionStatus.RUNNING.value,
            started_at=datetime.now(UTC),
        )
        task_record.status = TaskStatus.RUNNING.value
        session.add(record)
        session.commit()
        session.refresh(record)
        try:
            result = _sandbox_executor().run(workspace_path, argv)
        except SandboxError as exc:
            record.status = ExecutionStatus.ERROR.value
            record.stderr = str(exc)
            record.finished_at = datetime.now(UTC)
            task_record.status = TaskStatus.READY.value
            session.commit()
            raise typer.BadParameter(str(exc)) from exc
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
        task_record.status = TaskStatus.READY.value
        session.commit()
        typer.echo(
            json.dumps(
                {"execution_id": record.id, "argv": argv, **asdict(result)},
                indent=2,
            )
        )


@app.command("executions")
def list_executions(task_id: str) -> None:
    """List persisted sandbox results for a task."""
    init_db()
    with SessionLocal() as session:
        if session.get(EngineeringTask, task_id) is None:
            raise typer.BadParameter("Task ID does not exist")
        records = session.scalars(
            select(ExecutionRecord)
            .where(ExecutionRecord.task_id == task_id)
            .order_by(ExecutionRecord.started_at, ExecutionRecord.id)
        )
        typer.echo(
            json.dumps(
                [
                    {
                        "id": record.id,
                        "argv": json.loads(record.argv_json),
                        "status": record.status,
                        "exit_code": record.exit_code,
                        "stdout": record.stdout,
                        "stderr": record.stderr,
                        "duration_ms": record.duration_ms,
                        "timed_out": record.timed_out,
                        "output_truncated": record.output_truncated,
                    }
                    for record in records
                ],
                indent=2,
            )
        )


if __name__ == "__main__":
    app()
