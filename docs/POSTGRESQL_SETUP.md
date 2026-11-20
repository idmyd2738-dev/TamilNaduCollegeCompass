# PostgreSQL setup

## Requirements

- Python 3.12.
- PostgreSQL with permission to use the dedicated `collegehub` schema.
- The PostgreSQL `vector` extension available to the database user/provider.
- Dependencies from `requirements.txt`: SQLAlchemy 2.x, Alembic, psycopg 3, pgvector, and python-dotenv.

## Configure the connection

Set `DATABASE_URL` in the process environment or local `.env`:

```text
postgresql+psycopg://<user>:<password>@<host>:5432/<database>
```

`database.py` loads the project `.env` locally without overriding environment variables already present in the process. Do not commit `.env`, print its value, or put credentials in logs or source code.

Without a URL, the SQLAlchemy layer uses the separate `instance/collegehub.sqlite3` database. It never silently switches public database-mode routes to the bundled `sample_colleges.db`.

## Schema and migrations

Application tables and Alembic's version table live in schema `collegehub`; existing public tables are not part of the migration scope. The extension may be installed in `public` so the schema can resolve the `vector` type. `database.py` sets a transaction-scoped search path for application connections.

Migrations are explicit operations and do not run on app import:

```powershell
python -m alembic history
python -m alembic current
python -m alembic check
python -m alembic upgrade head
```

Review the target URL and migration contents before applying. The Neon environment has been tested: PostgreSQL 18.7, database `collegehub`, pgvector 0.8.7, and Alembic revision `b7c41e98f2ad`. These facts apply only to that configured environment.

## Tests

SQLite model and migration tests use temporary databases. Optional PostgreSQL compatibility tests require a dedicated database URL whose database name contains `test`, `tests`, or `pytest`:

```powershell
$env:TEST_POSTGRESQL_DATABASE_URL = "postgresql+psycopg://<user>:<password>@localhost:5432/collegehub_test"
python -m unittest discover -s tests -p "test_universal_database.py" -v
```

Never set the test URL to production. Without it, the automated PostgreSQL compatibility class is skipped; live Neon smoke tests are separate from that suite.
