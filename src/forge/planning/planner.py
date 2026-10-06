"""Deterministic task plans built only from persisted repository intelligence."""

import hashlib
import json
import re
import shlex
from dataclasses import asdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from forge.core.contracts import AffectedFile, IssueUnderstanding, Plan, RepositoryProfile
from forge.core.models import CodeSymbol, ImportRecord, IndexedFile, RepositoryProfileRecord

MAX_AFFECTED_FILES = 8
MAX_CONTEXT_MATCHES = 100
MAX_KEYWORDS = 12

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_PATH = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "add",
        "and",
        "bug",
        "change",
        "create",
        "debug",
        "ensure",
        "feature",
        "fix",
        "for",
        "from",
        "implement",
        "into",
        "issue",
        "make",
        "must",
        "only",
        "please",
        "should",
        "task",
        "test",
        "that",
        "the",
        "this",
        "update",
        "when",
        "with",
        "without",
    }
)
_CONSTRAINT_PREFIXES = (
    "must ",
    "must not ",
    "should ",
    "do not ",
    "don't ",
    "only ",
    "without ",
    "preserve ",
    "ensure ",
)


def current_index_fingerprint(session: Session, repository_id: str) -> str:
    """Hash the stored profile plus indexed paths and hashes for staleness checks."""
    profile = session.get(RepositoryProfileRecord, repository_id)
    rows = session.execute(
        select(IndexedFile.path, IndexedFile.content_hash)
        .where(IndexedFile.repository_id == repository_id)
        .order_by(IndexedFile.path)
    )
    digest = hashlib.sha256()
    if profile is not None:
        digest.update(profile.profile_json.encode())
        digest.update(b"\n")
    for path, content_hash in rows:
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(content_hash.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def plan_to_json(plan: Plan) -> str:
    """Serialize a plan in a stable representation suitable for persistence."""
    return json.dumps(asdict(plan), sort_keys=True)


def plan_from_json(value: str) -> Plan:
    """Deserialize a plan produced by :func:`plan_to_json`."""
    data = json.loads(value)
    issue_data = data.get("issue")
    issue = None
    if issue_data is not None:
        issue = IssueUnderstanding(
            summary=issue_data["summary"],
            task_type=issue_data["task_type"],
            keywords=tuple(issue_data["keywords"]),
            explicit_paths=tuple(issue_data.get("explicit_paths", ())),
            constraints=tuple(issue_data.get("constraints", ())),
        )
    affected = tuple(
        AffectedFile(
            path=item["path"],
            confidence=item["confidence"],
            reason=item["reason"],
            evidence=tuple(item["evidence"]),
        )
        for item in data.get("affected_files", ())
    )
    return Plan(
        steps=tuple(data["steps"]),
        acceptance_criteria=tuple(data["acceptance_criteria"]),
        validation_commands=tuple(tuple(command) for command in data["validation_commands"]),
        issue=issue,
        affected_files=affected,
        context_fingerprint=data.get("context_fingerprint", ""),
    )


def _summary(objective: str) -> str:
    lines = [line.strip(" \t-*#") for line in objective.splitlines() if line.strip()]
    return lines[0][:500] if lines else objective.strip()[:500]


def _keywords(objective: str) -> tuple[str, ...]:
    result: list[str] = []
    for match in _WORD.finditer(objective):
        token = match.group().lower().replace("-", "_")
        for part in token.split("_"):
            if len(part) >= 3 and part not in _STOP_WORDS and part not in result:
                result.append(part)
                if len(result) == MAX_KEYWORDS:
                    return tuple(result)
    return tuple(result)


def _constraints(objective: str) -> tuple[str, ...]:
    clauses = re.split(r"(?:\n+|(?<=[.!?])\s+)", objective)
    return tuple(
        clause.strip(" \t-*#")[:500]
        for clause in clauses
        if clause.strip(" \t-*#").casefold().startswith(_CONSTRAINT_PREFIXES)
    )


def _related(term: str, candidate: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", candidate.casefold())
    if len(term) < 3 or len(normalized) < 3:
        return False
    if term in normalized or normalized in term:
        return True
    common = 0
    for left, right in zip(term, normalized, strict=False):
        if left != right:
            break
        common += 1
    return common >= 5


def _module_for_path(path: str) -> str:
    parts = path.removesuffix(".py").split("/")
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _validation_commands(profile: RepositoryProfile) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = []
    if "Ruff" in profile.lint_tools:
        commands.append(("python", "-m", "ruff", "check", "."))
    if "mypy" in profile.type_checkers:
        targets = profile.source_directories or (".",)
        commands.append(("python", "-m", "mypy", *targets))
    for configured in (*profile.test_commands, *profile.build_commands):
        try:
            command = tuple(shlex.split(configured))
        except ValueError:
            continue
        if command and command not in commands:
            commands.append(command)
    return tuple(commands)


class IndexGroundedTaskPlanner:
    """Create explainable plans without reading files or invoking a model."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def plan(
        self,
        repository_id: str,
        objective: str,
        task_type: str,
        profile: RepositoryProfile,
    ) -> Plan:
        """Create a plan from the objective, stored profile, and persisted AST index."""
        files = tuple(
            self.session.scalars(
                select(IndexedFile)
                .where(IndexedFile.repository_id == repository_id)
                .order_by(IndexedFile.path)
            )
        )
        paths = {item.path for item in files}
        mentioned_paths = {match.group().rstrip(".,:;!?)]}") for match in _PATH.finditer(objective)}
        explicit_paths = tuple(sorted(mentioned_paths & paths))
        keywords = _keywords(_PATH.sub(" ", objective))
        issue = IssueUnderstanding(
            summary=_summary(objective),
            task_type=task_type,
            keywords=keywords,
            explicit_paths=explicit_paths,
            constraints=_constraints(objective),
        )
        affected = self._affected_files(repository_id, paths, explicit_paths, keywords)
        commands = _validation_commands(profile)
        steps = self._steps(task_type, issue, affected, commands)
        criteria = self._acceptance_criteria(issue, affected, commands)
        return Plan(
            steps=steps,
            acceptance_criteria=criteria,
            validation_commands=commands,
            issue=issue,
            affected_files=affected,
            context_fingerprint=current_index_fingerprint(self.session, repository_id),
        )

    def _affected_files(
        self,
        repository_id: str,
        paths: set[str],
        explicit_paths: tuple[str, ...],
        keywords: tuple[str, ...],
    ) -> tuple[AffectedFile, ...]:
        scores = dict.fromkeys(paths, 0)
        evidence: dict[str, set[str]] = {path: set() for path in paths}
        for path in explicit_paths:
            scores[path] += 100
            evidence[path].add("explicitly named in the objective")
        for path in paths:
            for keyword in keywords:
                if _related(keyword, path):
                    scores[path] += 3
                    evidence[path].add(f'path matches keyword "{keyword}"')

        for keyword in keywords:
            pattern = f"%{keyword[:5]}%"
            symbol_rows = self.session.execute(
                select(CodeSymbol, IndexedFile.path)
                .join(IndexedFile)
                .where(
                    IndexedFile.repository_id == repository_id,
                    or_(
                        CodeSymbol.name.ilike(pattern),
                        CodeSymbol.qualified_name.ilike(pattern),
                    ),
                )
                .order_by(IndexedFile.path, CodeSymbol.line_start)
                .limit(MAX_CONTEXT_MATCHES)
            )
            for symbol, path in symbol_rows:
                if _related(keyword, symbol.name) or _related(keyword, symbol.qualified_name):
                    scores[path] += 8
                    evidence[path].add(
                        f'indexed {symbol.kind} "{symbol.qualified_name}" '
                        f"at line {symbol.line_start}"
                    )

            import_rows = self.session.execute(
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
                .limit(MAX_CONTEXT_MATCHES)
            )
            for item, path in import_rows:
                target = ".".join(filter(None, (item.module, item.imported_name)))
                if _related(keyword, target):
                    scores[path] += 4
                    evidence[path].add(f'imports "{target}" at line {item.line}')

        primary = [
            path
            for _, path in sorted(
                ((score, path) for path, score in scores.items() if score >= 6),
                key=lambda item: (-item[0], item[1]),
            )[:20]
        ]
        for source_path in primary:
            module = _module_for_path(source_path)
            if not module:
                continue
            dependent_rows = self.session.execute(
                select(ImportRecord, IndexedFile.path)
                .join(IndexedFile)
                .where(
                    IndexedFile.repository_id == repository_id,
                    or_(
                        ImportRecord.module == module,
                        ImportRecord.module.like(f"{module}.%"),
                    ),
                )
                .order_by(IndexedFile.path, ImportRecord.line)
                .limit(MAX_CONTEXT_MATCHES)
            )
            for item, dependent_path in dependent_rows:
                if dependent_path == source_path:
                    continue
                if item.module == module or item.module.startswith(module + "."):
                    scores[dependent_path] += 5
                    evidence[dependent_path].add(f'depends on estimated module "{module}"')

        ranked = sorted(
            ((score, path) for path, score in scores.items() if score >= 3),
            key=lambda item: (-item[0], item[1]),
        )[:MAX_AFFECTED_FILES]
        result: list[AffectedFile] = []
        for score, path in ranked:
            items = tuple(sorted(evidence[path]))
            confidence = "high" if score >= 12 else "medium" if score >= 6 else "low"
            result.append(
                AffectedFile(
                    path=path,
                    confidence=confidence,
                    reason=items[0],
                    evidence=items,
                )
            )
        return tuple(result)

    @staticmethod
    def _steps(
        task_type: str,
        issue: IssueUnderstanding,
        affected: tuple[AffectedFile, ...],
        commands: tuple[tuple[str, ...], ...],
    ) -> tuple[str, ...]:
        file_scope = ", ".join(item.path for item in affected) or "no confidently matched files"
        steps = [
            f"Review the structured objective and confirm the indexed scope ({file_scope}).",
        ]
        if task_type in {"ANALYZE", "SEARCH", "REVIEW", "PLAN"}:
            steps.append(f"Investigate the indexed evidence for: {issue.summary}")
            steps.append(
                "Document findings, uncertainties, and any follow-up work without editing files."
            )
        elif task_type == "VERIFY":
            steps.append(f"Assess the indexed implementation against: {issue.summary}")
        else:
            steps.append(f"Implement the requested outcome in the confirmed scope: {issue.summary}")
            steps.append(
                "Add or update focused tests for the changed behavior and relevant edge cases."
            )
        if commands:
            steps.append("Run every configured verification command and resolve any failures.")
        else:
            steps.append(
                "Record that the repository profile exposes no automated verification commands."
            )
        return tuple(steps)

    @staticmethod
    def _acceptance_criteria(
        issue: IssueUnderstanding,
        affected: tuple[AffectedFile, ...],
        commands: tuple[tuple[str, ...], ...],
    ) -> tuple[str, ...]:
        criteria = [f"Requested outcome is satisfied: {issue.summary}"]
        criteria.extend(issue.constraints)
        if affected and issue.task_type not in {"ANALYZE", "SEARCH", "REVIEW", "PLAN", "VERIFY"}:
            criteria.append(
                "Every modified file is within the estimated scope or has an explicit "
                "documented justification."
            )
        if commands:
            criteria.append("Every configured verification command exits successfully.")
        else:
            criteria.append(
                "Manual verification evidence is recorded because no commands were detected."
            )
        return tuple(dict.fromkeys(criteria))
