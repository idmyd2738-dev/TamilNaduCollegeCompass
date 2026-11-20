import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import inspect, text

from database import UNIVERSAL_DATABASE_SCHEMA, create_database, resolve_database_url
from models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
LEGACY_SQLITE_TABLES = {
    "academic_years",
    "facilities",
    "information_sources",
    "verification_records",
}


def configured_url() -> str:
    override = config.attributes.get("connection_url")
    if override:
        return resolve_database_url(override)
    return resolve_database_url(os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url"))


def database_object_filter(schema_tables: set[str]):
    def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
        if type_ == "schema":
            return name in (None, UNIVERSAL_DATABASE_SCHEMA)
        if type_ == "table":
            if name == "alembic_version":
                return False
            if parent_names.get("schema_name") is None:
                return name in schema_tables
        return True

    return include_name


def run_migrations_offline() -> None:
    context.configure(
        url=configured_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database = create_database(configured_url())
    try:
        with database.engine.connect() as connection:
            version_table_schema = None
            include_name = None
            if connection.dialect.name == "sqlite":
                existing_tables = set(inspect(connection).get_table_names())
                collisions = existing_tables & LEGACY_SQLITE_TABLES
                if collisions and "alembic_version" not in existing_tables:
                    names = ", ".join(sorted(collisions))
                    raise RuntimeError(
                        "Refusing to apply the universal schema to a legacy CollegeHub "
                        f"SQLite database (conflicting tables: {names}). Use the separate "
                        "instance/collegehub.sqlite3 database."
                    )
            elif connection.dialect.name == "postgresql":
                schema_exists = connection.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
                    {"schema": UNIVERSAL_DATABASE_SCHEMA},
                ).scalar_one()
                if not schema_exists:
                    connection.exec_driver_sql(
                        f'CREATE SCHEMA "{UNIVERSAL_DATABASE_SCHEMA}"'
                    )
                    connection.commit()
                connection.dialect.default_schema_name = UNIVERSAL_DATABASE_SCHEMA

                existing_tables = set(
                    inspect(connection).get_table_names(schema=UNIVERSAL_DATABASE_SCHEMA)
                )
                include_name = database_object_filter(existing_tables)
                if connection.in_transaction():
                    connection.commit()
                if existing_tables and "alembic_version" not in existing_tables:
                    names = ", ".join(sorted(existing_tables))
                    raise RuntimeError(
                        f"Refusing to migrate non-empty schema {UNIVERSAL_DATABASE_SCHEMA!r} "
                        f"without an Alembic version table (found: {names})."
                    )
                version_table_schema = UNIVERSAL_DATABASE_SCHEMA
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
                render_as_batch=connection.dialect.name == "sqlite",
                version_table_schema=version_table_schema,
                include_schemas=connection.dialect.name == "postgresql",
                include_name=include_name,
            )
            with context.begin_transaction():
                context.run_migrations()
            if connection.dialect.name == "sqlite" and connection.in_transaction():
                connection.commit()
    finally:
        database.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
