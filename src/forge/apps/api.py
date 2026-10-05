"""Forge FastAPI service."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from forge.apps.schemas import (
    CreateTaskRequest,
    ImportResponse,
    IndexUpdateResponse,
    RegisterRepositoryRequest,
    RepositoryProfileResponse,
    RepositoryResponse,
    SymbolResponse,
    TaskResponse,
    TextMatchResponse,
)
from forge.config import get_settings
from forge.core.contracts import RepositoryProfile
from forge.core.database import get_session, init_db
from forge.core.models import EngineeringTask, Repository, RepositoryProfileRecord
from forge.logging import configure_logging
from forge.repository.files import configured_scan_policy
from forge.repository.indexer import SqlRepositoryIndexer, profile_from_json
from forge.repository.scanner import LocalRepositoryScanner
from forge.repository.search import ImportMatch, RepositorySearch, SymbolMatch, TextMatch

logger = logging.getLogger("forge.api")
SessionDependency = Annotated[Session, Depends(get_session)]


def profile_response(profile: RepositoryProfile) -> RepositoryProfileResponse:
    """Convert the internal Path-bearing profile into its HTTP representation."""
    data = dict(vars(profile))
    data["root"] = str(data["root"])
    return RepositoryProfileResponse(**data)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize storage before serving requests."""
    configure_logging(get_settings().log_level)
    init_db()
    yield


app = FastAPI(title="Forge", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Return service liveness."""
    return {"status": "ok"}


@app.post(
    "/repositories/register", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED
)
def register_repository(body: RegisterRepositoryRequest, session: SessionDependency) -> Repository:
    """Record the identity of a local Git repository."""
    try:
        profile = LocalRepositoryScanner().scan(Path(body.path))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    existing = session.scalar(select(Repository).where(Repository.path == str(profile.root)))
    if existing is not None:
        return existing
    repository = Repository(path=str(profile.root), name=profile.name)
    session.add(repository)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Repository was registered concurrently"
        ) from None
    session.refresh(repository)
    logger.info("repository registered", extra={"repository_id": repository.id})
    return repository


@app.get("/repositories/{repository_id}", response_model=RepositoryResponse)
def get_repository(repository_id: str, session: SessionDependency) -> Repository:
    """Fetch a registered repository."""
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repository


@app.post("/repositories/{repository_id}/index", response_model=IndexUpdateResponse)
def index_repository(repository_id: str, session: SessionDependency) -> IndexUpdateResponse:
    """Profile and incrementally index a registered repository."""
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        result = SqlRepositoryIndexer(session, configured_scan_policy()).update(
            repository.id, Path(repository.path)
        )
    except (OSError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = session.get(RepositoryProfileRecord, repository_id)
    if record is None:  # pragma: no cover - guarded by the transactional indexer
        raise HTTPException(status_code=500, detail="Profile was not persisted")
    profile = profile_from_json(record.profile_json)
    logger.info("repository indexed", extra={"repository_id": repository.id})
    return IndexUpdateResponse(**result.__dict__, profile=profile_response(profile))


@app.get("/repositories/{repository_id}/profile", response_model=RepositoryProfileResponse)
def get_repository_profile(
    repository_id: str, session: SessionDependency
) -> RepositoryProfileResponse:
    """Return the latest persisted repository profile."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    record = session.get(RepositoryProfileRecord, repository_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Repository has not been indexed")
    return profile_response(profile_from_json(record.profile_json))


@app.get("/repositories/{repository_id}/symbols", response_model=list[SymbolResponse])
def search_symbols(
    repository_id: str,
    session: SessionDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> tuple[SymbolMatch, ...]:
    """Search indexed definitions by symbol name."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).symbols(repository_id, query, limit)


@app.get("/repositories/{repository_id}/search", response_model=list[TextMatchResponse])
def search_source(
    repository_id: str,
    session: SessionDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> tuple[TextMatch, ...]:
    """Search lines from files admitted to the current source index."""
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).text(repository_id, Path(repository.path), query, limit)


@app.get("/repositories/{repository_id}/dependents", response_model=list[str])
def find_dependents(
    repository_id: str,
    session: SessionDependency,
    module: Annotated[str, Query(min_length=1, max_length=500)],
) -> tuple[str, ...]:
    """Return indexed files importing the requested module."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).dependents(repository_id, module)


@app.get("/repositories/{repository_id}/imports", response_model=list[ImportResponse])
def search_imports(
    repository_id: str,
    session: SessionDependency,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> tuple[ImportMatch, ...]:
    """Search indexed imports by module or imported name."""
    if session.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositorySearch(session).imports(repository_id, query, limit)


@app.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(body: CreateTaskRequest, session: SessionDependency) -> EngineeringTask:
    """Persist a pending task. No model or shell execution occurs."""
    if session.get(Repository, body.repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    task = EngineeringTask(
        repository_id=body.repository_id,
        objective=body.objective,
        task_type=body.task_type.value,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info("task created", extra={"task_id": task.id, "trace_id": task.trace_id})
    return task


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, session: SessionDependency) -> EngineeringTask:
    """Fetch a persisted task."""
    task = session.get(EngineeringTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
