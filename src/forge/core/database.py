"""SQLAlchemy database ownership and session dependency."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from forge.config import get_settings


class Base(DeclarativeBase):
    """Base class for persisted records."""


def make_engine(url: str) -> Engine:
    """Create a database engine with SQLite threading configured for the API."""
    options = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=options)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(db_engine: Engine = engine) -> None:
    """Create current tables. Schema migrations are a later requirement."""
    from forge.core import models  # noqa: F401

    Base.metadata.create_all(db_engine)


def get_session() -> Iterator[Session]:
    """Yield a request-scoped session."""
    with SessionLocal() as session:
        yield session
