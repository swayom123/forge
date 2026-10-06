"""Persistent repository and task records."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.core.database import Base
from forge.core.state import TaskStatus, TaskType


def new_id() -> str:
    """Generate an opaque persistent identifier."""
    return str(uuid4())


class Repository(Base):
    """A registered local Git repository."""

    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    tasks: Mapped[list["EngineeringTask"]] = relationship(back_populates="repository")
    profile: Mapped["RepositoryProfileRecord | None"] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    indexed_files: Mapped[list["IndexedFile"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class EngineeringTask(Base):
    """A persisted engineering request and its controlled lifecycle."""

    __tablename__ = "engineering_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(String(20), default=TaskType.IMPLEMENT.value)
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING.value)
    trace_id: Mapped[str] = mapped_column(String(36), default=new_id)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    repository: Mapped[Repository] = relationship(back_populates="tasks")
    plan: Mapped["TaskPlanRecord | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    workspace: Mapped["TaskWorkspaceRecord | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    executions: Mapped[list["ExecutionRecord"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    verification_attempts: Mapped[list["VerificationAttemptRecord"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskPlanRecord(Base):
    """A deterministic plan grounded in a particular repository index state."""

    __tablename__ = "task_plans"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    index_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    task: Mapped[EngineeringTask] = relationship(back_populates="plan")


class TaskWorkspaceRecord(Base):
    """An isolated Git worktree allocated to one planned task."""

    __tablename__ = "task_workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_tasks.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    base_commit: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[EngineeringTask] = relationship(back_populates="workspace")
    patches: Mapped[list["PatchRecord"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    executions: Mapped[list["ExecutionRecord"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    verification_attempts: Mapped[list["VerificationAttemptRecord"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class PatchRecord(Base):
    """Immutable audit metadata for one workspace file mutation."""

    __tablename__ = "patch_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("task_workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    before_hash: Mapped[str | None] = mapped_column(String(64))
    after_hash: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    workspace: Mapped[TaskWorkspaceRecord] = relationship(back_populates="patches")


class ExecutionRecord(Base):
    """Captured result of one policy-approved sandbox command."""

    __tablename__ = "execution_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("task_workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    argv_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(default=False, nullable=False)
    output_truncated: Mapped[bool] = mapped_column(default=False, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[EngineeringTask] = relationship(back_populates="executions")
    workspace: Mapped[TaskWorkspaceRecord] = relationship(back_populates="executions")
    verification_links: Mapped[list["VerificationExecutionRecord"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class VerificationAttemptRecord(Base):
    """One complete run of every verification command in a task plan."""

    __tablename__ = "verification_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_verification_task_attempt"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("engineering_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("task_workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    patch_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[EngineeringTask] = relationship(back_populates="verification_attempts")
    workspace: Mapped[TaskWorkspaceRecord] = relationship(back_populates="verification_attempts")
    execution_links: Mapped[list["VerificationExecutionRecord"]] = relationship(
        back_populates="verification", cascade="all, delete-orphan"
    )


class VerificationExecutionRecord(Base):
    """Ordered association between a verification attempt and command execution."""

    __tablename__ = "verification_execution_records"

    verification_id: Mapped[str] = mapped_column(
        ForeignKey("verification_attempts.id", ondelete="CASCADE"), primary_key=True
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("execution_records.id", ondelete="CASCADE"),
        primary_key=True,
        unique=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    verification: Mapped[VerificationAttemptRecord] = relationship(back_populates="execution_links")
    execution: Mapped[ExecutionRecord] = relationship(back_populates="verification_links")


class RepositoryProfileRecord(Base):
    """Persisted, deterministic repository profile."""

    __tablename__ = "repository_profiles"

    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    repository: Mapped[Repository] = relationship(back_populates="profile")


class IndexedFile(Base):
    """A safely read source file tracked by content hash."""

    __tablename__ = "indexed_files"
    __table_args__ = (UniqueConstraint("repository_id", "path", name="uq_indexed_file_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_error: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    repository: Mapped[Repository] = relationship(back_populates="indexed_files")
    symbols: Mapped[list["CodeSymbol"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
    imports: Mapped[list["ImportRecord"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class CodeSymbol(Base):
    """A class or function extracted from a source file."""

    __tablename__ = "code_symbols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("indexed_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    qualified_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    docstring: Mapped[str | None] = mapped_column(Text)
    file: Mapped[IndexedFile] = relationship(back_populates="symbols")


class ImportRecord(Base):
    """A Python import used for module dependency queries."""

    __tablename__ = "import_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("indexed_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    imported_name: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line: Mapped[int] = mapped_column(Integer, nullable=False)
    file: Mapped[IndexedFile] = relationship(back_populates="imports")
