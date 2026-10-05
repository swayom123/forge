"""Deterministic repository technology and layout profiling."""

import tomllib
from pathlib import Path
from typing import Any

from forge.core.contracts import RepositoryProfile
from forge.repository.files import DEFAULT_SCAN_POLICY, SafeFile, ScanPolicy, iter_safe_files

LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".cs": "C#",
}


def _text(files: dict[str, SafeFile], name: str) -> str:
    file = files.get(name)
    if file is None:
        return ""
    return file.read_bytes().decode("utf-8", errors="replace")


def _pyproject(files: dict[str, SafeFile]) -> dict[str, Any]:
    file = files.get("pyproject.toml")
    if file is None:
        return {}
    try:
        value = tomllib.loads(file.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class RepositoryProfiler:
    """Infer common repository metadata without importing or executing code."""

    def __init__(self, policy: ScanPolicy = DEFAULT_SCAN_POLICY) -> None:
        self.policy = policy

    def profile(self, root: Path) -> RepositoryProfile:
        """Build a stable profile from filenames and configuration text."""
        resolved = root.expanduser().resolve(strict=True)
        marker = resolved / ".git"
        if not resolved.is_dir() or (not marker.is_dir() and not marker.is_file()):
            raise ValueError("Path is not a Git repository root")
        safe_files = iter_safe_files(resolved, self.policy)
        files = {item.relative_path.as_posix(): item for item in safe_files}
        paths = set(files)
        extensions = (Path(path).suffix.lower() for path in files)
        languages = sorted(
            {
                LANGUAGE_EXTENSIONS[extension]
                for extension in extensions
                if extension in LANGUAGE_EXTENSIONS
            }
        )
        pyproject = _pyproject(files)
        configuration = "\n".join(
            (
                _text(files, "pyproject.toml"),
                _text(files, "requirements.txt"),
                _text(files, "setup.cfg"),
            )
        ).lower()

        frameworks = tuple(
            name
            for token, name in (("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask"))
            if token in configuration
        )
        managers: list[str] = []
        if "pyproject.toml" in paths:
            managers.append("pip")
            tool = pyproject.get("tool", {})
            if isinstance(tool, dict):
                for key, name in (("poetry", "Poetry"), ("pdm", "PDM"), ("uv", "uv")):
                    if key in tool:
                        managers.append(name)
        if "requirements.txt" in paths and "pip" not in managers:
            managers.append("pip")
        if "package.json" in paths:
            managers.append("npm")
        if "go.mod" in paths:
            managers.append("Go modules")
        if "Cargo.toml" in paths:
            managers.append("Cargo")

        tests = (
            ("pytest",)
            if "pytest" in configuration or any(path.startswith("tests/") for path in paths)
            else ()
        )
        linters = tuple(
            name
            for token, name in (("ruff", "Ruff"), ("eslint", "ESLint"))
            if token in configuration or token + ".config.js" in paths
        )
        type_checkers = tuple(
            name
            for token, name in (("mypy", "mypy"), ("pyright", "Pyright"))
            if token in configuration or f"{token}.ini" in paths or f"{token}config.json" in paths
        )
        source_dirs = tuple(
            name
            for name in ("src", "app", "lib")
            if any(path.startswith(name + "/") for path in paths)
        )
        test_dirs = tuple(
            name for name in ("tests", "test") if any(path.startswith(name + "/") for path in paths)
        )
        entry_points = tuple(
            name for name in ("main.py", "app.py", "src/main.py", "app/main.py") if name in paths
        )
        ci = tuple(
            path
            for path in sorted(paths)
            if path.startswith(".github/workflows/") or path in {".gitlab-ci.yml", "Jenkinsfile"}
        )
        test_commands = ("python -m pytest",) if "pytest" in tests else ()
        build_commands = ("python -m build",) if "pyproject.toml" in paths else ()
        summary_parts = [f"{len(safe_files)} readable files"]
        if languages:
            summary_parts.append("languages: " + ", ".join(languages))
        if frameworks:
            summary_parts.append("frameworks: " + ", ".join(frameworks))
        return RepositoryProfile(
            root=resolved,
            name=resolved.name,
            is_git_repository=True,
            languages=tuple(languages),
            frameworks=frameworks,
            package_managers=tuple(dict.fromkeys(managers)),
            test_frameworks=tests,
            lint_tools=linters,
            type_checkers=type_checkers,
            build_commands=build_commands,
            test_commands=test_commands,
            source_directories=source_dirs,
            test_directories=test_dirs,
            entry_points=entry_points,
            ci_configuration=ci,
            architecture_summary="; ".join(summary_parts),
        )
