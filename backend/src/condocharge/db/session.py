from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from condocharge.core.config import get_settings


def _resolve_sqlite_database_url(database_url: str) -> tuple[str, str | None]:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return database_url, None
    if url.database in (None, "", ":memory:"):
        return database_url, None

    raw_path = url.database
    assert raw_path is not None
    path = Path(raw_path)
    path = (Path.cwd() / path).resolve() if not path.is_absolute() else path.resolve()

    resolved = str(url.set(database=path.as_posix()))
    return resolved, str(path)


def create_db_engine() -> Engine:
    settings = get_settings()
    resolved_url, _ = _resolve_sqlite_database_url(settings.database_url)
    connect_args: dict[str, object] = {}
    if resolved_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    db_engine = create_engine(resolved_url, pool_pre_ping=True, connect_args=connect_args)

    if resolved_url.startswith("sqlite"):
        @event.listens_for(db_engine, "connect")
        def _configure_sqlite_connection(dbapi_connection: object, _: object) -> None:
            if not isinstance(dbapi_connection, sqlite3.Connection):
                return

            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout = 5000")
                # WAL is only valid for file-backed SQLite databases.
                if dbapi_connection.execute("PRAGMA database_list").fetchone()[2] not in ("", ":memory:"):
                    cursor.execute("PRAGMA journal_mode = WAL")
            finally:
                cursor.close()

    return db_engine


def sanitize_database_url_for_logs(database_url: str) -> str:
    try:
        url = make_url(database_url)
    except Exception:
        return "<invalid database url>"

    if url.drivername.startswith("sqlite"):
        database = url.database or ""
        if database in ("", ":memory:"):
            return url.render_as_string(hide_password=True)
        db_name = Path(database).name
        return str(url.set(database=f".../{db_name}"))

    sanitized = url
    if url.username:
        sanitized = sanitized.set(username="***")
    if url.password is not None:
        sanitized = sanitized.set(password="***")
    if url.database:
        sanitized = sanitized.set(database="***")
    return sanitized.render_as_string(hide_password=False)


def sanitize_sqlite_path_for_logs(sqlite_path: str | None) -> str | None:
    if not sqlite_path:
        return None
    return str(Path("...") / Path(sqlite_path).name)


RESOLVED_DATABASE_URL, RESOLVED_SQLITE_PATH = _resolve_sqlite_database_url(get_settings().database_url)
engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
