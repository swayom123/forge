"""Base contract for future specialized agents."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    """Agent identity and execution restrictions."""

    id: str
    name: str
    capabilities: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    model_name: str | None
    timeout_seconds: int
    max_retries: int


@dataclass(frozen=True)
class AgentContext:
    """Inputs shared with a single agent run."""

    trace_id: str
    task_id: str
    inputs: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    """Structured output of an agent run."""

    trace_id: str
    outputs: dict[str, Any]


class BaseAgent(ABC):
    """Contract for an agent that receives scoped context and returns data."""

    config: AgentConfig

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """Perform one bounded agent operation."""
