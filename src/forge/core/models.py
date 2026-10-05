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
    """A queued engineering request; no work is executed by Phase 1."""

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
