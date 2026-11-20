import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = BASE_DIR / "instance" / "collegehub.sqlite3"
UNIVERSAL_DATABASE_SCHEMA = "collegehub"
load_dotenv(BASE_DIR / ".env")


def resolve_database_url(value: str | None = None) -> str:
    raw_url = value or os.environ.get("DATABASE_URL")
    if not raw_url:
        DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        return URL.create("sqlite", database=str(DEFAULT_SQLITE_PATH)).render_as_string(
            hide_password=False
        )
    if raw_url.startswith("postgres://"):
        return "postgresql+psycopg://" + raw_url[len("postgres://"):]
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://"):]
    return raw_url


@dataclass(frozen=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    def session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()


def create_database(value: str | None = None) -> Database:
    resolved_url = resolve_database_url(value)
    is_sqlite = resolved_url.startswith("sqlite")
    is_memory_database = resolved_url in {"sqlite://", "sqlite:///:memory:"}
    engine_options = {"pool_pre_ping": True}
    if is_sqlite:
        engine_options["connect_args"] = {"check_same_thread": False}
        if is_memory_database:
            engine_options["poolclass"] = StaticPool

    engine = create_engine(resolved_url, **engine_options)
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    elif resolved_url.startswith("postgresql"):
        @event.listens_for(engine, "begin")
        def set_postgresql_search_path(connection):
            connection.exec_driver_sql(
                f'SET LOCAL search_path TO "{UNIVERSAL_DATABASE_SCHEMA}", public'
            )

    return Database(
        engine=engine,
        session_factory=sessionmaker(bind=engine, expire_on_commit=False),
    )


database = create_database()
