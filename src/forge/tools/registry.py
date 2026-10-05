"""Explicit registry of tools available to future agents."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolContext:
    """Context passed to an approved tool invocation."""

    trace_id: str
    task_id: str


class Tool(Protocol):
    """Structured tool contract; implementations must enforce their own policy."""

    name: str

    async def execute(self, context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]: ...


class ToolRegistry:
    """Reject unknown and duplicate tool names."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a named tool exactly once."""
        if not tool.name or tool.name in self._tools:
            raise ValueError(f"Invalid or duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Return an explicitly registered tool."""
        return self._tools[name]

    def names(self) -> tuple[str, ...]:
        """List registered names for a capability declaration."""
        return tuple(sorted(self._tools))
