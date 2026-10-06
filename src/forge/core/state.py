"""Persisted state types for Phase 1."""

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle status of an engineering task."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskType(StrEnum):
    """Supported planning categories, not execution capabilities."""

    ANALYZE = "ANALYZE"
    PLAN = "PLAN"
    SEARCH = "SEARCH"
    IMPLEMENT = "IMPLEMENT"
    TEST = "TEST"
    DEBUG = "DEBUG"
    REVIEW = "REVIEW"
    DOCUMENT = "DOCUMENT"
    VERIFY = "VERIFY"


class WorkspaceStatus(StrEnum):
    """Lifecycle status of an isolated task workspace."""

    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class PatchOperation(StrEnum):
    """Supported audited file mutations."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class ExecutionStatus(StrEnum):
    """Lifecycle status of a persisted sandbox execution."""

    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    TIMED_OUT = "TIMED_OUT"
    ERROR = "ERROR"


class VerificationStatus(StrEnum):
    """Outcome of one complete planned verification gate run."""

    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
