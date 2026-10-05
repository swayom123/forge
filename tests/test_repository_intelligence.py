"""Repository profiling, indexing, search, and traversal security tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from forge.core.database import Base
from forge.core.models import CodeSymbol, IndexedFile, Repository
from forge.repository.files import ScanLimitError, ScanPolicy, iter_safe_files
from forge.repository.indexer import SqlRepositoryIndexer
from forge.repository.profiler import RepositoryProfiler
from forge.repository.search import RepositorySearch


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Create a small representative FastAPI repository."""
    root = tmp_path / "demo"
    (root / ".git").mkdir(parents=True)
    (root / "src" / "demo").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi", "pytest"]
[tool.ruff]
[tool.mypy]
""".strip()
    )
    (root / "src" / "demo" / "users.py").write_text(
        '''"""User services."""
from demo.database import connect

class UserService:
    """Manage users."""

    async def find(self, user_id: int) -> str:
        return str(user_id)

def duplicate() -> str:
    return "users"
'''
    )
    (root / "tests" / "test_users.py").write_text(
        "from demo.users import UserService\n\ndef duplicate() -> None:\n    assert UserService\n"
    )
    (root / ".github" / "workflows" / "test.yml").write_text("name: test")
    return root


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an isolated repository index database."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def register(session: Session, root: Path) -> Repository:
    record = Repository(path=str(root), name=root.name)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def test_profile_detects_python_fastapi_tooling_and_layout(repository: Path) -> None:
    profile = RepositoryProfiler().profile(repository)

    assert profile.languages == ("Python",)
    assert profile.frameworks == ("FastAPI",)
    assert profile.package_managers == ("pip",)
    assert profile.test_frameworks == ("pytest",)
    assert profile.lint_tools == ("Ruff",)
    assert profile.type_checkers == ("mypy",)
    assert profile.source_directories == ("src",)
    assert profile.test_directories == ("tests",)
    assert profile.ci_configuration == (".github/workflows/test.yml",)
    assert profile.test_commands == ("python -m pytest",)


def test_index_is_incremental_and_searches_symbols_dependencies_and_text(
    repository: Path, session: Session
) -> None:
    record = register(session, repository)
    indexer = SqlRepositoryIndexer(session)

    first = indexer.update(record.id, repository)
    assert first.indexed_files == 2
    assert first.unchanged_files == 0
    assert first.parse_errors == 0

    search = RepositorySearch(session)
    duplicates = search.symbols(record.id, "duplicate")
    assert [(item.file_path, item.name) for item in duplicates] == [
        ("src/demo/users.py", "duplicate"),
        ("tests/test_users.py", "duplicate"),
    ]
    assert search.dependents(record.id, "demo.users") == ("tests/test_users.py",)
    assert search.imports(record.id, "connect")[0].file_path == "src/demo/users.py"
    assert search.text(record.id, repository, "Manage users")[0].line == 5

    second = indexer.update(record.id, repository)
    assert second.indexed_files == 0
    assert second.unchanged_files == 2

    (repository / "src" / "demo" / "users.py").write_text("def replacement() -> None:\n    pass\n")
    (repository / "tests" / "test_users.py").unlink()
    third = indexer.update(record.id, repository)
    assert third.indexed_files == 1
    assert third.deleted_files == 1
    assert search.symbols(record.id, "duplicate") == ()
    assert search.symbols(record.id, "replacement")[0].file_path == "src/demo/users.py"


def test_syntax_errors_are_recorded_without_aborting_index(
    repository: Path, session: Session
) -> None:
    broken = repository / "src" / "demo" / "broken.py"
    broken.write_text("def invalid(:\n")
    record = register(session, repository)

    result = SqlRepositoryIndexer(session).update(record.id, repository)

    assert result.parse_errors == 1
    indexed = session.scalar(select(IndexedFile).where(IndexedFile.path == "src/demo/broken.py"))
    assert indexed is not None
    assert indexed.parse_error is not None
    assert session.scalars(select(CodeSymbol).where(CodeSymbol.file_id == indexed.id)).all() == []


def test_traversal_skips_ignored_binary_large_and_symlinked_files(
    repository: Path, tmp_path: Path
) -> None:
    (repository / ".venv").mkdir()
    (repository / ".venv" / "hidden.py").write_text("def hidden(): pass")
    (repository / "binary.py").write_bytes(b"def visible():\x00pass")
    (repository / "large.py").write_text("x" * 101)
    outside = tmp_path / "outside.py"
    outside.write_text("def stolen(): pass")
    (repository / "escape.py").symlink_to(outside)

    files = iter_safe_files(repository, ScanPolicy(max_file_bytes=100))
    paths = {item.relative_path.as_posix() for item in files}

    assert ".venv/hidden.py" not in paths
    assert "binary.py" not in paths
    assert "large.py" not in paths
    assert "escape.py" not in paths
    assert "src/demo/users.py" not in paths  # fixture source exceeds this deliberate limit


def test_traversal_enforces_file_count_limit(repository: Path) -> None:
    with pytest.raises(ScanLimitError, match="exceeds 1 files"):
        iter_safe_files(repository, ScanPolicy(max_files=1))
