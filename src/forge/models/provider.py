"""Vendor-neutral model provider contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ModelMessage:
    """One model conversation message."""

    role: str
    content: str


@dataclass(frozen=True)
class ModelResponse:
    """Text response and optional token accounting."""

    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelProvider(Protocol):
    """Complete a scoped prompt; callers must redact secrets first."""

    async def complete(self, messages: tuple[ModelMessage, ...], model: str) -> ModelResponse: ...
