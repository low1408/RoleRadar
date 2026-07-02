"""Database engine and schema initialization helpers."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from roleradar.config.settings import Settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


def create_database_engine(
    database_url: str,
    *,
    sqlite_wal: bool = True,
    sqlite_busy_timeout_ms: int = 5000,
) -> Engine:
    """Create a SQLAlchemy engine with SQLite pragmas where applicable."""
    from sqlalchemy import create_engine

    url = make_url(database_url)
    connect_args = {}
    if url.drivername.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        _ensure_sqlite_parent_directory(url.database)

    engine = create_engine(database_url, connect_args=connect_args, future=True)

    if url.drivername.startswith("sqlite"):
        _configure_sqlite(
            engine,
            enable_wal=sqlite_wal and _is_file_sqlite_url(url.database),
            busy_timeout_ms=sqlite_busy_timeout_ms,
        )

    return engine


def create_session_factory(engine: Engine) -> sessionmaker:
    """Create a configured SQLAlchemy session factory."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def init_database(
    settings: Settings | None = None,
    engine: Engine | None = None,
) -> None:
    """Create all configured database tables."""
    from roleradar.storage import models  # noqa: F401

    if engine is None:
        settings = settings or Settings()
        engine = create_database_engine(
            settings.database_url,
            sqlite_wal=settings.sqlite_wal,
            sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        )

    Base.metadata.create_all(engine)
    _ensure_sqlite_skill_metadata_columns(engine)


def _ensure_sqlite_skill_metadata_columns(engine: Engine) -> None:
    """Add Phase 8 skill metadata columns to existing local SQLite databases."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "skills" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("skills")}
    statements = []
    if "taxonomy_version" not in existing_columns:
        statements.append("ALTER TABLE skills ADD COLUMN taxonomy_version VARCHAR(255)")
    if "source_updated_at" not in existing_columns:
        statements.append("ALTER TABLE skills ADD COLUMN source_updated_at DATETIME")
    if "updated_at" not in existing_columns:
        statements.append("ALTER TABLE skills ADD COLUMN updated_at DATETIME")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _configure_sqlite(
    engine: Engine,
    *,
    enable_wal: bool,
    busy_timeout_ms: int,
) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        if enable_wal:
            cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def _ensure_sqlite_parent_directory(url_database: str | None) -> None:
    if not _is_file_sqlite_url(url_database):
        return

    Path(url_database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _is_file_sqlite_url(url_database: str | None) -> bool:
    return bool(url_database and url_database != ":memory:")
