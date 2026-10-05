"""Queries over the persisted repository index."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from forge.core.models import CodeSymbol, ImportRecord, IndexedFile
from forge.repository.files import SafeFile


@dataclass(frozen=True)
class SymbolMatch:
    """A symbol definition with its source location."""

    name: str
    qualified_name: str
    kind: str
    file_path: str
    line_start: int
    line_end: int
    signature: str


@dataclass(frozen=True)
class TextMatch:
    """One matching source line."""

    file_path: str
    line: int
    text: str


@dataclass(frozen=True)
class ImportMatch:
    """One imported module or name and its source location."""

    file_path: str
    module: str
    imported_name: str | None
    level: int
    line: int


class RepositorySearch:
    """Search symbols, dependencies, and the bounded indexed source set."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def symbols(self, repository_id: str, query: str, limit: int = 50) -> tuple[SymbolMatch, ...]:
        """Find definitions by case-insensitive name or qualified name."""
        pattern = f"%{query}%"
        rows = self.session.execute(
            select(CodeSymbol, IndexedFile.path)
            .join(IndexedFile)
            .where(
                IndexedFile.repository_id == repository_id,
                or_(CodeSymbol.name.ilike(pattern), CodeSymbol.qualified_name.ilike(pattern)),
            )
            .order_by(IndexedFile.path, CodeSymbol.line_start)
            .limit(limit)
        )
        return tuple(
            SymbolMatch(
                symbol.name,
                symbol.qualified_name,
                symbol.kind,
                path,
                symbol.line_start,
                symbol.line_end,
                symbol.signature,
            )
            for symbol, path in rows
        )

    def dependents(self, repository_id: str, module: str) -> tuple[str, ...]:
        """Return indexed files importing a module or one of its children."""
        rows = self.session.scalars(
            select(IndexedFile.path)
            .join(ImportRecord)
            .where(
                IndexedFile.repository_id == repository_id,
                or_(ImportRecord.module == module, ImportRecord.module.like(f"{module}.%")),
            )
            .distinct()
            .order_by(IndexedFile.path)
        )
        return tuple(rows)

    def imports(self, repository_id: str, query: str, limit: int = 50) -> tuple[ImportMatch, ...]:
        """Find indexed imports by module or imported name."""
        pattern = f"%{query}%"
        rows = self.session.execute(
            select(ImportRecord, IndexedFile.path)
            .join(IndexedFile)
            .where(
                IndexedFile.repository_id == repository_id,
                or_(
                    ImportRecord.module.ilike(pattern),
                    ImportRecord.imported_name.ilike(pattern),
                ),
            )
            .order_by(IndexedFile.path, ImportRecord.line)
            .limit(limit)
        )
        return tuple(
            ImportMatch(path, item.module, item.imported_name, item.level, item.line)
            for item, path in rows
        )

    def text(
        self, repository_id: str, root: Path, query: str, limit: int = 50
    ) -> tuple[TextMatch, ...]:
        """Search source lines from paths already admitted to the bounded index."""
        results: list[TextMatch] = []
        files = self.session.execute(
            select(IndexedFile.path, IndexedFile.size_bytes)
            .where(IndexedFile.repository_id == repository_id)
            .order_by(IndexedFile.path)
        )
        resolved_root = root.resolve(strict=True)
        needle = query.casefold()
        for relative, indexed_size in files:
            candidate = resolved_root / relative
            if candidate.is_symlink():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(resolved_root)
                content = SafeFile(Path(relative), resolved, indexed_size).read_bytes()
                lines = content.decode("utf-8").splitlines()
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            for number, line in enumerate(lines, 1):
                if needle in line.casefold():
                    results.append(TextMatch(relative, number, line[:500]))
                    if len(results) >= limit:
                        return tuple(results)
        return tuple(results)
