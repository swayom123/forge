"""Persisted state types for Phase 1."""

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle status of an engineering task."""

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
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
