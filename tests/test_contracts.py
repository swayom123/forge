"""Small behavior tests for Phase 1 interfaces."""

from pathlib import Path

import pytest

from forge.repository.scanner import LocalRepositoryScanner
from forge.tools.registry import ToolRegistry


def test_scanner_accepts_git_worktree_marker(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /tmp/example")
    profile = LocalRepositoryScanner().scan(tmp_path)
    assert profile.root == tmp_path
    assert profile.is_git_repository


def test_registry_rejects_duplicate_name() -> None:
    class ExampleTool:
        name = "example"

        async def execute(self, context: object, arguments: dict[str, object]) -> dict[str, object]:
            return arguments

    registry = ToolRegistry()
    tool = ExampleTool()
    registry.register(tool)
    assert registry.names() == ("example",)
    with pytest.raises(ValueError):
        registry.register(tool)
