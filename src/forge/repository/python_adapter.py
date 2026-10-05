"""Python AST extraction behind a language-specific adapter."""

import ast
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtractedSymbol:
    """A Python class or function definition."""

    name: str
    qualified_name: str
    kind: str
    line_start: int
    line_end: int
    signature: str
    docstring: str | None


@dataclass(frozen=True)
class ExtractedImport:
    """A Python import statement target."""

    module: str
    imported_name: str | None
    level: int
    line: int


@dataclass(frozen=True)
class PythonExtraction:
    """Definitions and dependencies extracted from one module."""

    symbols: tuple[ExtractedSymbol, ...]
    imports: tuple[ExtractedImport, ...]


class LanguageAdapter(Protocol):
    """Parse one language into common symbol and import records."""

    language: str
    extensions: frozenset[str]

    def extract(self, source: str, filename: str) -> PythonExtraction: ...


class PythonLanguageAdapter:
    """Standard-library Python language adapter."""

    language = "Python"
    extensions = frozenset({".py"})

    def extract(self, source: str, filename: str) -> PythonExtraction:
        """Parse Python source without importing it."""
        return extract_python(source, filename)


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.parents: list[str] = []
        self.symbols: list[ExtractedSymbol] = []
        self.imports: list[ExtractedImport] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: str) -> None:
        arguments = ast.unparse(node.args)
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        self.symbols.append(
            ExtractedSymbol(
                name=node.name,
                qualified_name=".".join((*self.parents, node.name)),
                kind=kind,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature=f"{node.name}({arguments}){returns}",
                docstring=ast.get_docstring(node, clean=False),
            )
        )
        self.parents.append(node.name)
        self.generic_visit(node)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, "async_function")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = ", ".join(ast.unparse(base) for base in node.bases)
        self.symbols.append(
            ExtractedSymbol(
                name=node.name,
                qualified_name=".".join((*self.parents, node.name)),
                kind="class",
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature=f"{node.name}({bases})",
                docstring=ast.get_docstring(node, clean=False),
            )
        )
        self.parents.append(node.name)
        self.generic_visit(node)
        self.parents.pop()

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.extend(
            ExtractedImport(alias.name, None, 0, node.lineno) for alias in node.names
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.extend(
            ExtractedImport(node.module or "", alias.name, node.level, node.lineno)
            for alias in node.names
        )


def extract_python(source: str, filename: str) -> PythonExtraction:
    """Parse Python source without importing or executing it."""
    tree = ast.parse(source, filename=filename)
    visitor = _Visitor()
    visitor.visit(tree)
    return PythonExtraction(tuple(visitor.symbols), tuple(visitor.imports))
