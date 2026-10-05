"""Local Forge command line interface."""

import json
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from forge.core.database import SessionLocal, init_db
from forge.core.models import EngineeringTask, Repository
from forge.core.state import TaskType
from forge.repository.files import configured_scan_policy
from forge.repository.indexer import SqlRepositoryIndexer
from forge.repository.profiler import RepositoryProfiler
from forge.repository.scanner import LocalRepositoryScanner
from forge.repository.search import RepositorySearch

app = typer.Typer(help="Forge repository intelligence and task CLI.")


@app.command()
def inspect(path: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Profile a local Git repository without running its code."""
    try:
        profile = RepositoryProfiler(configured_scan_policy()).profile(path)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            {
                **profile.__dict__,
                "root": str(profile.root),
            },
            indent=2,
        )
    )


@app.command()
def register(path: Annotated[Path, typer.Argument()] = Path(".")) -> None:
    """Register a local Git repository."""
    try:
        profile = LocalRepositoryScanner().scan(path)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    init_db()
    with SessionLocal() as session:
        repository = session.scalar(select(Repository).where(Repository.path == str(profile.root)))
        if repository is None:
            repository = Repository(path=str(profile.root), name=profile.name)
            session.add(repository)
            session.commit()
            session.refresh(repository)
        typer.echo(f"Repository ID: {repository.id}")


@app.command()
def task(repository_id: str, objective: str, task_type: TaskType = TaskType.IMPLEMENT) -> None:
    """Record a pending engineering task."""
    init_db()
    with SessionLocal() as session:
        if session.get(Repository, repository_id) is None:
            raise typer.BadParameter("Repository ID does not exist")
        record = EngineeringTask(
            repository_id=repository_id,
            objective=objective,
            task_type=task_type.value,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        typer.echo(f"Task ID: {record.id}\nStatus: {record.status}\nTrace ID: {record.trace_id}")


@app.command()
def status(task_id: str) -> None:
    """Show the persisted state of a task."""
    init_db()
    with SessionLocal() as session:
        record = session.get(EngineeringTask, task_id)
        if record is None:
            raise typer.BadParameter("Task ID does not exist")
        typer.echo(f"Task: {record.id}\nStatus: {record.status}\nObjective: {record.objective}")


@app.command("index")
def index_repository(repository_id: str) -> None:
    """Profile and incrementally index a registered repository."""
    init_db()
    with SessionLocal() as session:
        repository = session.get(Repository, repository_id)
        if repository is None:
            raise typer.BadParameter("Repository ID does not exist")
        try:
            result = SqlRepositoryIndexer(session, configured_scan_policy()).update(
                repository.id, Path(repository.path)
            )
        except (OSError, ValueError) as exc:
            session.rollback()
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(json.dumps(result.__dict__, indent=2))


@app.command()
def search(repository_id: str, query: str, limit: int = 50) -> None:
    """Search indexed symbol definitions."""
    if limit < 1 or limit > 200:
        raise typer.BadParameter("Limit must be between 1 and 200")
    init_db()
    with SessionLocal() as session:
        if session.get(Repository, repository_id) is None:
            raise typer.BadParameter("Repository ID does not exist")
        matches = RepositorySearch(session).symbols(repository_id, query, limit)
        typer.echo(json.dumps([match.__dict__ for match in matches], indent=2))


if __name__ == "__main__":
    app()
